#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Tom Mladenov'

import logging
import time
import toml

from apscheduler.schedulers.background import BackgroundScheduler

from core.camera import Camera, CameraType
from core.mount import Mount
from core.object import Object
from telegraf.client import TelegrafClient


class Server(object):

    def __init__(self, config_file, parent=None):
        super(Server, self).__init__()

        # load toml configuration file
        self.config = toml.load(config_file)

        # configure server attributes
        self.host = self.config["server"]["host"]
        self.port = self.config["server"]["port"]
        self.description = self.config["server"]["description"]

        self.scheduler = BackgroundScheduler({'apscheduler.timezone': 'UTC'})
        self.scheduler.start()

        self.telegraf = TelegrafClient(host=self.config["telegraf"]["host"], port=self.config["telegraf"]["port"])

        self.object = Object(self, config=self.config["object"], logging_level=logging.DEBUG)

        #self.guider = Camera(self, type=CameraType.GUIDER, config = dict(load_config(items=self.configurator.items("guider"))), logging_level=logging.DEBUG)
        #self.guider.start()

        #self.imager = Camera(self, type=CameraType.IMAGER, config = dict(load_config(items=self.configurator.items("imager"))), logging_level=logging.DEBUG)
        #self.imager.start()

        self.mount = Mount(self, config=self.config["mount"], logging_level=logging.DEBUG)

 
    def shutdown(self):
        self.guider.stop()
        #self.imager.stop()
        self.mount.stop()
        self.scheduler.stop()
        self.object.stop()
        time.sleep(2)
