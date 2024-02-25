#!/usr/bin/python3
import sys
sys.path.append('/storage/.kodi/addons/script.service.argonforty-device/resources/lib')
from argonregister import *

# Initialize I2C Bus
bus = argonregister_initializebusobj()

# check if it's the new firmware with control registers support
argonregsupport = argonregister_checksupport(bus)

# stop the fan and power off
argonregister_setfanspeed(bus, 0, argonregsupport)
argonregister_signalpoweroff(bus, argonregsupport)
