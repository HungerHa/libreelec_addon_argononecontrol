#!/usr/bin/python
import sys, os
if os.path.exists('/storage/.kodi/addons/virtual.system-tools/lib'):
	sys.path.append('/storage/.kodi/addons/virtual.system-tools/lib')
if os.path.exists('/storage/.kodi/addons/virtual.system-tools/lib.private'):
	sys.path.append('/storage/.kodi/addons/virtual.system-tools/lib.private')

import smbus
sys.path.append('/storage/.kodi/addons/virtual.rpi-tools/lib')
from gpiozero import pi_info

# I2C Addresses
ADDR_ARGONONEFAN=0x1a
ADDR_ARGONONEREG=ADDR_ARGONONEFAN

# ARGONONEREG Addresses
ADDR_ARGONONEREG_DUTYCYCLE=0x80
ADDR_ARGONONEREG_FW=0x81
ADDR_ARGONONEREG_IR=0x82
ADDR_ARGONONEREG_CTRL=0x86

pi = pi_info()
model = pi.model
if model == '3B' or model == '4B' or model == '5B':
	bus = smbus.SMBus(1)
else:
	bus = smbus.SMBus(0)
try:
	bus.write_byte_data(ADDR_ARGONONEREG,ADDR_ARGONONEREG_DUTYCYCLE,0) # fan off
	bus.write_byte_data(ADDR_ARGONONEREG,ADDR_ARGONONEREG_CTRL,1) # power off
except:
	model='Zero'
