# mini-ogs
Repository for an advanced mini optical ground station


## Preparation

Pull necessary images:
```
 docker pull grafana/grafana
 docker pull influxdb:1.8
 docker pull telegraf
 docker pull jermine/opencv:armhf-alpine
```

build custom image
```
 docker build . -t ogs-core
``` 

## Development

To run ogs-core standalone:
```
docker run -it --network host --privileged --name ogs-core ogs-core sh
```

Sync local code to the running container with:
```
./sync.sh
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


