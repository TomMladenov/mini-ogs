#!/usr/bin/env python3

import datetime
import enum
import logging
import math
import sys
import threading
import time

import PyTrinamic
from PyTrinamic.connections.ConnectionManager import ConnectionManager
from PyTrinamic.modules.TMCM1240.TMCM_1240 import TMCM_1240, _APs

import core.PID as PID


class AxisException(Exception):
	pass

class AxisState(enum.Enum):

	IDLE = 0
	GOTO_POSITION = 1
	GOTO_VELOCITY = 2
	ABORT = 3
	TRACK = 4

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
		self.name = AxisType(self.type).name
		self.config = config
		self.debug = debug

		self.errors = 0
		self.success = 0
		self.last_error = ""
		self.last_command = ""
		self.looptime = 0.0
		self.looprate = 0.0

		self.pos_internal_microsteps = 0
		self.pos_internal_degrees = 0.0

		self.pos_encoder_microsteps = 0
		self.pos_encoder_degrees = 0.0

		self.vel_internal_microsteps = 0
		self.vel_internal_degrees = 0.0

		self.driver_error_flags = 0
		self.driver_status_flags = 0

		self.driver_temperature = 0
		self.driver_voltage = 0.0

		self.pos_target_degrees = 25.0



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

		self.PID = PID.PID(P=25, I=35, D=0)
		self.PID.SetPoint=0.0
		self.PID.setSampleTime(0.01)
		self.PID.setWindup(7)

		self.running = True
		self.state = AxisState.IDLE
		self.nextState = AxisState.IDLE

		# eyJrIjoiTXBkMDluc0g0aWEwR29SUFo0ZUo5VUd4WHRRZzY0REIiLCJuIjoiYWRtaW5fa2V5IiwiaWQiOjF9 api key grafana with admyn role

		self.status = 	{
							"name" : self.name,
							"state" : AxisState(self.state).name,
							"errors" : self.errors,
							"success" : self.success,
							"last_error" : self.last_error,
							"last_command" : self.last_command,
							"looptime": self.looptime,
							"looprate" : self.looprate,

							"pos_internal_microsteps" : self.pos_internal_microsteps,
							"pos_internal_degrees" : self.pos_internal_degrees,

							"pos_encoder_microsteps" : self.pos_encoder_microsteps,
							"pos_encoder_degrees" : self.pos_encoder_degrees,

							"vel_internal_microsteps" : self.vel_internal_microsteps,
							"vel_internal_degrees" : self.vel_internal_degrees,

							"driver_error_flags" : self.driver_error_flags,
							"driver_status_flags" : self.driver_status_flags,

							"driver_temperature" : self.driver_temperature,
							"driver_voltage" : self.driver_voltage,

							"pos_target_degrees" : self.pos_target_degrees,
							"pos_error_degrees" : self.pos_target_degrees - self.pos_internal_degrees
						}

		logging.debug("{} Initialised axis ".format(self.name))

	def updateStatus(self):

		self.status["name"] = self.name
		self.status["state" ] = AxisState(self.state).name
		self.status["errors" ] = self.errors
		self.status["success" ] = self.success
		self.status["last_error" ] = self.last_error
		self.status["last_command" ] = self.last_command
		self.status["looptime"] = self.looptime
		self.status["looprate" ] = self.looprate

		self.status["pos_internal_microsteps" ] = self.pos_internal_microsteps
		self.status["pos_internal_degrees" ] = self.pos_internal_degrees

		self.status["pos_encoder_microsteps" ] = self.pos_encoder_microsteps
		self.status["pos_encoder_degrees" ] = self.pos_encoder_degrees

		self.status["vel_internal_microsteps" ] = self.vel_internal_microsteps
		self.status["vel_internal_degrees" ] = self.vel_internal_degrees

		self.status["driver_error_flags" ] = self.driver_error_flags
		self.status["driver_status_flags" ] = self.driver_status_flags

		self.status["driver_temperature" ] = self.driver_temperature
		self.status["driver_voltage" ] = self.driver_voltage

		self.status["pos_target_degrees"] = self.pos_target_degrees
		self.status["pos_error_degrees"] = self.pos_target_degrees - self.pos_internal_degrees

		self.parent.parent.telegraf.metric(self.name, self.status)
						

	def getStatus(self):
		return self.status


	def microstepsToDegrees(self, microsteps):
		d = microsteps * self.degreesPerUstep
		return d


	def degreesToMicrosteps(self, degrees):
		m = degrees / self.degreesPerUstep
		return round(m)


	def configureDrive(self, config):
		for key in config:
			if "axisparam" in key:
				parameter = int(key.split("_")[2])
				value = config[key]	
				status = self.__executeAxisCommand(True, AxisState.IDLE, self.drive.setAxisParameter, parameter, value)

	def setPIDvalues(self, P, I, D):
		self.PID.setKp(P)
		self.PID.setKi(I)
		self.PID.setKd(D)

	def setPosition(self, position_degrees):
		position_usteps = self.degreesToMicrosteps(position_degrees)
		condition = (self.state == self.nextState == AxisState.IDLE)
		self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setActualPosition, position_usteps)
		self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setTargetPosition, position_usteps)
		self.__executeAxisCommand(condition, AxisState.IDLE, self.drive.setAxisParameter, _APs.EncoderPosition, position_usteps)


	def gotoPosition(self, position_degrees):
		position_usteps = self.degreesToMicrosteps(position_degrees)
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
		


	def abortGoto(self):
		condition = (self.state == self.nextState == AxisState.GOTO_POSITION) or (self.state == self.nextState == AxisState.GOTO_VELOCITY)
		return self.__executeAxisCommand(condition, AxisState.ABORT, self.drive.stop)


	def emergencyStop(self):
		condition = (self.state == self.nextState == AxisState.IDLE) or \
					(self.state == self.nextState == AxisState.GOTO_POSITION) or \
					(self.state == self.nextState == AxisState.GOTO_VELOCITY) or \
					(self.state == self.nextState == AxisState.TRACK)
		return self.__executeAxisCommand(condition, AxisState.ABORT, self.drive.stop)


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
			self.pos_internal_microsteps = self.drive.getActualPosition()
			self.pos_internal_degrees = self.microstepsToDegrees(self.pos_internal_microsteps)
			self.success += 1

		except Exception as e:
			self.last_error = str(e)
			self.errors += 1


		try:
			self.pos_encoder_microsteps = self.drive.getAxisParameter(_APs.EncoderPosition)
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

		
		#logging.info("position={} usteps; state={}; looprate={} Hz; errors {}; ".format(self.position_microsteps, self.state, self.looprate, self.errors))
		logging.debug(str(self.status))


	def __getDriverStatus(self):

		try:
			self.driver_status_flags = self.drive.getStatusFlags()
			self.success += 1

		# error in telemetry readout is not critical
		except Exception as e:
			self.last_error = str(e)
			self.errors += 1


		try:
			self.driver_error_flags = self.drive.getErrorFlags()
			self.success += 1

		# error in telemetry readout is not critical
		except Exception as e:
			self.last_error = str(e)
			self.errors += 1


		try:
			self.driver_voltage = self.drive.analogInput(8)/10
			self.success += 1

		# error in telemetry readout is not critical
		except Exception as e:
			self.last_error = str(e)
			self.errors += 1
		
		try:
			self.driver_temperature = self.drive.analogInput(9)
			self.success += 1

		# error in telemetry readout is not critical
		except Exception as e:
			self.last_error = str(e)
			self.errors += 1
		

	def __PositionReached(self): 
		
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
		try:
			if abs(velocity_usteps) > self.config["i_axisparam_4"]:
				velocity_usteps = int(math.copysign(self.config["i_axisparam_4"], velocity_usteps))
			self.drive.rotate(velocity_usteps)

		except Exception as e:
			pass


	def stop(self):
		self.emergencyStop()
		time.sleep(1)
		self.running = False


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

			# state register
			#--------------------------
			self.state = self.nextState
			#--------------------------

			self.__getAxisStatus()

			#self.__getDriverStatus()



			if self.state == AxisState.IDLE:
				pass

			elif self.state == AxisState.GOTO_POSITION:
				valid, positionReached = self.__PositionReached()

				if valid and positionReached:
					self.nextState = AxisState.IDLE
				else:
					self.nextState = self.state

			elif self.state == AxisState.GOTO_VELOCITY or self.state == AxisState.ABORT:
				valid, isStopped = self.__isStopped()

				if valid and isStopped:
					self.nextState = AxisState.IDLE
				else:
					self.nextState = self.state

			elif self.state == AxisState.TRACK:
				if self.type == AxisType.ELEVATION:
					if self.pos_target_degrees > 0 and self.pos_target_degrees < 90:
						self.PID.SetPoint = self.pos_target_degrees
						self.PID.update(self.pos_internal_degrees)
						if abs(self.PID.output) > 0:
							self.__setVelocity(self.PID.output)
						else:
							pass
					else:
						pass


			#===================
			self.mutex.release()
			#===================

			# adapt looprates based on state
			if self.state == AxisState.TRACK:
				time.sleep(0.01)
			else:
				time.sleep(0.01)

			# execute a function that updates a dict from the internal variables, the dict is exposed to the outside as telemetry status
			self.updateStatus()
