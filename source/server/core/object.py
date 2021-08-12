#!/usr/bin/env python3

import threading
import time
import datetime
import numpy as np
import logging
import ephem
from core.timer import CustomTimer


class Object(threading.Thread):

    def __init__(self, parent, config, logging_level):
        super(Object, self).__init__()
        logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.config = config
        self.running = True

        self.name = self.config["s_name"]

        self.object = None 
        self.azimuth_previous = 180.0

        self.azimuth = 0.0
        self.elevation = 0.0
        self.ra = 0.0
        self.dec = 0.0
        self.east_west_correction_active = False
        self.west_east_correction_active = False

        self.observer = ephem.Observer()
        self.publish_timer = CustomTimer(self.config["f_publish_interval"], self.__publishTask).start()

    
    def setTLE(self, name, l1, l2):
        self.object = ephem.readtle(name, l1, l2)
        self.east_west_correction_active = False
        self.west_east_correction_active = False
        self.azimuth_previous = 180.0


    def getPosition(self, t=None):
        if t != None:
            self.observer.date = t
        else:
            self.observer.date = datetime.datetime.utcnow()

        #lat, lon, elev = self.parent.gps.getPosition()
        #self.observer.lon = lon
        #self.observer.lat = lat
        #self.observer.elevation = elev

        self.observer.lon = 5.0 * ephem.degree
        self.observer.lat = 50.0 * ephem.degree
        self.observer.elevation = 30.0

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



    def getStatus(self):
        return {
                    "name" : self.object.catalog_number if self.object != None else "",
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

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            while self.object != None:
                self.getPosition()
                time.sleep(0.015)
            time.sleep(1)

