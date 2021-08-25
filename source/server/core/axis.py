#!/usr/bin/env python3

import datetime
import enum
import logging
import math
import sys
import threading
import time
from core.timer import CustomTimer

import PyTrinamic
from PyTrinamic.connections.ConnectionManager import ConnectionManager
from PyTrinamic.modules.TMCM1240.TMCM_1240 import TMCM_1240, _APs

from core.PID import PID


class AxisException(Exception):
    pass

class AxisState(enum.Enum):

    IDLE = 0
    GOTO_POSITION = 1
    GOTO_VELOCITY = 2
    ABORT = 3
    TRACK = 4
    OOL = 5
    PARK = 6

class AxisType(enum.Enum):
    AZIMUTH = 0
    ELEVATION = 1


class Axis(threading.Thread):

    def __init__(self, parent, drive, type, debug, config):
        super(Axis, self).__init__()
        logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.drive = drive
        self.type = type
        self.config = config
        self.name = self.config["s_name"]
        self.debug = debug

        self.errors = 0
        self.success = 0
        self.last_error = ""
        self.last_command = ""
        self.looptime = 0.0
        self.looprate = 0.0

        self.pos_mount_microsteps = 0
        self.pos_mount_degrees = 0.0
        self.pos_celestial_degrees = 0.0

        self.pos_encoder_microsteps = 0
        self.pos_encoder_degrees = 0.0

        self.vel_internal_microsteps = 0
        self.vel_internal_degrees = 0.0

        self.driver_error_flags = 0
        self.driver_status_flags = 0

        self.driver_temperature = 0
        self.driver_voltage = 0.0

        self.pos_target_degrees = 0.0
        self.pos_error_degrees = 0.0

        self.previous_set_velocity = 0

        self.microsteps = 64.0 # usteps per pulse
        self.ppr = 200.0 # pulses per stepper revolution (full steps of the stepper motor)
        self.axisRatio = 720.0 # stepper motor revolutions for 1 rotation about telescope axis
        self.degreesPerUstep = (360.0/(self.microsteps * self.ppr * self.axisRatio)) # degrees/ ustep
        self.degreesPerStep = (360.0/(self.ppr * self.axisRatio)) # degrees per step

        # drive mutex
        self.mutex = threading.Lock()

        self.prevLoopTime = datetime.datetime.utcnow()
        self.currentLoopTime = datetime.datetime.utcnow()

        self.configureDrive(self.config)

        self.pid = PID(Kp=self.config["f_kp_controller"], Ki=self.config["f_ki_controller"], Kd=self.config["f_kd_controller"])
        self.pid.setSampleTime(self.config["f_looprate"])
        self.pid.setWindup(self.microstepsToDegrees(self.config["i_axisparam_4"]))

        # init flags
        self.running = True
        self.out_of_limits = False
        self.on_target = False

        # set default states
        self.state = AxisState.IDLE
        self.nextState = AxisState.IDLE

        # init task timers
        self.poll_timer = CustomTimer(self.config["f_poll_interval"], self.__pollTask).start()
        self.publish_timer = CustomTimer(self.config["f_publish_interval"], self.__publishTask).start()

        logging.debug("{} Initialised axis ".format(self.name))

    def getStatus(self):
        status = 	{
                        "name" : self.name,
                        "state"  : AxisState(self.state).name,
                        "errors" : self.errors,
                        "success"  : self.success,
                        "last_error"  : self.last_error,
                        "last_command"  : self.last_command,
                        "looptime" : self.looptime,
                        "looprate" : self.looprate,
                        "pos_mount_microsteps" : self.pos_mount_microsteps,
                        "pos_mount_degrees" : self.pos_mount_degrees,
                        "pos_celestial_degrees" : self.pos_celestial_degrees,
                        "pos_encoder_microsteps" : self.pos_encoder_microsteps,
                        "pos_encoder_degrees" : self.pos_encoder_degrees,
                        "vel_internal_microsteps" : self.vel_internal_microsteps,
                        "vel_internal_degrees"  : self.vel_internal_degrees,
                        "driver_error_flags"  : self.driver_error_flags,
                        "driver_status_flags"  : self.driver_status_flags,
                        "driver_temperature"  : self.driver_temperature,
                        "driver_voltage"  : self.driver_voltage,
                        "pos_target_degrees" : self.pos_target_degrees,
                        "pos_error_degrees" : self.pos_error_degrees,
                        "out_of_limits" : 1 if self.out_of_limits else 0,
                        "P" : self.pid.PTerm,
                        "I" : self.pid.Ki * self.pid.ITerm,
                        "D" : self.pid.Kd * self.pid.DTerm,
                        "on_target" : 1 if self.on_target else 0,
                        "correction_active" : 1 if self.parent.model_active else 0
                    }
        return status					


    def microstepsToDegrees(self, microsteps):
        d = microsteps * self.degreesPerUstep
        return d


    def degreesToMicrosteps(self, degrees):
        m = float(degrees) / self.degreesPerUstep
        return int(m)


    def configureDrive(self, config):
        for key in config:
            if "axisparam" in key:
                parameter = int(key.split("_")[2])
                value = config[key]	
                status = self.__executeAxisCommand(True, AxisState.IDLE, self.drive.setAxisParameter, parameter, value)

    def setPIDvalues(self, P, I, D):
        self.pid.setKp(P)
        self.pid.setKi(I)
        self.pid.setKd(D)

    def setPosition(self, position_degrees):
        position_usteps = self.degreesToMicrosteps(position_degrees)
        condition = (self.state == self.nextState == AxisState.IDLE)
        self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setActualPosition, position_usteps)
        self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setTargetPosition, position_usteps)
        self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setAxisParameter, _APs.EncoderPosition, position_usteps)


    def gotoPosition(self, position_degrees_mount):
        position_usteps = self.degreesToMicrosteps(position_degrees_mount)
        condition = (self.state == self.nextState == AxisState.IDLE)
        return self.__executeAxisCommand(condition, AxisState.GOTO_POSITION, self.drive.moveTo, position_usteps)


    def gotoVelocity(self, velocity):
        speed_usteps = self.degreesToMicrosteps(velocity)
        if abs(speed_usteps) > self.config["i_axisparam_4"]:
            speed_usteps = int(math.copysign(self.config["i_axisparam_4"], speed_usteps))
            
        condition = (self.state == self.nextState == AxisState.IDLE) or (self.state == self.nextState == AxisState.GOTO_VELOCITY)
        return self.__executeAxisCommand(condition, AxisState.GOTO_VELOCITY, self.drive.rotate, speed_usteps)


    def startTracking(self):
        if self.state == AxisState.IDLE:
            self.nextState = AxisState.TRACK
        

    def abort(self):
        condition = (self.state == self.nextState == AxisState.GOTO_POSITION) or \
                    (self.state == self.nextState == AxisState.GOTO_VELOCITY) or \
                    (self.state == self.nextState == AxisState.TRACK) or \
                    (self.state == self.nextState == AxisState.PARK)
        return self.__executeAxisCommand(condition, AxisState.ABORT, self.drive.stop)

    def park(self):
        position_usteps = self.degreesToMicrosteps(0)
        condition = (self.state == self.nextState == AxisState.IDLE) or (self.state == self.nextState == AxisState.OOL)
        return self.__executeAxisCommand(condition, AxisState.PARK, self.drive.moveTo, position_usteps)        

    def __executeAxisCommand(self, stateCondition, nextStateOnSuccess, driveCommand, *driveCommandArgs):

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

            # acquire the mutex
            # -----------------
            self.mutex.acquire()
            logging.debug("{} Mutex acquired".format(self.name))
            # -----------------

            retries = 0
            while retries < 5:
                try:
                    driveCommand(*driveCommandArgs)
                    success = True
                    self.nextState = nextStateOnSuccess
                    break

                except Exception as e:
                    encountered_exception = str(e)
                    
                    retries += 1
                    time.sleep(0.5)
                    success = False
            
            # release the mutex
            # -----------------
            self.mutex.release()
            logging.debug("{} Mutex released".format(self.name))
            # -----------------

            if success:
                returnMessage = {"success": True}
                logging.info("{} Succesfully executed command {} arguments {} ({} retries)".format(self.name, driveCommand.__name__, driveCommandArgs, retries))
            else:
                logging.warning("{} Failed to execute command {} arguments {}, {} attempts, exception {}".format(self.name, driveCommand.__name__, driveCommandArgs, retries, encountered_exception))
                returnMessage = {"success": False, "message": encountered_exception}

        else:
            returnMessage = {"success": False, "message": "not in correct state or transition in progress"}

        logging.debug(returnMessage)
        self.last_command = driveCommand.__name__

        return returnMessage


    def __getAxisStatus(self):

        try:
            self.pos_mount_microsteps = self.drive.getActualPosition()
            self.pos_mount_degrees = self.microstepsToDegrees(self.pos_mount_microsteps)

            if self.parent.model_active:
                self.pos_celestial_degrees = self.parent.mountToCelestial(self.type, self.pos_mount_degrees)
            else:
                self.pos_celestial_degrees = self.pos_mount_degrees

            self.success += 1

        except Exception as e:
            self.last_error = str(e)
            self.errors += 1


        try:
            pos_encoder_microsteps = self.drive.getAxisParameter(_APs.EncoderPosition)

            if pos_encoder_microsteps >= 2**31:
                pos_encoder_microsteps -= 2**32
                
            if self.type == AxisType.AZIMUTH:
                self.pos_encoder_microsteps = -pos_encoder_microsteps
            else:
                self.pos_encoder_microsteps = pos_encoder_microsteps            

            self.pos_encoder_degrees = self.microstepsToDegrees(self.pos_encoder_microsteps)
            self.success += 1

        # error in telemetry readout is not critical
        except Exception as e:
            self.last_error = str(e)
            self.errors += 1			


        try:
            self.vel_internal_microsteps = self.drive.getActualVelocity()
            self.vel_internal_degrees = self.microstepsToDegrees(self.vel_internal_microsteps)
            self.success += 1

        # error in telemetry readout is not critical
        except Exception as e:
            self.last_error = str(e)
            self.errors += 1


    def __positionReached(self): 
        
        try:
            positionReached = self.drive.positionReached()
            valid = True

        except Exception as e:
            positionReached = False
            valid = False
            self.last_error = str(e)
            self.errors += 1
            
        finally:
            return valid, positionReached


    def __isStopped(self):
        try:
            isStopped = (self.drive.getActualVelocity() == 0)
            valid = True

        except Exception as e:
            isStopped = False
            valid = False

            self.last_error = str(e)
            self.errors += 1
            
        finally:
            return valid, isStopped


    def __setVelocity(self, velocity_degrees):
        velocity_usteps = self.degreesToMicrosteps(velocity_degrees)
        if velocity_usteps != self.previous_set_velocity:
            try:
                if (velocity_usteps < -self.config["i_axisparam_4"]):
                    velocity_usteps = -self.config["i_axisparam_4"]

                elif (velocity_usteps > self.config["i_axisparam_4"]):
                    velocity_usteps = self.config["i_axisparam_4"]

                self.drive.rotate(velocity_usteps)
                self.previous_set_velocity = velocity_usteps
            except Exception as e:
                pass

    def __abort(self):
        retries = 0
        while retries < 10:
            try:
                self.drive.stop()
                success = True
                break

            except Exception as e:
                retries += 1
                time.sleep(0.5)
                success = False
        return success     


    def stop(self):
        self.abort()
        time.sleep(1)
        self.running = False
        

    def __pollTask(self):

        self.mutex.acquire()
        try:
            self.driver_status_flags = self.drive.getStatusFlags()
            self.success += 1

        except Exception as e:
            self.last_error = str(e)
            self.errors += 1


        try:
            self.driver_error_flags = self.drive.getErrorFlags()
            self.success += 1

        except Exception as e:
            self.last_error = str(e)
            self.errors += 1


        try:
            self.driver_voltage = self.drive.analogInput(8)/10
            self.success += 1

        except Exception as e:
            self.last_error = str(e)
            self.errors += 1
        
        try:
            self.driver_temperature = self.drive.analogInput(9)
            self.success += 1

        except Exception as e:
            self.last_error = str(e)
            self.errors += 1
        self.mutex.release()


    def __publishTask(self):
        current_status = self.getStatus()
        self.parent.parent.telegraf.metric(self.name, current_status)


    def run(self):
        while self.running:

            self.currentLoopTime = datetime.datetime.utcnow()
            self.loopdelta = self.currentLoopTime - self.prevLoopTime # calculate a timedelta between loops for looprate calculation
            self.prevLoopTime = self.currentLoopTime

            self.looptime = self.loopdelta.total_seconds()
            self.looprate = round(1.0 / self.looptime, 3)

            #===================
            self.mutex.acquire()
            #===================

            self.__getAxisStatus()

            az_target, el_target = self.parent.parent.object.getPosition()

            # fetch target position
            if self.type == AxisType.AZIMUTH:
                self.pos_target_degrees = az_target # in celestial reference frame
            else:
                self.pos_target_degrees = el_target # in celestial reference frame


            self.pos_error_degrees = self.pos_target_degrees - self.pos_celestial_degrees  # error = setpoint - sensor value
            if abs(self.pos_error_degrees) < self.config["f_target_threshold"]:
                self.on_target = True
            else:
                self.on_target = False

            # state register
            #--------------------------
            self.state = self.nextState
            #--------------------------

            # state dependent actions
            if self.state == AxisState.IDLE:
                pass

            elif self.state == AxisState.GOTO_POSITION:
                valid, positionReached = self.__positionReached()

                if valid and positionReached:
                    self.nextState = AxisState.IDLE
                else:
                    self.nextState = self.state


            elif self.state == AxisState.GOTO_VELOCITY:
                valid, isStopped = self.__isStopped()

                if valid and isStopped:
                    self.nextState = AxisState.IDLE
                else:
                    self.nextState = self.state


            elif self.state == AxisState.ABORT:
                valid, isStopped = self.__isStopped()

                if valid and isStopped:
                    self.nextState = AxisState.IDLE
                else:
                    self.nextState = self.state


            elif self.state == AxisState.TRACK:

                self.pid.SetPoint = self.pos_target_degrees
                self.pid.update(self.pos_celestial_degrees)
                if abs(self.pid.output) > 0:
                    self.__setVelocity(self.pid.output)

            elif self.state == AxisState.OOL:
                valid, isStopped = self.__isStopped()

                if valid and not isStopped:
                    self.__abort()
                else:
                    pass

            elif self.state == AxisState.PARK:
                valid, positionReached = self.__positionReached()

                if valid and positionReached:
                    self.nextState = AxisState.IDLE
                else:
                    self.nextState = self.state

            if (self.pos_mount_degrees < self.config["f_limit_min"] or self.pos_mount_degrees > self.config["f_limit_max"]):
                self.out_of_limits = True # purely for indicative purposes
                if not self.state == AxisState.PARK:
                    # do not throw us back into OOL when we are parking from the OOL state
                    # park mode is safe as regards the OOL because the home position (0,0) is hardcoded in the function
                    self.nextState = AxisState.OOL
            else:
                self.out_of_limits = False


            #===================
            self.mutex.release()
            #===================


            time.sleep(self.config["f_looprate"])


