#!/usr/bin/python3
import sys
import xml.etree.ElementTree as ET

sys.path.append('/storage/.kodi/addons/service.argononecontrol/resources/lib')
from argonregister import *

# Initialize I2C Bus
bus = argonregister_initializebusobj()

# Workaround for early MCU firmware versions
# Consider the current add-on settings
tree = ET.parse('/storage/.kodi/userdata/addon_data/service.argononecontrol/settings.xml')
root = tree.getroot()
for child in root.findall(".//setting[@id='cmdset_legacy']"):
    if child.text.lower() == 'true':
        usereg = False
    else:
        usereg = None

# Stop the fan and power off
argonregister_setfanspeed(bus, 0, usereg)
argonregister_signalpoweroff(bus, usereg)
