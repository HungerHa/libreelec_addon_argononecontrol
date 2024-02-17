#!/usr/bin/python
import sys
sys.path.append('/storage/.kodi/addons/virtual.system-tools/lib.private')
import smbus
sys.path.append('/storage/.kodi/addons/virtual.rpi-tools/lib')
from gpiozero import pi_info

pi = pi_info()
model = pi.model
if model == '3B' or model == '4B' or model == '5B':
	bus = smbus.SMBus(1)
else:
	bus = smbus.SMBus(0)
try:
	bus.write_byte_data(0x1a,0x80,0)
	bus.write_byte(0x1a,0xFF)
except:
	model='Zero'
