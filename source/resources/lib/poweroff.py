#!/usr/bin/python3
import os
import sys
import xml.etree.ElementTree as ET

sys.path.append('/storage/.kodi/addons/service.argononecontrol/resources/lib')
from argonregister import *

# Initialize I2C Bus
bus = argonregister_initializebusobj()

# Workaround for early MCU firmware versions
# Consider the current add-on settings
use_register = None
settings_file = '/storage/.kodi/userdata/addon_data/service.argononecontrol/settings.xml'
if os.path.isfile(settings_file):
    tree = ET.parse(settings_file)
    root = tree.getroot()
    for child in root.findall(".//setting[@id='cmdset_legacy']"):
        if child.text.lower() == 'true':
            use_register = False
        else:
            use_register = None

# Stop the fan and power off
argonregister_setfanspeed(bus, 0, use_register)
argonregister_signalpoweroff(bus, use_register)
