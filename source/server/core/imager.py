#!/usr/bin/env python3

import enum
import logging
import os
import sys
import threading
from threading import Timer
from core.timer import CustomTimer
import time
import json

import cv2
import numpy as np
import imagezmq
import zwoasi as asi


class ImagerType(enum.Enum):
    MAIN = 0
    GUIDER = 1


class ImagerState(enum.Enum):
    IDLE=0
    STREAMING=1


class Imager(threading.Thread):

    def __init__(self, parent, type, config, logging_level):
        super(Imager, self).__init__()

        logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.config = config
        self.type = type
        self.name = self.config["s_name"]
        self.running = True

        self.fps = 0
        self.temperature = 0

        self.prevLoopTime = time.time()
        self.currentLoopTime = time.time()

        self.sender = imagezmq.ImageSender("tcp://{}:{}".format(self.config["s_streamhost"], self.config["i_streamport"]), REQ_REP=False)

        # drive mutex
        self.mutex = threading.Lock()

        self.state = ImagerState.IDLE
        self.nextState = ImagerState.IDLE

        self.fps_array = []     

        libfile = '/opt/lib/libASICamera2.so.1.19.1'

        try:
            asi.init(libfile)
        except Exception as e:
            print(e)

        logging.info('loaded ASI lib file {FILE}'.format(FILE=libfile))

        try:
            self.camera = asi.Camera(0)
            #self.camModel = self.camera._get_camera_property(1)['Name']
        except Exception as e:
            logging.error('No ASI camera detected {MSG}'.format(MSG=e))
            os._exit(0)

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


    def startStreaming(self):
        condition = (self.state == self.nextState == ImagerState.IDLE)
        self.__executeCameraCommand(condition, ImagerState.STREAMING, self.camera.start_video_capture)


    def stopStreaming(self):
        condition = (self.state == self.nextState == ImagerState.STREAMING)
        self.__executeCameraCommand(condition, ImagerState.IDLE, self.camera.stop_video_capture)


    def setExposure(self, exposure):
        condition = (self.state == self.nextState == ImagerState.IDLE) or (self.state == self.nextState == ImagerState.STREAMING)
        self.__executeCameraCommand(condition, self.state, self.camera.set_control_value, asi.ASI_EXPOSURE, exposure)


    def setGain(self, gain):
        condition = (self.state == self.nextState == ImagerState.IDLE) or (self.state == self.nextState == ImagerState.STREAMING)
        self.__executeCameraCommand(condition, self.state, self.camera.set_control_value, asi.ASI_GAIN, gain)


    def setFlip(self, flip):
        condition = (self.state == self.nextState == ImagerState.IDLE) or (self.state == self.nextState == ImagerState.STREAMING)
        self.__executeCameraCommand(condition, self.state, self.camera.set_control_value, asi.ASI_FLIP, flip)


    def stop(self):
        self.stopStreaming()
        self.poll_timer.cancel()
        self.publish_timer.cancel()
        self.running = False


    def getStatus(self):
        status =    {
                        "state" : ImagerState(self.state).name,
                        "fps" : self.fps,
                        "temperature" : self.temperature
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

            if self.state == ImagerState.IDLE:
                self.fps = 0

            elif self.state == ImagerState.STREAMING:
                self.img = self.camera.capture_video_frame(buffer_=None, filename=None, timeout=None)
                result, buffer = cv2.imencode('.jpg', self.img, [int(cv2.IMWRITE_JPEG_QUALITY), self.config["i_transport_compression"]])
                metadata = json.dumps({"config":self.config, "status": self.getStatus()})
                self.sender.send_image(metadata, buffer)

                # calculate an average frames/sec using 10 loops
                fps = round(1.0 / self.loopdelta, 2)
                self.fps_array.append(fps)
                if len(self.fps_array) >= 10:
                    self.fps = round(sum(self.fps_array)/len(self.fps_array), 2)
                    # clear the array again
                    self.fps_array = []

            # release the mutex
            self.mutex.release()

            if self.state == ImagerState.IDLE:
                time.sleep(1)
            else:
                pass
