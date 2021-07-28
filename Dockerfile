FROM jermine/opencv:armhf-alpine

COPY requirements.txt /opt/mini-ogs/requirements.txt
COPY . /opt/mini-ogs

WORKDIR /opt/mini-ogs
RUN apk update && apk add python3-dev gcc libc-dev g++ libzmq musl-dev zeromq-dev
RUN pip install -r requirements.txt 