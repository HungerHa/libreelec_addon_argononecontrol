#!/bin/bash
case "$1" in
  halt)
    #
    ;;
  poweroff)
    # workaround for remote control initiated shutdown (case MCU not available)
    i2c_check=$(/storage/.kodi/addons/virtual.system-tools/bin/i2cdetect -y 1 | grep 1a)
    if [ $? -eq 0 ]; then
      /usr/bin/python /storage/.kodi/addons/script.service.argonforty-device/resources/lib/poweroff.py
    fi
    ;;
  reboot)
    #
    ;;
  *)
    # your commands here
    ;;
esac
