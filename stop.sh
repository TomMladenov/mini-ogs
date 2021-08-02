#!/bin/bash

docker-compose down --remove-orphans
docker container prune -f 
docker ps -a