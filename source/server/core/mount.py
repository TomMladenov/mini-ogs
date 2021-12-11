#!/usr/bin/env python3

import PyTrinamic
from PyTrinamic.connections.ConnectionManager import ConnectionManager
from PyTrinamic.modules.TMCM1240.TMCM_1240 import TMCM_1240
import time
import datetime
from datetime import timedelta
import sys
import threading
import enum
import logging
import katpoint
from core.axis import Axis, AxisState, AxisException, AxisType
from core.camera import CameraState
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
import numpy as np

class MountException(Exception):
    pass


class Mount(object):

    def __init__(self, parent, config, logging_level):

        logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.config = config
        self.running = True

        self.name = self.config["name"]

        self.pm = katpoint.PointingModel() # define an empty pointing model
        self.model_active = False

        if self.config["use_test_calib"]:
            self.calib_points_az = self.config["calib_az_test"]
            self.calib_points_el = self.config["calib_el_test"]
        else:
            self.calib_points_az = self.config["calib_az"]
            self.calib_points_el = self.config["calib_el"]

        self.calibration_jobs = []
        self.calibrating = False
        

        try:
            self.cm0 = ConnectionManager(["--port=/dev/ttyACM0", "--data-rate=1000000"], debug=False)
            self.interface0 = self.cm0.connect()
            self.drive0 = TMCM_1240(connection=self.interface0)
            self.drive0_addr = self.drive0.getGlobalParameter(self.drive0.GPs.serialAddress, bank=0)

            self.cm1 = ConnectionManager(["--port=/dev/ttyACM1", "--data-rate=1000000"], debug=False)
            self.interface1 = self.cm1.connect()
            self.drive1 = TMCM_1240(connection=self.interface1)
            self.drive1_addr = self.drive1.getGlobalParameter(self.drive1.GPs.serialAddress, bank=0)
        except Exception as e:
            logging.critical("Exception encountered during mount INIT {}".format(e))
            sys.exit(0)


        if self.drive0_addr == 1 and self.drive1_addr == 2:
            logging.info("drive0 has serialAddress 1: linking /dev/ttyACM0 -> Azimuth")
            self.azimuth = Axis(self, drive=self.drive0, type=AxisType.AZIMUTH, config=self.config["azimuth"], debug=True)

            logging.info("drive1 has serialAddress 2: linking /dev/ttyACM1 -> Elevation")
            self.elevation = Axis(self, drive=self.drive1,  type=AxisType.ELEVATION, config=self.config["elevation"], debug=True)

        elif self.drive0_addr == 2 and self.drive1_addr == 1:
            logging.info("drive1 has serialAddress 1: linking /dev/ttyACM1 -> Azimuth")
            self.azimuth = Axis(self, drive=self.drive1,  type=AxisType.AZIMUTH, config=self.config["azimuth"], debug=True)

            logging.info("drive0 has serialAddress 2: linking /dev/ttyACM0 -> Elevation")
            self.elevation = Axis(self, drive=self.drive0, type=AxisType.ELEVATION, config=self.config["elevation"], debug=True)

        else:
            logging.critical("Exception encountered during mount INIT")
            sys.exit(0)

        #Start axis threads
        self.azimuth.start()
        self.elevation.start()

    def setPointingModel(self, params):
        try:
            self.pm.set(params)
            success = True
            message = self.pm.values()
            self.model_active = True
        except Exception as e:
            success = False
            message = str(e)
            self.model_active = False

        return {"success" : success, "message" : message}

    def mountToCelestial(self, type, angle):

        # mount = the mount coordinate system
        # celestial = the celestial sphere coordinate system (=mount coordinate system + applied model)

        if type == AxisType.AZIMUTH:
            pos_mount_azimuth = angle
            pos_mount_elevation = self.elevation.pos_mount_degrees

            pos_celestial_azimuth_rad, pos_celestial_elevation_rad = self.pm.reverse(np.radians(pos_mount_azimuth), np.radians(pos_mount_elevation))

            return np.degrees(pos_celestial_azimuth_rad)

        elif type == AxisType.ELEVATION:
            pos_mount_azimuth = self.azimuth.pos_mount_degrees
            pos_mount_elevation = angle

            pos_celestial_azimuth_rad, pos_celestial_elevation_rad = self.pm.reverse(np.radians(pos_mount_azimuth), np.radians(pos_mount_elevation))

            return np.degrees(pos_celestial_elevation_rad)

    def celestialToMount(self, type, angle):
        # mount = the mount coordinate system
        # celestial = the celstial sphere coordinate system (=mount coordinate system + applied model)

        if type == AxisType.AZIMUTH:
            pos_celestial_azimuth = angle
            pos_celestial_elevation = self.elevation.pos_celestial_elevation

            pos_mount_azimuth_rad, pos_mount_elevation_rad = self.pm.apply(np.radians(pos_celestial_azimuth), np.radians(pos_celestial_elevation))

            return np.degrees(pos_mount_azimuth_rad)

        elif type == AxisType.ELEVATION:
            pos_celestial_azimuth = self.azimuth.pos_celestial_elevation
            pos_celestial_elevation = angle

            pos_mount_azimuth_rad, pos_mount_elevation_rad = self.pm.apply(np.radians(pos_celestial_azimuth), np.radians(pos_celestial_elevation))

            return np.degrees(pos_mount_elevation_rad)

    def calibrate(self, points=8):

        # clear the ID list of the previous calibration jobs
        self.calibration_jobs = []

        # log the calibration start time
        start_time = datetime.datetime.utcnow()

        if self.parent.guider.state == CameraState.STILL:

            # set a flag indicating we are in a calibration procedure, and that we are not to be messed with
            self.calibrating = True

            # add the listener which will modifying concurrent job start dates for
            self.parent.scheduler.add_listener(self.updateCalibrationJob, EVENT_JOB_EXECUTED)

            # schedule preliminary gotoPosition jobs every minute, the job listener will glue them together nby modifying the start time of the next once the previous one executes
            n = 0
            for az, el in zip(self.calib_points_az, self.calib_points_el):

                scheduling_time = start_time + timedelta(minutes=n)
                goto_job = self.parent.scheduler.add_job(self.gotoMountPosition, trigger='date', run_date=scheduling_time, args=None, kwargs={"az_mount" : az, "el_mount" : el}, name="Move to calibration point {} az{} el{}".format(n, az, el))
                self.calibration_jobs.append(goto_job.id)
                
                fits_time = start_time + timedelta(minutes=n + 1)
                capture_job = self.parent.scheduler.add_job(self.parent.guider.captureFits, trigger='date', run_date=fits_time, args=None, kwargs={"suffix" : "calibration{}".format(n)}, name="Capture FITS at point {}".format(n))
                self.calibration_jobs.append(capture_job.id)

                # store the job id as we will use it later to retrieve the next job
                
                n += 1

            while self.calibrating:
                time.sleep(1)

            self.parent.scheduler.remove_listener(self.updateCalibrationJob)

        else:

            self.calibrating = False
            raise MountException("Camera must be in state STILL to commence calibration")


    def updateCalibrationJob(self, event):

        id_job_finished = event.job_id
        index_job_finished = self.calibration_jobs.index(id_job_finished)
        index_next_job = index_job_finished + 1
        try:
            next_job_id = self.calibration_jobs[index_next_job]
            next_job = self.parent.scheduler.get_job(next_job_id)
            next_job.modify(next_run_time=datetime.datetime.utcnow() + timedelta(seconds=3))
        except Exception as e:
            self.calibrating = False


    def gotoMountPosition(self, az_mount, el_mount):

        if 	az_mount < self.azimuth.config["f_limit_min"] or \
            az_mount > self.azimuth.config["f_limit_max"] or \
            el_mount < self.elevation.config["f_limit_min"] or \
            el_mount > self.elevation.config["f_limit_max"]:
            raise MountException("Requested target position is outside of limits")
        else:
            if self.azimuth.state == AxisState.IDLE and self.elevation.state == AxisState.IDLE:
                response_azimuth = self.azimuth.gotoPosition(az_mount)
                response_elevation = self.elevation.gotoPosition(el_mount)
                time.sleep(2)

                if response_azimuth["success"] and response_elevation["success"]:
                    # wait until both axis are at IDLE again before releasing the job
                    while self.azimuth.state != AxisState.IDLE or self.elevation.state != AxisState.IDLE:
                        time.sleep(1)
                else:
                    raise MountException("Encountered exception during axis commanding: response_azimuth {} response_elevation {}".format(response_azimuth, response_elevation))


    def gotoPosition(self, az, el):
        """Function to make teh moutn slew to a set of celestial coordinates

        This function uses the pointing model and calculates the actual mount angles from the desired celestial sky
        coordinates. These actual axis angles are then commanded to the axes.

        naming convention:
        coordinates in axis/mount frame: xx_mount
        coordinates in celestial frame: xx_celestial

        Arguments:
        az -- the desired azimuth angle in the celestial frame
        el -- the desired elevation angle in the celestial frame
        """

        if not self.model_active:
            # if the pointing model is not active, the celestial frame coordinates are equal to the ones of the mount
            az_mount, el_mount = az, el
        else:
            az_mount_rad, el_mount_rad = self.pm.apply(np.radians(az), np.radians(el))
            az_mount = np.degrees(az_mount_rad)
            el_mount = np.degrees(el_mount_rad)
        
        logging.debug("Slewing to actual axis position AZ{} EL{}".format(az_mount, el_mount))

        if 	az_mount < self.azimuth.config["f_limit_min"] or \
            az_mount > self.azimuth.config["f_limit_max"] or \
            el_mount < self.elevation.config["f_limit_min"] or \
            el_mount > self.elevation.config["f_limit_max"]:
            raise MountException("Requested target position is outside of limits")
        else:
            if self.azimuth.state == AxisState.IDLE and self.elevation.state == AxisState.IDLE:
                response_azimuth = self.azimuth.gotoPosition(az_mount)
                response_elevation = self.elevation.gotoPosition(el_mount)
                time.sleep(2)

                if response_azimuth["success"] and response_elevation["success"]:
                    # wait until both axis are at IDLE again before releasing the job
                    while self.azimuth.state != AxisState.IDLE or self.elevation.state != AxisState.IDLE:
                        time.sleep(1)
                else:
                    raise MountException("Encountered exception during axis commanding: response_azimuth {} response_elevation {}".format(response_azimuth, response_elevation))


    def gotoVelocity(self, vel_az, vel_el):
        """Command the axis of the mount at a certain velocity

        Arguments:
        vel_az -- the desired rotational speed for the azimuth axis in degrees/second
        vel_el -- the desired rotational speed for the elevation axis in degrees/second
        """

        if 	(self.azimuth.state == AxisState.IDLE or self.azimuth.state == AxisState.GOTO_VELOCITY) and \
            (self.elevation.state == AxisState.IDLE or self.elevation.state == AxisState.GOTO_VELOCITY):
            self.azimuth.gotoVelocity(vel_az)
            self.elevation.gotoVelocity(vel_el)
            time.sleep(2)

    def setPosition(self, az, el):
        self.azimuth.setPosition(az)
        self.elevation.setPosition(el)
        time.sleep(2)

    def startTracking(self):
        """Command the mount to start tracking
        """		

        if self.parent.object.objectLoaded():

            object_az, object_el = self.parent.object.getPosition()
        
            if 	self.azimuth.state == AxisState.IDLE and self.elevation.state == AxisState.IDLE and \
                object_az > self.azimuth.config["f_limit_min"] and object_az < self.azimuth.config["f_limit_max"] and \
                object_el > self.elevation.config["f_limit_min"] and object_el < self.elevation.config["f_limit_max"]:

                self.azimuth.startTracking()
                self.elevation.startTracking()

    def park(self):
        if (self.azimuth.state == AxisState.IDLE or self.azimuth.state == AxisState.OOL) and \
            (self.elevation.state == AxisState.IDLE or self.elevation.state == AxisState.OOL):
            self.azimuth.park()
            self.elevation.park()

    def setPidPositionLoop(self, p, i, d):
        self.azimuth.setPidPositionLoop(p, i, d)
        self.elevation.setPidPositionLoop(p, i, d)

    def setPidOffAxisLoop(self, p, i, d):
        self.azimuth.setPidOffAxisLoop(p, i, d)
        self.elevation.setPidOffAxisLoop(p, i, d)       

    def abort(self):
        response_azimuth = self.azimuth.abort()
        response_elevation = self.elevation.abort()
        time.sleep(2)	

        if response_azimuth["success"] and response_elevation["success"]:
            # wait until both axis are at IDLE again before releasing the job
            while self.azimuth.state != AxisState.IDLE or self.elevation.state != AxisState.IDLE:
                time.sleep(1)
        else:
            raise MountException("Encountered exception during axis commanding: response_azimuth {} response_elevation {}".format(response_azimuth, response_elevation))		


    def getStatus(self):
        return {
                    "azimuth" : self.azimuth.status,
                    "elevation" : self.elevation.status
                }


    def stop(self):
        self.azimuth.stop()
        self.elevation.stop()
        self.interface0.close()
        self.interface1.close()

