#!/usr/bin/env python3

import PyTrinamic
from PyTrinamic.connections.ConnectionManager import ConnectionManager
from PyTrinamic.modules.TMCM1240.TMCM_1240 import TMCM_1240
import time
import datetime
import sys
import threading
import enum
import logging
from core.axis import Axis, AxisState, AxisException, AxisType

class MountException(Exception):
	pass


class MountState(enum.Enum):

	IDLE=0
	GOTO_POSITION=1
	GOTO_VELOCITY=2
	GOTO_ABORT=3
	TRACK=4
	TRACK_ABORT=5


class Mount(object):

	def __init__(self, parent, config, az_config, el_config, logging_level):

		logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
		logging.Formatter.converter = time.gmtime

		self.parent = parent
		self.config = config
		self.running = True

		self.name = self.config["s_name"]


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
			self.azimuth = Axis(self, drive=self.drive0, type=AxisType.AZIMUTH, config = az_config, debug=True)

			logging.info("drive1 has serialAddress 2: linking /dev/ttyACM1 -> Elevation")
			self.elevation = Axis(self, drive=self.drive1,  type=AxisType.ELEVATION, config = el_config, debug=True)

		elif self.drive0_addr == 2 and self.drive1_addr == 1:
			logging.info("drive1 has serialAddress 1: linking /dev/ttyACM1 -> Azimuth")
			self.azimuth = Axis(self, drive=self.drive1,  type=AxisType.AZIMUTH, config = az_config, debug=True)

			logging.info("drive0 has serialAddress 2: linking /dev/ttyACM0 -> Elevation")
			self.elevation = Axis(self, drive=self.drive0, type=AxisType.ELEVATION, config = el_config, debug=True)

		else:
			logging.critical("Exception encountered during mount INIT")
			sys.exit(0)

		#Start axis threads
		self.azimuth.start()
		self.elevation.start()

	def gotoPosition(self, az, el):
		response_azimuth = self.azimuth.gotoPosition(az)
		response_elevation = self.elevation.gotoPosition(el)
		time.sleep(2)

		if response_azimuth["success"] and response_elevation["success"]:
			# wait until both axis are at IDLE again before releasing the job
			while self.azimuth.state != AxisState.IDLE or self.elevation.state != AxisState.IDLE:
				time.sleep(1)
		else:
			raise MountException("Encountered exception during axis commanding: response_azimuth {} response_elevation {}".format(response_azimuth, response_elevation))


	def gotoVelocity(self, vel_az, vel_el):
		self.azimuth.gotoVelocity(vel_az)
		self.elevation.gotoVelocity(vel_el)
		time.sleep(2)

	def setPosition(self, az, el):
		self.azimuth.setPosition(az)
		self.elevation.setPosition(el)
		time.sleep(2)

	def startTracking(self):
		if self.azimuth.state == AxisState.IDLE and self.elevation.state == AxisState.IDLE:
			self.azimuth.startTracking()
			self.elevation.startTracking()

	def setPIDvalues(self, p, i, d):
		self.azimuth.setPIDvalues(p, i, d)
		self.elevation.setPIDvalues(p, i, d)
		

	def emergencyStop(self):
		response_azimuth = self.azimuth.emergencyStop()
		response_elevation = self.elevation.emergencyStop()
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

