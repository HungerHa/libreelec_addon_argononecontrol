# -*- coding: utf-8 -*-

from threading import Thread
from threading import Event

import xbmc
import xbmcaddon

from resources.lib import argon


def thread_powerbutton(abort_flag, power_button):
    argon.shutdown_check(abort_flag, power_button)


def thread_fan(abort_flag):
    argon.temp_check(abort_flag)


def run():
    ADDON = xbmcaddon.Addon()

    monitor = argon.SettingMonitor()

    abort_flag = Event()
    power_button = Event()
    t1 = Thread(target = thread_fan, args=(abort_flag,))
    t1.start()
    xbmc.log(msg='Argon ONE Control: fan control thread started', level=xbmc.LOGDEBUG)

    powerbutton = ADDON.getSettingBool('powerbutton')
    if powerbutton:
        power_button.set()
    t2 = Thread(target = thread_powerbutton, args=(abort_flag, power_button,))
    t2.start()
    xbmc.log(msg='Argon ONE Control: power button monitoring thread started', level=xbmc.LOGDEBUG)

    while not monitor.abortRequested():
        # Sleep/wait for abort for 1 seconds
        if monitor.waitForAbort(1):
            # Abort was requested while waiting. We should exit
            break
    abort_flag.set()
    power_button.set()
    t1.join()
    t2.join()
    abort_flag.clear()
    power_button.clear()
    xbmc.log(msg='Argon ONE Control: workerthreads stopped', level=xbmc.LOGDEBUG)
    argon.cleanup()
