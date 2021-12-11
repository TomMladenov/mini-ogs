#!/usr/bin/env python3

import enum
import logging
import os
import sys
import threading
from threading import Timer
from core.timer import CustomTimer
import time
import gpsd
import numpy as np



class GPSstate(enum.Enum):

    NO_MODE = 0
    TIME = 1
    FIX_2D = 2
    FIX_3D = 3


class GPS(threading.Thread):

    def __init__(self, parent, config, logging_level):
        super(GPS, self).__init__()

        logging.basicConfig(level=logging_level, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
        logging.Formatter.converter = time.gmtime

        self.parent = parent
        self.config = config
        self.name = self.config["name"]
        self.running = True

        
        self.mode = GPSstate.NO_MODE
        self.state = GPSstate(self.mode).name
        self.lat = 0.0
        self.lon = 0.0
        self.track = 0.0
        self.hspeed = 0.0
        self.time_utc = ""

        self.error_c = 0.0
        self.error_s = 0.0
        self.error_t = 0.0
        self.error_v = 0.0
        self.error_x = 0.0
        self.error_y = 0.0

        self.mgrs = ""
        self.grid = ""
        self.alt = 0.0
        self.climb = 0.0

        
        gpsd.connect(host=self.config["s_host"], port=self.config["i_port"])

        self.publish_timer = CustomTimer(self.config["f_publish_interval"], self.__publishTask).start()

    def getPosition(self):
        if self.mode != GPSstate.FIX_3D:
            return self.config["f_fallback_lat"], self.config["f_fallback_lon"], self.config["f_fallback_alt"]
        else:
            return self.lat, self.lon, self.alt

    def __publishTask(self):
        current_status = self.getStatus()
        self.parent.telegraf.metric(self.name, current_status)

    def getStatus(self):
        status = {
                    "mode" : self.mode,
                    "state" : self.state,
                    "sats_visible" : self.sats_visible,
                    "sats_used" : self.sats_used,
                    "lat" : self.lat,
                    "lon" : self.lon,
                    "track" : self.track,
                    "hspeed" : self.hspeed,
                    "time_utc" : self.time_utc,
                    "error_c" : self.error_c,
                    "error_s" : self.error_s,
                    "error_t" : self.error_t,
                    "error_v" : self.error_v,
                    "error_x" : self.error_x,
                    "error_y" : self.error_y,
                    "alt" : self.alt,
                    "climb" : self.climb
                }

    def _shutdown_thread(self):
        self.running = False


    def run(self):
        while self.running:
            self.packet = gpsd.get_current()
            self.mode = self.packet.mode
            self.sats_visible = self.packet.sats
            self.sats_used = self.packet.sats_valid

            if self.mode == GPSstate.NO_MODE:

                self.state = GPSstate(self.mode).name
                self.lat = 0.0
                self.lon = 0.0
                self.track = 0.0
                self.hspeed = 0.0
                self.time_utc = ""

                self.error_c = 0.0
                self.error_s = 0.0
                self.error_t = 0.0
                self.error_v = 0.0
                self.error_x = 0.0
                self.error_y = 0.0

                self.mgrs = ""
                self.grid = ""
                self.alt = 0.0
                self.climb = 0.0

            elif self.mode == GPSstate.TIME:

                self.state = GPSstate(self.mode).name
                self.lat = 0.0
                self.lon = 0.0
                self.track = 0.0
                self.hspeed = 0.0
                self.time_utc = str(self.packet.time)
                self.error_c = 0.0
                self.error_s = 0.0
                self.error_t = 0.0
                self.error_v = 0.0
                self.error_x = 0.0
                self.error_y = 0.0
                self.mgrs = ""
                self.grid = ""
                self.alt = 0.0
                self.climb = 	0.0

            elif self.mode == GPSstate.FIX_2D:

                self.state = GPSstate(self.mode).name
                self.lat = self.packet.lat
                self.lon = self.packet.lon
                self.track = self.packet.track
                self.hspeed = self.packet.track
                self.time_utc = str(self.packet.time)

                self.error_c = 0.0
                self.error_s = 0.0
                self.error_t = 0.0
                self.error_v = 0.0
                self.error_x = 0.0
                self.error_y = 0.0

                self.mgrs = self.m.toMGRS(self.packet.lat, self.packet.lon).decode('utf-8')
                self.grid = self.to_grid(self.packet.lat, self.packet.lon)
                self.alt = 0.0
                self.climb = 0.0

            elif self.mode == GPSstate.FIX_3D:

                self.state = GPSstate(self.mode).name
                self.lat = self.packet.lat
                self.lon = self.packet.lon
                self.track = self.packet.track
                self.hspeed = self.packet.track
                self.time_utc = str(self.packet.time)

                self.error_c = float(self.packet.error["c"])
                self.error_s = float(self.packet.error["s"])
                self.error_t = float(self.packet.error["t"])
                self.error_v = float(self.packet.error["v"])
                self.error_x = float(self.packet.error["x"])
                self.error_y = float(self.packet.error["y"])

                self.mgrs = self.m.toMGRS(self.packet.lat, self.packet.lon).decode('utf-8')
                self.grid = self.to_grid(self.packet.lat, self.packet.lon)
                self.alt = self.packet.alt
                self.climb = self.packet.climb

            time.sleep(1)
