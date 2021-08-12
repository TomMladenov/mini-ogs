# mini-ogs
Repository for an advanced mini optical ground station


## Preparation

Pull necessary images:
```
 docker pull grafana/grafana:8.0.3
 docker pull telegraf:1.19.1
 docker pull forcedinductionz/docker-gpsd
```

build custom image(s)
```
 docker build . -t ogs-core --file Dockerfile_ogs-core
 docker build . -t telegraf-python:1.19.1 --file Dockerfile_telegraf
 docker build . -t gpsfake --file Dockerfile_gpsfake
``` 

## Development

To run ogs-core standalone:
```
docker run -it --network host --privileged --name ogs-core ogs-core sh
docker run -it --network host --privileged --name ogs-core -v /home/user/git/mini-ogs/source:/opt/source -v /home/user/git/mini-ogs/config/ogs-core/config.ini:/opt/config/config.ini ogs-core python3 main.py

```

Sync local code to the running container with:
```
./sync.sh
```

To run telegraf standalone for dev purposes:
```
docker run --network host --privileged -v /home/user/git/mini-ogs/config/telegraf/:/etc/telegraf/ telegraf
```


## Operations

Start the docker containers using the wrapper script:
```
 ./start.sh
```

Stop and remove all containers using the wrapper script:
```
 ./stop.sh
```


