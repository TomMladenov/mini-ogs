#!/usr/bin/env python3

import PyTrinamic
from PyTrinamic.connections.ConnectionManager import ConnectionManager
from PyTrinamic.modules.TMCM1240.TMCM_1240 import TMCM_1240
import time
import datetime
import sys


cm0 = ConnectionManager(["--interface=serial_tmcl","--port=/dev/ttyUSB0", "--data-rate=1000000"], debug=True)

interface0 = cm0.connect()

motor0 = TMCM_1240(connection=interface0, moduleID=1)
motor1 = TMCM_1240(connection=interface0, moduleID=2)

t0 = datetime.datetime.utcnow()
motor0_addr = motor0.getGlobalParameter(motor0.GPs.serialAddress, bank=0)
t1 = datetime.datetime.utcnow()

print("Request took {} seconds".format(t1.timestamp() - t0.timestamp()))


motor1_addr = motor1.getGlobalParameter(motor1.GPs.serialAddress, bank=0)

if motor0_addr == 1:
	print("interface0 has serialAddress 1: /dev/ttyACM0->AZ /dev/ttyACM1->EL")
	azimuth = motor0
	elevation = motor1
elif motor0_addr == 2:
	print("interface0 has serialAddress 2: /dev/ttyACM0->EL /dev/ttyACM1->AZ")
	azimuth = motor1
	elevation = motor0
else:
	print("Error during motor INIT, exiting...")
	sys.exit(0)

'''

print("issuing request to motors in 1s...")
time.sleep(1)
response = azimuth.stop()
response = elevation.stop()
print("Request done")

interface0.printInfo()
interface0.enableDebug(True)
#to = interface0.get_timeout()
#print(to)


response = azimuth.moveTo(150000, 100000)
print(response)

time.sleep(30)
'''


'''

time.sleep(5)

azimuth.setActualPosition(0)
elevation.setActualPosition(0)

print("Rotating  AZ to 150000")
azimuth.moveTo(150000, 100000)
azimuth.getAxisParameter(azimuth.APs.ActualPosition)
while not(azimuth.positionReached()):
	print("{T} Position not yet reached".format(T=datetime.datetime.utcnow()))
	time.sleep(1)
	pass

time.sleep(5);

print("Stopping AZ")
azimuth.stop()


print("Rotating  EL to 150000")
elevation.moveTo(150000, 100000)
elevation.getAxisParameter(elevation.APs.ActualPosition)
while not(elevation.positionReached()):
	print("{T} Position not yet reached".format(T=datetime.datetime.utcnow()))
	time.sleep(1)
	pass

time.sleep(5);

print("Stopping EL")
elevation.stop()
'''

interface0.close()
interface1.close()


'''
time.sleep(5)

azimuth.setActualPosition(0)
elevation.setActualPosition(0)

print("Preparing parameters")
azimuth.setMaxAcceleration(15000)
elevation.setMaxAcceleration(15000)

print("Rotating  AZ to 150000")
azimuth.moveTo(150000, 100000)
print("past")
azimuth.getAxisParameter(azimuth.APs.ActualPosition)
while not(azimuth.positionReached()):
	print("{T} Position not yet reached".format(T=datetime.datetime.utcnow()))
	pass

time.sleep(5);

print("Stopping AZ")
azimuth.stop()


print("Rotating  EL to 40000")
elevation.rotate(40000)
time.sleep(5);

print("Stopping EL")
elevation.stop()
'''



'''
print("ActualPostion")
print(Module_1240.getActualPosition())
time.sleep(5);

print("Doubling moved distance")
Module_1240.moveBy(Module_1240.getActualPosition(), 150000)
Module_1240.getAxisParameter(Module_1240.APs.ActualPosition)
while not(Module_1240.positionReached()):
	pass

print("Furthest point reached")
print(Module_1240.getActualPosition())

time.sleep(5)

print("Moving back to 0")
Module_1240.moveTo(0, 100000)

# Wait until position 0 is reached
while not(Module_1240.positionReached()):
	print("{T} Position not yet reached".format(T=datetime.datetime.utcnow()))
	pass

print("Reached Position 0")
'''


'''
response = Module_1240.getAxisParameter(Module_1240.APs.FullstepResolution)
print(response)


Module_1240.moveTo(0, 30000)

while not(Module_1240.positionReached()):
	pass

print("Reached Position")
print(Module_1240.getActualPosition())

myInterface.close()
'''
