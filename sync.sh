#!/bin/bash

docker cp . $(docker ps -aqf "name=ogs-core"):/opt/mini-ogs