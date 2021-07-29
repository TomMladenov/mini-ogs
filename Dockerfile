FROM navikey/raspbian-buster

COPY requirements.txt /opt/mini-ogs/requirements.txt
COPY . /opt/mini-ogs

WORKDIR /opt/mini-ogs
RUN apt-get update && apt-get -y install python3-dev gcc libc-dev g++ libzmq-dev musl-dev wget libusb-dev python3 python3-pip libatlas-base-dev libusb-1.0-0-dev python3-opencv
RUN pip3 install -r requirements.txt

WORKDIR /opt
RUN wget https://download.astronomy-imaging-camera.com/download/asi-camera-sdk-linux-mac/?wpdmdl=381 -O asi-sdk.tar.bz2
RUN tar -xvf asi-sdk.tar.bz2 && mkdir /opt/lib && cp ASI_linux_mac_SDK_V1.19.1/lib/armv7/* /opt/lib && rm asi-sdk.tar.bz2 && rm -rf ASI_linux_mac_SDK_V1.19.1

WORKDIR /opt/mini-ogs/source/server
CMD python3 main.py

