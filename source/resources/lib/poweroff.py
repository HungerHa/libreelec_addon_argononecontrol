#!/usr/bin/python3
import sys

sys.path.append('/storage/.kodi/addons/service.argononecontrol/resources/lib')
from argonregister import *

# Initialize I2C Bus
bus = argonregister_initializebusobj()

# stop the fan and power off
argonregister_setfanspeed(bus, 0)
argonregister_signalpoweroff(bus)
