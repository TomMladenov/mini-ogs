#!/usr/bin/env python3

import enum
import logging
import os
import sys
import threading
from threading import Timer
from core.timer import CustomTimer
from core.axis import AxisType
import time
import json
import datetime

from astropy.io import fits
from astropy.coordinates import SkyCoord, EarthLocation
from astropy import coordinates as coord
from astropy.coordinates.tests.utils import randomly_sample_sphere
from astropy.time import Time
from astropy import units as u

import cv2
import numpy as np
import imagezmq
import zwoasi as asi

class CanmeraException(Exception):
    pass


class CameraType(enum.Enum):
    GUIDER = 0
    IMAGER = 1


class CameraState(enum.Enum):
    IDLE=0
    STREAMING=1
    STILL=2


class Camera(threading.Thread):

    def __init__(self, parent, type, config, logging_level):
        super(Camera, self).__init__()

        logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.config = config
        self.type = type
        self.name = self.config["name"]
        self.running = True

        self.fps = 0
        self.temperature = 0

        self.platescale_x = (180.0/np.pi)*(1/self.config["f_focal"])*self.config["f_pitch_x"]*self.config["i_bins"] #degrees per pixel
        self.platescale_x_arcsec = self.platescale_x * 3600.0 # arcseconds per pixel

        self.platescale_y = (180.0/np.pi)*(1/self.config["f_focal"])*self.config["f_pitch_y"]*self.config["i_bins"] #degrees per pixel
        self.platescale_y_arcsec = self.platescale_y * 3600.0 # arcseconds per pixel

        self.prevLoopTime = time.time()
        self.currentLoopTime = time.time()

        self.sender = imagezmq.ImageSender("tcp://{}:{}".format(self.config["s_streamhost"], self.config["i_streamport"]), REQ_REP=False)

        # blob detector configuration
        self.object_detection_enabled = self.config["b_object_detection_enabled"]

        self.params = cv2.SimpleBlobDetector_Params()
        self.params.filterByColor = False
        self.params.blobColor = 0 

        # Extracted blobs have an area between minArea (inclusive) and maxArea (exclusive).
        self.params.filterByArea = True
        self.params.minArea = 5. # Highly depending on image resolution and dice size
        self.params.maxArea = 400. # float! Highly depending on image resolution.

        self.params.filterByCircularity = True
        self.params.minCircularity = 0. # 0.7 could be rectangular, too. 1 is round. Not set because the dots are not always round when they are damaged, for example.
        self.params.maxCircularity = 3.4028234663852886e+38 # infinity.

        self.params.filterByConvexity = False
        self.params.minConvexity = 0.
        self.params.maxConvexity = 3.4028234663852886e+38

        self.params.filterByInertia = True # a second way to find round blobs.
        self.params.minInertiaRatio = 0.3 # 1 is round, 0 is anywhat 
        self.params.maxInertiaRatio = 3.4028234663852886e+38 # infinity again

        self.params.minThreshold = 35 # from where to start filtering the image
        self.params.maxThreshold = 255.0 # where to end filtering the image
        self.params.thresholdStep = 25 # steps to go through
        self.params.minDistBetweenBlobs = 3.0 # avoid overlapping blobs. must be bigger than 0. Highly depending on image resolution! 
        self.params.minRepeatability = 2 # if the same blob center is found at different threshold values (within a minDistBetweenBlobs), then it (basically) increases a counter for that blob. if the counter for each blob is >= minRepeatability, then it's a stable blob, and produces a KeyPoint, otherwise the blob is discarded.



        '''
        
        self.params.minThreshold = self.config["i_blob_minthreshold"]
        self.params.maxThreshold = self.config["i_blob_maxthreshold"]
        self.params.thresholdStep = self.config["i_blob_thresholdstep"]
        self.params.blobColor = self.config["i_blob_color"]
        self.params.filterByArea = self.config["b_blob_filterbyarea"]
        self.params.minArea = self.config["i_blob_minarea"]
        self.params.filterByCircularity = self.config["b_blob_filterbycircularity"]
        self.params.filterByConvexity = self.config["b_blob_filterbyconvexity"]
        self.params.filterByInertia = self.config["b_blob_filterbyinertia"]
        self.params.minInertiaRatio = self.config["i_blob_mininertiaratio"]
        self.params.maxInertiaRatio = self.config["i_blob_maxinertiaratio"]
        '''
        self.blob_detector = cv2.SimpleBlobDetector_create(self.params)
        self.keypoints = []

        self.object_x = self.config["i_width"]/2.0
        self.object_y = self.config["i_height"]/2.0

        self.object_offset_x = self.object_x - self.config["i_width"]/2.0
        self.object_offset_y = self.object_y - self.config["i_height"]/2.0

        # below ofcourse assumes the camera frame x=azimuth, y=elevation
        self.object_offset_az =  self.object_offset_x * self.platescale_x
        self.object_offset_el = self.object_offset_y * self.platescale_y

        self.object_in_fov = False

        # drive mutex
        self.mutex = threading.Lock()

        self.state = CameraState.IDLE
        self.nextState = CameraState.IDLE

        self.fps_array = []     

        libfile = '/opt/lib/libASICamera2.so.1.19.1'

        try:
            asi.init(libfile)
        except Exception as e:
            print(e)

        logging.info('loaded ASI lib file {FILE}'.format(FILE=libfile))

        num_cameras = asi.get_num_cameras()
        logging.info('Found {} connected cameras'.format(num_cameras))

        correct_cam_found = False

        if num_cameras == 0:
            logging.error('No ASI camera detected {MSG}, check the USB 3.0 connections...'.format(MSG=e))
            os._exit(0)

        elif num_cameras == 1:
            try:
                index = 0
                logging.info('Attempting connection to Camera with ID {}'.format(index))
                self.camera = asi.Camera(index)
                logging.info('Connection OK')
                id = self.camera.get_id()
                if id != self.config["s_id"]:
                    correct_cam_found = False
                    logging.error('Connected to camera, but returned ID ({}) does not match the expected ID ({}), exiting...'.format(id, self.config["s_id"]))
                    os._exit(0)
                else:
                    logging.info('Connected to camera with correct ID ({}), used dev index {}'.format(id, index))
                    correct_cam_found = True

            except Exception as e:
                correct_cam_found = False                
                logging.error('Error connecting to camera with index {}, exception: {}'.format(index, e))
                os._exit(0)

        elif num_cameras == 2:

            try:
                index = 0
                logging.info('Attempting connection to Camera with ID {}'.format(index))
                self.camera = asi.Camera(index)
                logging.info('Connection OK')
                id = self.camera.get_id()
                if id != self.config["s_id"]:
                    correct_cam_found = False
                    logging.error('Connected to camera, but returned ID ({}) does not match the expected ID ({}), trying next id'.format(id, self.config["s_id"]))
                else:
                    logging.info('Connected to camera with correct ID ({}), used dev index {}'.format(id, index))
                    correct_cam_found = True

            except Exception as e:
                correct_cam_found = False
                logging.error('Error connecting to camera with index {}, exception: {}'.format(index, e))
                # do not exit as we might still have luck with the second camera since 2 are connected

            if not correct_cam_found:
                try:
                    index = 1
                    logging.info('Attempting connection to Camera with ID {}'.format(index))
                    self.camera = asi.Camera(index)
                    logging.info('Connection OK')
                    id = self.camera.get_id()
                    if id != self.config["s_id"]:
                        correct_cam_found = False
                        logging.error('Connected to camera, but returned ID ({}) does not match the expected ID ({}), exiting...'.format(id, self.config["s_id"]))
                        os._exit(0) 
                    else:
                        logging.info('Found camera with correct ID ({}), used dev index {}'.format(id, index))

                except Exception as e:
                    correct_cam_found = False
                    logging.error('Error connecting to camera with index {}, exception: {}'.format(index, e))          



        self.initCamera()

        # init task timers
        self.poll_timer = CustomTimer(self.config["f_poll_interval"], self.__pollTask).start()
        self.publish_timer = CustomTimer(self.config["f_publish_interval"], self.__publishTask).start()

    def initCamera(self):
        self.camera.set_control_value(asi.ASI_BANDWIDTHOVERLOAD, self.config["i_bandwidth"])
        self.camera.disable_dark_subtract()
        self.camera.set_control_value(asi.ASI_EXPOSURE, self.config["i_exposure"])
        self.camera.set_control_value(asi.ASI_GAIN, self.config["i_gain"])

        self.camera.set_control_value(asi.ASI_WB_B, self.config["i_whitebalance_blue"])
        self.camera.set_control_value(asi.ASI_WB_R, self.config["i_whitebalance_red"])
        self.camera.set_control_value(asi.ASI_GAMMA, self.config["i_gamma"])

        self.camera.set_control_value(asi.ASI_FLIP, self.config["i_flip"])
        self.camera.set_control_value(asi.ASI_HIGH_SPEED_MODE, self.config["b_highspeed"]) 
        self.camera.set_control_value(asi.ASI_HARDWARE_BIN, self.config["b_hwbin"])
        self.camera.set_roi(    start_x = self.config["i_startx"],    \
                                start_y = self.config["i_starty"],    \
                                width = self.config["i_width"],       \
                                height = self.config["i_height"],     \
                                bins = self.config["i_bins"],        \
                                image_type = asi.ASI_IMG_RAW8)


    def getConfig(self):
        return self.config

    def __executeCameraCommand(self, stateCondition, nextStateOnSuccess, cameraCommand, *cameraCommandArgs):

        """ Generic function to execute direct axis commands which are called by an external thread, hence this function
        uses the mutex of this class.

        Parameters
        ----------
        stateCondition : bool
            a boolean expression indicating a prerequisitie for the current state of the FSM
        nextStateOnSuccess : AxisState
            enum indicating the next state of the FSM upon a successful command to the driver
        driveCommand : function
            function of the driver to execute
        *driveCommandargs : args
            variable length argument tuple to pass to the driveCommand
        
        Returns
        -------
        returnMessage : dict
            dict containing a success and message field
        """
        
        if stateCondition:
            
            try:
                self.mutex.acquire()
                logging.debug("{} Mutex acquired".format(self.name))
                cameraCommand(*cameraCommandArgs)
                self.nextState = nextStateOnSuccess
                logging.debug("{} Executed camera function {} with arguments {}".format(self.name, cameraCommand.__name__, cameraCommandArgs))
                self.mutex.release()
                logging.debug("{} Mutex released".format(self.name))
                returnMessage = {"success": True}

            except Exception as e:
                returnMessage = {"success": False, "message": str(e)}

        else:
            returnMessage = {"success": False, "message": "not in correct state or transition in progress"}

        
        logging.info(returnMessage)

       
        self.last_command = cameraCommand.__name__

        return returnMessage

    # operating modes

    def startStreaming(self):
        condition = (self.state == self.nextState == CameraState.IDLE)
        self.__executeCameraCommand(condition, CameraState.STREAMING, self.camera.start_video_capture)
        #self.__executeCameraCommand(condition, CameraState.STREAMING, time.sleep, 0.1)

    def startStill(self):
        condition = (self.state == self.nextState == CameraState.IDLE)
        self.__executeCameraCommand(condition, CameraState.STILL, self.camera.stop_video_capture)
        #self.__executeCameraCommand(condition, CameraState.STREAMING, time.sleep, 0.1)

    def setIdle(self):
        condition = (self.state == self.nextState == CameraState.STREAMING) or (self.state == self.nextState == CameraState.STILL)
        self.__executeCameraCommand(condition, CameraState.IDLE, self.camera.stop_video_capture)


    def setExposure(self, exposure):
        condition = (self.state == self.nextState == CameraState.IDLE) or \
                    (self.state == self.nextState == CameraState.STREAMING) or \
                    (self.state == self.nextState == CameraState.STILL)
        result = self.__executeCameraCommand(condition, self.state, self.camera.set_control_value, asi.ASI_EXPOSURE, exposure)
        if result["success"]:
            self.config["i_exposure"] = exposure


    def setGain(self, gain):
        condition = (self.state == self.nextState == CameraState.IDLE) or \
                    (self.state == self.nextState == CameraState.STREAMING) or \
                    (self.state == self.nextState == CameraState.STILL)
        result = self.__executeCameraCommand(condition, self.state, self.camera.set_control_value, asi.ASI_GAIN, gain)
        if result["success"]:
            self.config["i_gain"] = gain

    def setFlip(self, flip):
        condition = (self.state == self.nextState == CameraState.IDLE) or \
                    (self.state == self.nextState == CameraState.STREAMING) or \
                    (self.state == self.nextState == CameraState.STILL)
        result = self.__executeCameraCommand(condition, self.state, self.camera.set_control_value, asi.ASI_FLIP, flip)
        if result["success"]:
            self.config["i_flip"] = flip

    def enableBlobDetector(self, state):
        self.object_detection_enabled = state
        self.config["b_object_detection_enabled"] = state


    def setTransportCompression(self, compression):
        if compression > 10 and compression < 100:
            self.config["i_transport_compression"] = compression
        else:
            raise CameraException("The value is not in the allowed range")

    def captureFits(self, suffix):
        if (self.state == self.nextState == CameraState.STILL):

            self.mutex.acquire()
            t0 = float(time.time())
            img = self.camera.capture(buffer_=None, filename=None)
            t = (float(time.time())+t0)/2.0 # the exact time of the middle of the frame

            #emit the frame via zmq to allow live monitoring
            result, buffer = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), self.config["i_transport_compression"]])
            metadata = json.dumps({"config":self.config, "status": self.getStatus()})
            self.sender.send_image(metadata, buffer)

            self.mutex.release()

            formatted_timestamp = datetime.datetime.fromtimestamp(t).strftime('%Y%m%d_%H%M%S')
            fname = "{}_{}.fits".format(formatted_timestamp, suffix)

            # Format header
            hdr = fits.Header()
            hdr['DATE-OBS'] = datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S.%f")
            hdr['EXPTIME'] = self.config["i_exposure"]
            hdr['CRPIX1'] = float(self.config["i_width"])/2.0
            hdr['CRPIX2'] = float(self.config["i_height"])/2.0
            hdr['OBJECT'] = suffix
            hdr['BITPIX'] = 8
            hdr['PIXSCAL1'] = self.platescale_x_arcsec
            hdr['PIXSCAL2'] = self.platescale_y_arcsec

            #lat, lon, alt = self.parent.gps.getPosition()
            hdr['GEOD_LAT'] = self.parent.mount.config["f_lat"]
            hdr['GEOD_LON'] = self.parent.mount.config["f_lon"]
            hdr['GEOD_ALT'] = self.parent.mount.config["f_alt"]
            hdr['CENTAZ'] = self.parent.mount.azimuth.pos_mount_degrees
            hdr['CENTALT'] = self.parent.mount.elevation.pos_mount_degrees
            hdr['CRVAL1'] = 0.0
            hdr['CRVAL2'] = 0.0
            hdr['CD1_1'] = 1.0/3600.0
            hdr['CD1_2'] = 0.0
            hdr['CD2_1'] = 0.0
            hdr['CD2_2'] = 1.0/3600.0
            hdr['CUNIT1'] = "deg"
            hdr['CUNIT2'] = "deg"
            hdr['CTYPE1'] = "RA---TAN"
            hdr['CTYPE2'] = "DEC--TAN"
            hdr['CRRES1'] = 0.0
            hdr['CRRES2'] = 0.0
            hdr['EQUINOX'] = 2000.0
            hdr['RADECSYS'] = "ICRS"
            hdr['COSPAR'] = 0
            hdr['OBSERVER'] = 0
            hdr['CENTAZ_M'] = self.parent.mount.azimuth.pos_mount_degrees
            hdr['CENTEL_M'] = self.parent.mount.elevation.pos_mount_degrees
            hdr['CENTAZ_C'] = self.parent.mount.azimuth.pos_celestial_degrees
            hdr['CENTEL_C'] = self.parent.mount.elevation.pos_celestial_degrees
            hdr['AZ_ENC'] = self.parent.mount.azimuth.pos_encoder_degrees
            hdr['EL_ENC'] = self.parent.mount.elevation.pos_encoder_degrees            
            hdr['CALIB'] = str(self.parent.mount.model_active)
            hdr['CALIB_D'] = str(self.parent.mount.pm.values())

            hdr['TEMPERATURE'] = self.temperature

            hdu = fits.PrimaryHDU(data=img, header=hdr)
            dest = self.config["s_fits_storage_dir"] + "/" + fname

            hdu.writeto(dest)
            return dest

    def stop(self):
        self.setIdle()
        self.poll_timer.cancel()
        self.publish_timer.cancel()
        self.running = False

    def getOffAxisValue(self, axis):
        """Return the observed off-axis value in degrees
        """
        if axis == AxisType.AZIMUTH:
            return self.object_offset_az
        else:
            return self.object_offset_el

    def getOffAxisSetpoint(self, axis):
        """Return the configured off-axis setpoint in degrees
        The off-axis setpoint is used to provide a relation between the guider and main imager optically
        An off axis setpoint (default is 0, 0, center of sensor) can be used when the optical axis of the main imager
        and that of the guider are not perfectly aligned.
        """        
        if axis == AxisType.AZIMUTH:
            return self.config["i_offaxis_setpoint_x"] * self.platescale_x
        else:
            return self.config["i_offaxis_setpoint_y"] * self.platescale_y    

    def setOffAxisSetpoint(self, pix_x, pix_y):
        """Set the configured off-axis setpoint in pixels from center
        """   
        if pix_x < self.config["i_width"]/2 and pix_y < self.config["i_height"]/2:
            self.config["i_offaxis_setpoint_x"] = pix_x
            self.config["i_offaxis_setpoint_y"] = pix_y
        else:
            raise CameraException("The offaxis setpoint in pixels is outside of the camera sensor frame!")

    def objectInFov(self):
        return self.object_in_fov


    def getStatus(self):
        status =    {
                        "state" : CameraState(self.state).name,
                        "fps" : self.fps,
                        "temperature" : self.temperature,
                        "object_x" : self.object_x,
                        "object_y" : self.object_y,
                        "object_offset_x" : self.object_offset_x,
                        "object_offset_y" : self.object_offset_y,
                        "object_offset_az" : self.object_offset_az,
                        "object_offset_el" : self.object_offset_el
                    }
        return status

    # functions called internally by the task timers

    def __pollTask(self):
        self.mutex.acquire()
        self.temperature = self.camera.get_control_value(asi.ASI_TEMPERATURE)[0]/10.0
        self.mutex.release()


    def __publishTask(self):
        current_status = self.getStatus()
        self.parent.telegraf.metric(self.name, current_status)


    def run(self):
        while self.running:

            # get the time between 2 loops
            self.currentLoopTime = time.time()
            self.loopdelta = self.currentLoopTime - self.prevLoopTime
            self.prevLoopTime = self.currentLoopTime
           
            # acquire the mutex
            self.mutex.acquire()

            # state register
            self.state = self.nextState

            if self.state == CameraState.IDLE:
                self.fps = 0

            elif self.state == CameraState.STILL:
                self.fps = 0

            elif self.state == CameraState.STREAMING:
                try:
                    self.img = self.camera.capture_video_frame(buffer_=None, filename=None, timeout=(2*self.config["i_exposure"])/1000.0 + 500.0)
                    #self.img = self.camera.capture()
                    result, buffer = cv2.imencode('.jpg', self.img, [int(cv2.IMWRITE_JPEG_QUALITY), self.config["i_transport_compression"]])

                    if self.object_detection_enabled:
                        self.keypoints = self.blob_detector.detect(self.img)
                        if self.keypoints != []:
                            target = self.keypoints[0]
                            self.object_x = target.pt[0]
                            self.object_y = target.pt[1]
                            self.object_in_fov = True
                        else:             
                            self.object_in_fov = False
                    
                    else:
                        self.object_in_fov = False
                        self.object_x = self.config["i_width"]/2.0
                        self.object_y = self.config["i_height"]/2.0

                    self.object_offset_x = self.object_x - self.config["i_width"]/2.0
                    self.object_offset_y = self.object_y - self.config["i_height"]/2.0

                    # below ofcourse assumes the camera frame x=azimuth, y=elevation
                    self.object_offset_az =  self.object_offset_x * self.platescale_x
                    self.object_offset_el = self.object_offset_y * self.platescale_y


                    metadata = json.dumps({"config":self.config, "status": self.getStatus()})
                    self.sender.send_image(metadata, buffer)

                    # calculate an average frames/sec using 10 loops
                    fps = round(1.0 / self.loopdelta, 2)
                    self.fps_array.append(fps)
                    if len(self.fps_array) >= 10:
                        self.fps = round(sum(self.fps_array)/len(self.fps_array), 2)
                        # clear the array again
                        self.fps_array = []
                except Exception as e:
                    logging.error('Timeout on frame acquisition! {}'.format(self.config["s_name"]))
                    pass

            # release the mutex
            self.mutex.release()

            if self.state == CameraState.IDLE or self.state == CameraState.STILL:
                time.sleep(1)
            else:
                pass
