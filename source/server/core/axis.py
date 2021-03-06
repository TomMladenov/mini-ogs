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
        self.name = self.config["name"]
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

        self.trajectory_setpoint_degrees = 0.0
        self.trajectory_error_degrees = 0.0
        self.offaxis_setpoint_degrees = 0.0
        self.offaxis_error_degrees = 0.0

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

        # position loop PID controller (inner)
        self.pid_position = PID(Kp=self.config["controller_parameters"]["kp_controller"], Ki=self.config["controller_parameters"]["ki_controller"], Kd=self.config["controller_parameters"]["kd_controller"])
        self.pid_position.setSampleTime(self.config["controller_parameters"]["looprate"])
        self.pid_position.setWindup(self.microstepsToDegrees(self.config["axis_parameters"]["4"]))

        # off-axis optical feedback PID controller (outer)
        self.pid_offaxis = PID(Kp=self.config["controller_parameters"]["kp_offaxis_controller"], Ki=self.config["controller_parameters"]["ki_offaxis_controller"], Kd=self.config["controller_parameters"]["kd_offaxis_controller"])
        self.pid_offaxis.setSampleTime(self.config["controller_parameters"]["looprate_offaxis_controller"])
        self.pid_offaxis.setWindup(self.config["controller_parameters"]["windup_offaxis_controller"])

        # init flags
        self.running = True
        self.out_of_limits = False
        self.trajectory_on_target = False
        self.offaxis_on_target = False

        # set default states
        self.state = AxisState.IDLE
        self.nextState = AxisState.IDLE

        # init task timers
        self.poll_timer = CustomTimer(self.config["poll_interval"], self.__pollTask).start()
        self.publish_timer = CustomTimer(self.config["publish_interval"], self.__publishTask).start()

        logging.debug("{} Initialised axis ".format(self.name))

    def getStatus(self):
        """Function to take a snapshot of the current class variables and put it in a Python dict.
        """

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

                        "trajectory_setpoint_degrees" : self.trajectory_setpoint_degrees,
                        "trajectory_error_degrees" : self.trajectory_error_degrees,

                        "offaxis_setpoint_degrees" : self.offaxis_setpoint_degrees,
                        "offaxis_error_degrees" : self.offaxis_error_degrees,

                        "out_of_limits" : 1 if self.out_of_limits else 0,
                        "correction_active" : 1 if self.parent.model_active else 0,

                        "P_trajectory" : self.pid_position.PTerm,
                        "I_trajectory" : self.pid_position.Ki * self.pid_position.ITerm,
                        "D_trajectory" : self.pid_position.Kd * self.pid_position.DTerm,
                        "trajectory_on_target" : 1 if self.trajectory_on_target else 0,
                        
                        "P_offaxis" : self.pid_offaxis.PTerm,
                        "I_offaxis" : self.pid_offaxis.Ki * self.pid_offaxis.ITerm,
                        "D_offaxis" : self.pid_offaxis.Kd * self.pid_offaxis.DTerm,
                        "offaxis_on_target" : 1 if self.offaxis_on_target else 0
                    }
        return status					


    def microstepsToDegrees(self, microsteps):
        d = microsteps * self.degreesPerUstep
        return d


    def degreesToMicrosteps(self, degrees):
        m = float(degrees) / self.degreesPerUstep
        return int(m)


    def configureDrive(self, config):
        for key, value in config["axis_parameters"].items():
            status = self.__executeAxisCommand(True, AxisState.IDLE, self.drive.setAxisParameter, int(key), value)

    def setPidPositionLoop(self, P, I, D):
        self.pid_position.setKp(P)
        self.pid_position.setKi(I)
        self.pid_position.setKd(D)

    def setPidOffAxisLoop(self, P, I, D):
        self.pid_offaxis.setKp(P)
        self.pid_offaxis.setKi(I)
        self.pid_offaxis.setKd(D)      

    def setPosition(self, position_degrees):
        position_usteps = self.degreesToMicrosteps(position_degrees)
        condition = (self.state == self.nextState == AxisState.IDLE)
        self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setActualPosition, position_usteps)
        self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setTargetPosition, position_usteps)
        if self.type == AxisType.AZIMUTH:
            self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setAxisParameter, _APs.EncoderPosition, -position_usteps)
        else:
            self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setAxisParameter, _APs.EncoderPosition, position_usteps)


    def gotoPosition(self, position_degrees_mount):
        """Command the axis 
        """
        position_usteps = self.degreesToMicrosteps(position_degrees_mount)
        condition = (self.state == self.nextState == AxisState.IDLE)
        return self.__executeAxisCommand(condition, AxisState.GOTO_POSITION, self.drive.moveTo, position_usteps)


    def gotoVelocity(self, velocity):
        speed_usteps = self.degreesToMicrosteps(velocity)
        if abs(speed_usteps) > self.config["axis_parameters"]["4"]:
            speed_usteps = int(math.copysign(self.config["axis_parameters"]["4"], speed_usteps))
            
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
                if (velocity_usteps < -self.config["axis_parameters"]["4"]):
                    velocity_usteps = -self.config["axis_parameters"]["4"]

                elif (velocity_usteps > self.config["axis_parameters"]["4"]):
                    velocity_usteps = self.config["axis_parameters"]["4"]

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

            # there are 2 setpoints in the cascaded controller
            self.trajectory_setpoint_degrees = self.parent.parent.object.getPositionAxis(self.type)
            self.offaxis_setpoint_degrees = self.parent.parent.guider.getOffAxisSetpoint(self.type)

            # there are 2 error signals as well
            self.trajectory_error_degrees = self.trajectory_setpoint_degrees + self.pid_offaxis.output - self.pos_celestial_degrees
            self.offaxis_error_degrees = self.offaxis_setpoint_degrees - self.parent.parent.guider.getOffAxisValue(self.type)

            if abs(self.trajectory_error_degrees) < self.config["target_threshold_trajectory"]:
                self.trajectory_on_target = True
            else:
                self.trajectory_on_target = False

            if abs(self.offaxis_error_degrees) < self.config["target_threshold_offaxis"]:
                self.offaxis_on_target = True
            else:
                self.offaxis_on_target = False

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
                    self.pid_position.clear()
                    self.pid_offaxis.clear()
                else:
                    self.nextState = self.state


            elif self.state == AxisState.TRACK:
                
                # set the desired off axis setpoing
                self.pid_offaxis.SetPoint = self.parent.parent.guider.getOffAxisSetpoint(self.type) # adjust this later to a flexible off-axis value
                
                # update the offaxis controller with the observed offset by the guider in that axis
                self.pid_offaxis.update(self.parent.parent.guider.getOffAxisValue(self.type))

                if self.parent.parent.guider.object_detection_enabled and self.parent.parent.guider.keypoints != []:
                # update the position loop with the calculated trajectory + output of offaxis controller
                    self.pid_position.SetPoint = self.trajectory_setpoint_degrees - self.pid_offaxis.output
                else:
                    self.pid_position.SetPoint = self.trajectory_setpoint_degrees

                # update the position loop with the current mount coordinates (albeit pushed through the pointing model)
                self.pid_position.update(self.pos_celestial_degrees)

                if abs(self.pid_position.output) > 0:
                    self.__setVelocity(self.pid_position.output)

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

            if (self.pos_mount_degrees < self.config["limit_min"] or self.pos_mount_degrees > self.config["limit_max"]):
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


            time.sleep(self.config["controller_parameters"]["looprate"])


