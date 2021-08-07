#!/usr/bin/env python3

from threading import Thread
import time
import datetime
import numpy as np
import logging
import ephem
from core.timer import CustomTimer


class Object(object):

	def __init__(self, parent, config, logging_level):

		logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
		logging.Formatter.converter = time.gmtime

		self.parent = parent
		self.config = config
		self.running = True

		self.name = self.config["s_name"]

        self.object = None 
        self.azimuth_previous = 180.0

        self.observer = ephem.Observer()

        self.publish_timer = CustomTimer(self.config["f_publish_interval"], self.__publishTask).start()

    
    def setObject(self, name, l1, l2):
        self.object = ephem.readtle(name, l1, l2)
        self.east_west_correction_active = False
        self.west_east_correction_active = False
        self.azimuth_previous = 180.0


    def getPosition(self, t=None):
        if t != None:
            self.observer.date = t
        else:
            self.observer.date = datetime.datetime.utcnow()

        lat, lon, elev = self.parent.gps.getPosition()
        self.observer.lon = lon
        self.observer.lat = lat
        self.observer.elevation = elev

        self.object.compute(self.observer)

        # fetch object attributes
        azimuth = np.degrees(self.object.az)
		self.elevation = np.degrees(self.object.alt)
        self.ra = np.degrees(self.object.ra)
        self.dec = np.degrees(self.object.dec)

        # determine azimuth correction
        if  self.azimuth_previous > 350.0 and azimuth < 5.0:
            self.west_east_correction_active = True
            self.east_west_correction_active = False
        elif self.azimuth_previous < 5.0 and azimuth > 350.0:
            self.west_east_correction_active = False
            self.east_west_correction_active = True

        # apply azimuth correction
        if self.west_east_correction_active:
            self.azimuth = azimuth + 360.0
        elif self.east_west_correction_active:
            self.azimuth = azimuth - 360.0
        else:
            self.azimuth = azimuth   

        self.azimuth_previous = self.azimuth

        return self.azimuth, self.elevation 



	def getStatus(self):
		return {
					"name" : self.azimuth.status,
					"l1" : self.elevation.status,
                    "l2" : self.sdfsdf,
                    "azimuth" : self.azimuth,
                    "elevation" : self.elevation,
                    "west_east_correction_active" : 1 if self.west_east_correction_active else 0,
                    "east_west_correction_active" : 1 if self.east_west_correction_active else 0,
                    "ra" : self.ra,
                    "dec" : self.dec
				}

    def __publishTask(self):
        current_status = self.getStatus()
        self.parent.telegraf.metric(self.name, current_status)

