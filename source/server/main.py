#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Tom Mladenov'

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from server import Server

import sys
import os
import uvicorn
import logging
import time
import inspect

tags_metadata = [
    {
        "name": "mount",
        "description": "Mount functions",
    },
    {
        "name": "imager",
        "description": "Imager functions",
    },
    {
        "name": "guider",
        "description": "Guider functions",
    }				
]

#Load server
server = Server()

#Load API
api = FastAPI(openapi_tags=tags_metadata)


@api.put("/server/ping")
def ping():
    return {"success": True, "response": "pong"}


@api.post("/server/mount/position/goto", tags=["mount"])
def goto_position(az: float, el: float, t: Optional[str] = None):
    desc = "{} args: az={}, el={}".format(inspect.getframeinfo(inspect.currentframe()).function, az, el)

    try:
        if t != None:
            job = server.scheduler.add_job(server.mount.gotoPosition, trigger='date', next_run_time=t, args=[az, el], name=desc)

        else:
            job = server.scheduler.add_job(server.mount.gotoPosition, args=[az, el], name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }

    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }


@api.post("/server/mount/position/set", tags=["mount"])
def set_position(az: float, el: float, t: Optional[str] = None):
    desc = "{} args: az={}, el={}".format(inspect.getframeinfo(inspect.currentframe()).function, az, el)

    try:
        if t != None:
            job = server.scheduler.add_job(server.mount.setPosition, trigger='date', next_run_time=t, args=[az, el], name=desc)

        else:
            job = server.scheduler.add_job(server.mount.setPosition, args=[az, el], name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }

    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }

@api.post("/server/mount/velocity", tags=["mount"])
def goto_velocity(az: float, el: float, t: Optional[str] = None):
    desc = "{} args: az={}, el={}".format(inspect.getframeinfo(inspect.currentframe()).function, az, el)

    try:
        if t != None:
            job = server.scheduler.add_job(server.mount.gotoVelocity, trigger='date', next_run_time=t, args=[az, el], name=desc)

        else:
            job = server.scheduler.add_job(server.mount.gotoVelocity, args=[az, el], name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": [az, el]						
                        }											
                }

    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }


@api.post("/server/mount/start_track", tags=["mount"])
def start_track(t: Optional[str] = None):
    desc = "Start tracking"

    try:
        if t != None:
            job = server.scheduler.add_job(server.mount.startTracking, trigger='date', next_run_time=t, name=desc)

        else:
            job = server.scheduler.add_job(server.mount.startTracking, name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__						
                        }											
                }

    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }

@api.post("/server/mount/pid", tags=["mount"])
def set_pid(P: float, I: float, D:float, t: Optional[str] = None):
    desc = "{} args: P={}, I={}, D={}".format(inspect.getframeinfo(inspect.currentframe()).function, P, I, D)

    try:
        if t != None:
            job = server.scheduler.add_job(server.mount.setPIDvalues, trigger='date', next_run_time=t, args=[P, I, D], name=desc)

        else:
            job = server.scheduler.add_job(server.mount.setPIDvalues, args=[P, I, D], name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": [P, I, D]					
                        }											
                }

    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }


@api.get("/server/mount/status", tags=["mount"])
def get_status():
    desc = "Get mount status"

    return server.mount.getStatus()


@api.put("/server/mount/emergency_stop", tags=["mount"])
def emergency_stop():
    desc = "Perform an emergency stop"

    try:
        job = server.scheduler.add_job(server.mount.emergencyStop, name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }
    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }


@api.put("/server/imager/stream/start", tags=["imager"])
def start_streaming(t: Optional[str] = None):
    desc = "Start imager streaming"

    try:
        if t != None:
            job = server.scheduler.add_job(server.imager.startStreaming, trigger='date', next_run_time=t, name=desc)

        else:
            job = server.scheduler.add_job(server.imager.startStreaming, name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }
    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }

@api.put("/server/imager/stream/stop", tags=["imager"])
def stop_streaming(t: Optional[str] = None):
    desc = "Stop imager streaming"

    try:
        if t != None:
            job = server.scheduler.add_job(server.imager.stopStreaming, trigger='date', next_run_time=t, name=desc)

        else:
            job = server.scheduler.add_job(server.imager.stopStreaming, name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }
    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }

@api.post("/server/imager/exposure", tags=["imager"])
def set_exposure(exposure : int, t: Optional[str] = None):
    desc = "Set imager exposure"

    try:
        if t != None:
            job = server.scheduler.add_job(server.imager.setExposure, trigger='date', next_run_time=t, args=[exposure], name=desc)

        else:
            job = server.scheduler.add_job(server.imager.setExposure, args=[exposure], name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }
    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }


@api.post("/server/imager/gain", tags=["imager"])
def set_gain(gain : int, t: Optional[str] = None):
    desc = "Set imager gain"

    try:
        if t != None:
            job = server.scheduler.add_job(server.imager.setGain, trigger='date', next_run_time=t, args=gain, name=desc)

        else:
            job = server.scheduler.add_job(server.imager.setGain, args=gain, name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.id 							
                        }											
                }
    except Exception as e:

        return 	{													
                    "success" : False, 								
                    "message": "Exception occurred: {}".format(e) 	
                }				


def custom_openapi():
    if api.openapi_schema:
        return api.openapi_schema
    openapi_schema = get_openapi(
        title="OGS API",
        version="0.1.0",
        description="Optical groundstation API",
        routes=api.routes,
    )
    api.openapi_schema = openapi_schema
    return api.openapi_schema


if __name__ == '__main__':


    from apscheduler.schedulers.background import BackgroundScheduler
    from apschedulerui.web import SchedulerUI
    ui = SchedulerUI(server.scheduler)
    ui.start()  # Server available at localhost:5000.


    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
    logging.Formatter.converter = time.gmtime

    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = '%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)'
    log_config["formatters"]["default"]["fmt"] = '%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)'

    api.openapi = custom_openapi

    uvicorn.run(api, host=server.host, port=server.port, log_config=log_config, headers=[('Server', server.s_header_description)])
    server.shutdown()
    sys.exit("Please wait until all systems are stopped...")
