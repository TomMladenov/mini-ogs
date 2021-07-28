#!/bin/bash

docker-compose down
docker container prune -f
docker ps -a