#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'Tom Mladenov'

from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

from apscheduler.schedulers.background import BackgroundScheduler
from apschedulerui.web import SchedulerUI

from server import Server

import sys
import os
import uvicorn
import logging
import time
import inspect

tags_metadata = [
    {
        "name": "general",
        "description": "General",
    },	    
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


@api.put("/server/ping", tags=["general"])
def ping():
    return {"success": True, "response": "pong"}


@api.get("/server/jobs", tags=["general"])
def get_jobs(jobid: Optional[str] = None):
    if jobid != None:
        job = server.scheduler.get_job(jobid)

        if job != None:
            return 	{													
                        "success" : True,								
                        "job":											
                            {											
                                "id": job.id, 							
                                "name": job.name, 						
                                "function": job.func.__name__, 			
                                "args": job.args,
                                "kwargs" : job.kwargs,
                                "next_run_time" : str(job.next_run_time)							
                            }											
                    }
        else:
            return {"success": False, "response": "No job found on the server with this ID!"} 
    else:
        jobs = server.scheduler.get_jobs()

        if jobs != []:
            return 	{													
                        "success" : True,								
                        "jobs":	[{"id" : job.id, "name" : job.name, "function" : job.func.__name__, "args" : job.args, "kwargs" : job.kwargs, "next_run_time" : str(job.next_run_time)} for job in jobs]										
                    }
        else:
            return {"success": False, "response": "No jobs found on the server!"}


@api.delete("/server/jobs", tags=["general"])
def remove_jobs():
    server.scheduler.remove_all_jobs()
    return {"success": True, "response": ""}

@api.post("/server/mount/park", tags=["mount"])
def park(t: Optional[str] = None):
    return add_server_job(function=server.mount.park, args=None, kwargs=None, t=t)

@api.post("/server/mount/position/goto", tags=["mount"])
def goto_position(az: float, el: float, t: Optional[str] = None):
    keyword_arguments = {"az" : az, "el" : el}
    return add_server_job(function=server.mount.gotoPosition, args=None, kwargs=keyword_arguments, t=t)
    

@api.post("/server/mount/position/set", tags=["mount"])
def set_position(az: float, el: float, t: Optional[str] = None):
    keyword_arguments = {"az" : az, "el" : el}
    return add_server_job(function=server.mount.setPosition, args=None, kwargs=keyword_arguments, t=t)


@api.post("/server/mount/velocity", tags=["mount"])
def goto_velocity(vel_az: float, vel_el: float, t: Optional[str] = None):
    keyword_arguments = {"vel_az" : vel_az, "vel_el" : vel_el}
    return add_server_job(function=server.mount.gotoVelocity, args=None, kwargs=keyword_arguments, t=t)


@api.post("/server/mount/start_track", tags=["mount"])
def start_track(t: Optional[str] = None):
    return add_server_job(function=server.mount.startTracking, args=None, kwargs=None, t=t)


@api.post("/server/mount/pid", tags=["mount"])
def set_pid(p: float, i: float, d:float, t: Optional[str] = None):
    keyword_arguments = {"p" : p, "i" : i, "d" : d}
    return add_server_job(function=server.mount.setPIDvalues, args=None, kwargs=keyword_arguments, t=t)


@api.get("/server/mount/status", tags=["mount"])
def get_status():
    desc = "Get mount status"
    return server.mount.getStatus()


@api.put("/server/mount/abort", tags=["mount"])
def abort():
    return add_server_job(function=server.mount.abort, args=None, kwargs=None, t=None)


@api.put("/server/imager/stream/start", tags=["imager"])
def start_streaming(t: Optional[str] = None):
    return add_server_job(function=server.imager.startStreaming, args=None, kwargs=None, t=t)


@api.put("/server/imager/stream/stop", tags=["imager"])
def stop_streaming(t: Optional[str] = None):
    return add_server_job(function=server.imager.stopStreaming, args=None, kwargs=None, t=t)


@api.post("/server/imager/exposure", tags=["imager"])
def set_exposure(exposure : int, t: Optional[str] = None):
    keyword_arguments = {"exposure" : exposure}
    return add_server_job(function=server.imager.setExposure, args=None, kwargs=keyword_arguments, t=t)


@api.post("/server/imager/gain", tags=["imager"])
def set_gain(gain : int, t: Optional[str] = None):
    keyword_arguments = {"gain" : gain}
    return add_server_job(function=server.imager.setGain, args=None, kwargs=keyword_arguments, t=t)


@api.post("/server/imager/flip", tags=["imager"])
def set_flip(flip : int, t: Optional[str] = None):
    keyword_arguments = {"flip" : flip}
    return add_server_job(function=server.imager.setFlip, args=None, kwargs=keyword_arguments, t=t)

@api.post("/server/object", tags=["object"])
def set_object(name : str, l1: str, l2: str, t: Optional[str] = None):
    keyword_arguments = {"name" : name, "l1" : l1, "l2" : l2}
    return add_server_job(function=server.object.setTLE, args=None, kwargs=keyword_arguments, t=t)

def add_server_job(function, args, kwargs, t):			

    try:
        desc = "{} {} {}".format(function.__name__, args, kwargs)

        if t != None:
            job = server.scheduler.add_job(function, trigger='date', next_run_time=t, args=args, kwargs=kwargs, name=desc)
        else:
            job = server.scheduler.add_job(function, trigger='date', args=args, kwargs=kwargs, name=desc)

        return 	{													
                    "success" : True,								
                    "job":											
                        {											
                            "id": job.id, 							
                            "name": job.name, 						
                            "function": job.func.__name__, 			
                            "args": job.args,
                            "kwargs" : job.kwargs,
                            "next_run_time" : job.next_run_time,
                            "executor" : job.executor					
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


    ui = SchedulerUI(server.scheduler)

    ui.start(port=5000, host='0.0.0.0', daemon=True)


    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)')
    logging.Formatter.converter = time.gmtime

    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = '%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)'
    log_config["formatters"]["default"]["fmt"] = '%(asctime)s %(levelname)-8s M:%(module)s T:%(threadName)-10s  Msg:%(message)s (L%(lineno)d)'

    api.openapi = custom_openapi

    # ------------------ blocking call -------------------
    uvicorn.run(api, host=server.host, port=server.port, log_config=log_config, headers=[('Server', server.s_header_description)])
    # ----------------------------------------------------
    
    server.shutdown()
    sys.exit("Please wait until all systems are stopped...")
