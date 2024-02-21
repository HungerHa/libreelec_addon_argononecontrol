# -*- coding: utf-8 -*-

#from resources.lib import kodiutils
#from resources.lib import kodilogging
#import logging
import time
import xbmc
import xbmcaddon

from threading import Thread
from threading import Event
from resources.lib import argon


def thread_powerbutton(event):
	argon.shutdown_check(event)


def thread_fan(event):
	argon.temp_check(event)


def run():
	ADDON = xbmcaddon.Addon()
	#logger = logging.getLogger(ADDON.getAddonInfo('id'))

	#monitor = xbmc.Monitor()
	monitor = argon.SettingMonitor()

	event = Event()
	t1 = Thread(target = thread_fan, args=(event,))
	t1.start()

	powerbutton = ADDON.getSettingBool('powerbutton')
	if powerbutton == True:
		t2 = Thread(target = thread_powerbutton, args=(event,))
		t2.start()

	while not monitor.abortRequested():
		# Sleep/wait for abort for 10 seconds
		if monitor.waitForAbort(1):
			# Abort was requested while waiting. We should exit
			break
		#logger.debug("ArgonForty Device addon! %s" % time.time())
	event.set()
	t1.join()
	if 't2' in locals():
		t2.join()
	argon.cleanup()
