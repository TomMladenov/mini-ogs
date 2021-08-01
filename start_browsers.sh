#!/bin/bash

remote_host=192.168.0.240

chromium-browser http://$remote_host:8000/docs#/ http://$remote_host:5000/ http://$remote_host:5000 http://$remote_host:3000