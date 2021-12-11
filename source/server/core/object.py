#!/usr/bin/env python3

import threading
import time
import datetime
import numpy as np
import logging
import ephem
from core.timer import CustomTimer
from core.axis import AxisType


class Object():

    def __init__(self, parent, config, logging_level):
        logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.config = config
        self.name = self.config["name"]

        self.object = None 
        self.azimuth = 0.0
        self.elevation = 0.0
        self.ra = 0.0
        self.dec = 0.0

        self.__reset()

        self.observer = ephem.Observer()
        self.publish_timer = CustomTimer(self.config["publish_interval"], self.__publishTask).start()

    
    def setTLE(self, name, l1, l2):
        self.object = ephem.readtle(name, l1, l2)
        self.__reset()

    def __reset(self):
        self.east_west_correction_active = False
        self.west_east_correction_active = False
        self.azimuth_previous = 180.0

    def setBody(self, name):
        try:
            object = getattr(ephem, name)
            self.object = object()
            self.__reset()
            return {"success": True, "message": ""}
        except Exception as e:
            self.object = None
            return {"success": False, "message": str(e)}

    def getBodies(self):
        return [name for _0, _1, name in ephem._libastro.builtin_planets()]

    def setStar(self, name):
        try:
            self.object = ephem.star(name)
            self.__reset()
            return {"success": True, "message": ""}
        except Exception as e:
            self.object = None
            return {"success": False, "message": str(e)}
        
    def getStars(self):
        return [star.split(",")[0] for star in ephem.stars.db.split("\n")]


    def getPosition(self, t=None):
        if self.object != None:
            if t != None:
                self.observer.date = t
            else:
                self.observer.date = datetime.datetime.utcnow()

            self.observer.lat = self.parent.mount.config["lat"] * ephem.degree
            self.observer.lon = self.parent.mount.config["lon"] * ephem.degree
            self.observer.elevation = self.parent.mount.config["alt"]

            self.object.compute(self.observer)

            # fetch object attributes
            azimuth = np.degrees(self.object.az) # not the final azimuth
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
        else:
            return 0.0, 0.0

    def getPositionAxis(self, axis):
        az, el = self.getPosition()
        if axis == AxisType.AZIMUTH:
            return az
        else:
            return el

    def objectLoaded(self):
        if self.object != None:
            return True
        else:
            return False


    def getStatus(self):
        return {
                    "name" : self.object.name if self.object != None else "",
                    "azimuth" : self.azimuth,
                    "elevation" : self.elevation,
                    "west_east_correction_active" : 1 if self.west_east_correction_active else 0,
                    "east_west_correction_active" : 1 if self.east_west_correction_active else 0,
                    "ra" : self.ra,
                    "dec" : self.dec
                }

    def __publishTask(self):
        self.getPosition()
        current_status = self.getStatus()
        self.parent.telegraf.metric(self.name, current_status)

    def stop(self):
        self.publish_timer.cancel()
