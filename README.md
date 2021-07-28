# mini-ogs
Repository for an advanced mini optical ground station


## preparation

Pull necessary images:
```
 docker pull grafana/grafana
 docker pull influxdb:1.8
 docker pull telegraf
 docker pull jermine/opencv:armhf-alpine
```

build custom image
```
 docker build .
``` 

## operations

Start the docker containers:
```
 docker compose up -d
```

Stop all containers:
```
 docker compose down -d
```