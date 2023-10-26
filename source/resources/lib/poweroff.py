#!/usr/bin/python
import sys
sys.path.append('/storage/.kodi/addons/virtual.system-tools/lib')
import smbus
sys.path.append('/storage/.kodi/addons/virtual.rpi-tools/lib')
import RPi.GPIO as GPIO
rev = GPIO.RPI_REVISION
if rev == 2 or rev == 3:
	bus = smbus.SMBus(1)
else:
	bus = smbus.SMBus(0)
try:
	bus.write_byte(0x1a,0)
	bus.write_byte(0x1a,0xFF)
except:
	rev=0
