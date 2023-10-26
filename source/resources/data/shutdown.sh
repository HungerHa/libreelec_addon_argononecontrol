#!/bin/bash
case "$1" in
  halt)
    /usr/bin/python /storage/.kodi/addons/script.service.argonforty-device/resources/lib/poweroff.py
    ;;
  poweroff)
    /usr/bin/python /storage/.kodi/addons/script.service.argonforty-device/resources/lib/poweroff.py
    ;;
  reboot)
    #
    ;;
  *)
    # your commands here
    ;;
esac
