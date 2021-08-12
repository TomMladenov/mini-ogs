#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Tom Mladenov'

import datetime
import json
import logging
import os
import time
from configparser import ConfigParser
from threading import Thread

from apscheduler import events
from apscheduler.schedulers.background import BackgroundScheduler

from core.axis import Axis
from core.imager import Imager, ImagerType
from core.mount import Mount
from core.object import Object
from core.gps import GPS
from telegraf.client import TelegrafClient

def str2bool(v):
    return v.lower() in ("yes", "true", "t", "1")


def load_config(items):
    result = []
    for (key, value) in items:
        type_tag = key[:2]
        if type_tag == "s_":
            result.append((key, value))
        elif type_tag == "f_":
            result.append((key, float(value)))
        elif type_tag == "b_":
            result.append((key, str2bool(value)))
        elif type_tag == "i_":
            result.append((key, int(value)))
        elif type_tag == "l_":
            result.append((key, json.loads(value)))
        else:
            raise ValueError('Invalid type tag {T} found in ini file at key {K}, value {V}'.format(T=type_tag, K=key, V=value))

    return result


class Server(object):

    def __init__(self, parent=None):
        super(Server, self).__init__()

        self.configurator = ConfigParser(inline_comment_prefixes = (";",))
        self.configurator.read("/opt/config/config.ini")

        server_config = dict(load_config(items=self.configurator.items("server")))

        self.host = server_config["s_server_host"]
        self.port = server_config["i_server_port"]
        self.s_header_description = server_config["s_header_description"]

        self.scheduler = BackgroundScheduler({'apscheduler.timezone': 'UTC'})
        self.scheduler.start()

        self.telegraf = TelegrafClient(host='localhost', port=8092)

        self.object = Object(self, config = dict(load_config(items=self.configurator.items("object"))), logging_level=logging.DEBUG)
        self.object.start()

        self.gps = None
        self.guider = None
        self.imager = Imager(self, type=ImagerType.MAIN, config = dict(load_config(items=self.configurator.items("imager"))), logging_level=logging.DEBUG)
        self.imager.start()

        self.mount = Mount(	self,   config = dict(load_config(items=self.configurator.items("mount"))), 	\
                                    az_config = dict(load_config(items=self.configurator.items("azimuth"))), 	\
                                   el_config = dict(load_config(items=self.configurator.items("elevation"))),		\
                                    logging_level=logging.DEBUG)

 
    def shutdown(self):
        self.imager.stop()
        self.mount.stop()
        self.scheduler.stop()
        self.object.stop()
        time.sleep(2)
