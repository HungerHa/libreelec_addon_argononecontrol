#!/usr/bin/python3
#
# This script set fan speed and monitor power button events.
#
# Fan Speed is set by sending 0 to 100 to the MCU (Micro Controller Unit)
# The values will be interpreted as the percentage of fan speed, 100% being maximum
#
# Power button events are sent as a pulse signal to BCM Pin 4 (BOARD P7)
# A pulse width of 20-30ms indicates reboot request (double-tap)
# A pulse width of 40-50ms indicates shutdown request (hold and release after 3 secs)
#
# Additional comments are found in each function below
#
# Standard Deployment/Triggers:
#  * Raspbian, OSMC: Runs as service via /lib/systemd/system/argononed.service
#  * lakka, libreelec: Runs as service via /storage/.config/system.d/argononed.service
#  * recalbox: Runs as service via /etc/init.d/
#

import importlib.util
import os
import sys
from shutil import copyfile
from threading import Event
import time
import zlib

# For LibreELEC/Lakka, note that we need to add system paths
sys.path.append('/storage/.kodi/addons/virtual.rpi-tools/lib')
# workaround for lgpio issue
# https://github.com/gpiozero/gpiozero/issues/1106
os.environ['LG_WD'] = '/tmp'
lgpio_spec = importlib.util.find_spec('lgpio')
if lgpio_spec is not None:
    import lgpio
else:
    from gpiozero import Button

import xbmc
import xbmcaddon

from resources.lib.argonregister import *
from resources.lib.argonsysinfo import *

SHUTDOWN_PIN = 4

# Initialize I2C Bus
bus = argonregister_initializebusobj()
fansettingupdate = False
power_btn_triggered = False
power_button_mon = Event()
powerbutton_remap = False

class SettingMonitor(xbmc.Monitor):
    """Detect Settings Change"""
    def onSettingsChanged(self):
        global fansettingupdate
        fansettingupdate = True


def thread_sleep(sleep_sec, abort_flag):
    """quick interruptible sleep"""
    global fansettingupdate
    for i in range(sleep_sec):
        if abort_flag.is_set() or fansettingupdate:
            break
        time.sleep(1)


def power_btn_pressed(chip=None, gpio=None, level=None, timestamp=None):
    global power_btn_triggered
    power_btn_triggered = True
    if timestamp is not None:
        xbmc.log(msg='Argon40: power button pressed event -> {}, {}, {}, {}'.format(chip, gpio, level, timestamp), level=xbmc.LOGDEBUG)


def shutdown_check(abort_flag, power_button):
    """
    This function is the thread that monitors activity in our shutdown pin.
    The pulse width is measured, and the corresponding shell command will be issued.
    """
    global lgpio_spec
    global power_button_mon
    power_button_mon = power_button
    power_button_mon.wait()
    if abort_flag.is_set():
        xbmc.log(msg='Argon40: power button monitoring was not running', level=xbmc.LOGDEBUG)
        return

    global power_btn_triggered
    power_btn_triggered = False
    if lgpio_spec is not None:
        xbmc.log(msg='Argon40: power button monitoring via lgpio', level=xbmc.LOGDEBUG)
        #Initialize GPIO
        # open the gpio chip and set the pin 4 as input (pull down)
        lgpio.exceptions = False
        h = lgpio.gpiochip_open(4)
        if h >= 0:
            # Pi5 mapping
            chip = 4
        else:
            # Old mapping
            chip = 0
            h = lgpio.gpiochip_open(0)
        lgpio.exceptions = True
        #lgpio.gpio_claim_input(h, SHUTDOWN_PIN, lFlags=lgpio.SET_PULL_DOWN)
        err = lgpio.gpio_claim_alert(h, SHUTDOWN_PIN, eFlags=lgpio.RISING_EDGE, lFlags=lgpio.SET_PULL_DOWN)
        if err < 0:
            xbmc.log(msg="GPIO in use {}:{} ({})".format(chip, SHUTDOWN_PIN, lgpio.error_text(err)), level=xbmc.LOGDEBUG)
        cb_power_btn = lgpio.callback(h, SHUTDOWN_PIN, edge=lgpio.RISING_EDGE, func=power_btn_pressed)
    else:
        xbmc.log(msg='Argon40: power button monitoring via gpiozero', level=xbmc.LOGDEBUG)
        # pull down the pin
        btn = Button(SHUTDOWN_PIN, pull_up=False)
        btn.when_pressed = power_btn_pressed

    while True:
        if not power_button_mon.is_set():
            xbmc.log(msg='Argon40: power button monitoring has been disabled', level=xbmc.LOGDEBUG)
        power_button_mon.wait()
        if abort_flag.is_set():
            break
        pulsetime = 1
        time.sleep(0.001)
        if power_btn_triggered:
            power_btn_triggered = False
            xbmc.log(msg='Argon40: power button was pressed', level=xbmc.LOGDEBUG)
            time.sleep(0.01)
            # wait until the button is released
            if lgpio_spec is not None:
                # lgpio in use
                while lgpio.gpio_read(h, SHUTDOWN_PIN) == 1:
                    time.sleep(0.01)
                    pulsetime += 1
                    if abort_flag.is_set() or not power_button_mon.is_set():
                        xbmc.log(msg='Argon40: button monitoring loop 2 aborted', level=xbmc.LOGDEBUG)
                        break
            else:
                # gpiozero in use
                while btn.is_pressed:
                    time.sleep(0.01)
                    pulsetime += 1
                    if abort_flag.is_set() or not power_button_mon.is_set():
                        xbmc.log(msg='Argon40: button monitoring loop 2 aborted', level=xbmc.LOGDEBUG)
                        break

            xbmc.log(msg='Argon40: power button was released', level=xbmc.LOGDEBUG)
            if pulsetime >= 2 and pulsetime <= 3:
                if powerbutton_remap:
                    xbmc.shutdown()
                else:
                    xbmc.restart()
            elif pulsetime >= 4 and pulsetime <= 5:
                xbmc.shutdown()
        if abort_flag.is_set():
            xbmc.log(msg='Argon40: button monitoring loop 1 aborted', level=xbmc.LOGDEBUG)
            break
    # freeing the GPIO resources
    if lgpio_spec is not None:
        # lgpio in use
        cb_power_btn.cancel()
        cb_power_btn = None
        free_pin = lgpio.gpio_free(h, SHUTDOWN_PIN)
        if free_pin == 0:
            xbmc.log(msg='Argon40: power button GPIO pin freed', level=xbmc.LOGDEBUG)
        close_chip = lgpio.gpiochip_close(h)
        if close_chip < 0:
            xbmc.log(msg='Argon40: GPIO chip could not be closed', level=xbmc.LOGDEBUG)
    else:
        # gpiozero in use
        btn.close()
        if btn.closed:
            xbmc.log(msg='Argon40: power button pin freed', level=xbmc.LOGDEBUG)
    xbmc.log(msg='Argon40: power button monitoring stopped', level=xbmc.LOGDEBUG)


def get_fanspeed(tempval, configlist):
    """
    This function converts the corresponding fanspeed for the given temperature
    The configuration data is a list of strings in the form "<temperature>=<speed>"
    """
    for curconfig in configlist:
        curpair = curconfig.split('=')
        tempcfg = float(curpair[0])
        fancfg = int(float(curpair[1]))
        if tempval >= tempcfg:
            if fancfg < 1:
                return 0
            elif fancfg < 10:
                return 10
            return fancfg
    return 0


def load_config():
    """
    This function retrieves the fanspeed configuration list from a file, arranged by temperature.
    It ignores lines beginning with "#" and checks if the line is a valid temperature-speed pair.
    The temperature values are formatted to uniform length, so the lines can be sorted properly.
    """
    ADDON = xbmcaddon.Addon()

    global power_button_mon
    global powerbutton_remap
    powerbutton = ADDON.getSettingBool('powerbutton')
    powerbutton_remap = ADDON.getSettingBool('powerbutton_remap')
    if powerbutton:
        if not power_button_mon.is_set():
            xbmc.log(msg='Argon40: power button monitoring has been enabled', level=xbmc.LOGDEBUG)
        power_button_mon.set()
    else:
        power_button_mon.clear()

    newconfig = []
    newhddconfig = []
    newgpuconfig = []
    newpmicconfig = []

    fanspeed_disable = ADDON.getSettingBool('fanspeed_disable')
    if fanspeed_disable:
        return [['90=100'], newgpuconfig, newhddconfig, newpmicconfig]
    fanspeed_alwayson = ADDON.getSettingBool('fanspeed_alwayson')
    if fanspeed_alwayson:
        return [['1=100'], newgpuconfig, newhddconfig, newpmicconfig]
    fanspeed_gpu = ADDON.getSettingBool('fanspeed_gpu')
    fanspeed_hdd = ADDON.getSettingBool('fanspeed_hdd')
    fanspeed_pmic = ADDON.getSettingBool('fanspeed_pmic')
    temperature_unit = xbmc.getInfoLabel('System.TemperatureUnits')

    configtype = ['a', 'b', 'c']
    for typekey in configtype:
        if temperature_unit == '°F':
            tempval = (float(ADDON.getSetting('cputempf_'+typekey))-32.0) * 5.0/9.0
            gputempval = (float(ADDON.getSetting('gputempf_'+typekey))-32.0) * 5.0/9.0
            hddtempval = (float(ADDON.getSetting('hddtempf_'+typekey))-32.0) * 5.0/9.0
            pmictempval = (float(ADDON.getSetting('pmictempf_'+typekey))-32.0) * 5.0/9.0
        else:
            tempval = float(ADDON.getSetting('cputemp_'+typekey))
            gputempval = float(ADDON.getSetting('gputemp_'+typekey))
            hddtempval = float(ADDON.getSetting('hddtemp_'+typekey))
            pmictempval = float(ADDON.getSetting('pmictemp_'+typekey))
        fanval = int(ADDON.getSetting('fanspeed_'+typekey))
        gpufanval = int(ADDON.getSetting('fanspeed_gpu_'+typekey))
        hddfanval = int(ADDON.getSetting('fanspeed_hdd_'+typekey))
        pmicfanval = int(ADDON.getSetting('fanspeed_pmic_'+typekey))

        newconfig.append( "{:5.1f}={}".format(tempval,fanval))
        if fanspeed_gpu:
            newgpuconfig.append( "{:5.1f}={}".format(gputempval,gpufanval))
        if fanspeed_hdd:
            newhddconfig.append( "{:5.1f}={}".format(hddtempval,hddfanval))
        if fanspeed_pmic:
            newpmicconfig.append( "{:5.1f}={}".format(pmictempval,pmicfanval))

    if len(newconfig) > 0:
        newconfig.sort(reverse=True)
    if len(newgpuconfig) > 0:
        newgpuconfig.sort(reverse=True)
    if len(newhddconfig) > 0:
        newhddconfig.sort(reverse=True)
    if len(newpmicconfig) > 0:
        newpmicconfig.sort(reverse=True)

    return [ newconfig, newgpuconfig, newhddconfig, newpmicconfig ]


def temp_check(abort_flag):
    """
    This function is the thread that monitors temperature and sets the fan speed.
    The value is fed to get_fanspeed to get the new fan speed.
    To prevent unnecessary fluctuations, lowering fan speed is delayed by 30 seconds.

    Location of config file varies based on OS
    """
    global fansettingupdate

    argonregsupport = argonregister_checksupport(bus)

    fanconfig = ['65=100', '60=55', '55=10']
    fanhddconfig = ['50=100', '40=55', '30=30']

    prevspeed=0

    while True:
        tmpconfig = load_config()
        # CPU fan settings
        if len(tmpconfig[0]) > 0:
            fanconfig = tmpconfig[0]
        # GPU fan settings
        if len(tmpconfig[1]) > 0:
            fangpuconfig = tmpconfig[1]
        else:
            fangpuconfig = []
        # HDD fan settings
        if len(tmpconfig[2]) > 0:
            fanhddconfig = tmpconfig[2]
        else:
            fanhddconfig = []
        # PMIC fan settings
        if len(tmpconfig[3]) > 0:
            fanpmicconfig = tmpconfig[3]
        else:
            fanpmicconfig = []

        fansettingupdate = False
        while not fansettingupdate:
            # Speed based on CPU Temp
            val = argonsysinfo_getcputemp()
            xbmc.log(msg='Argon40: current CPU temperature : ' + str(val), level=xbmc.LOGDEBUG)
            newspeed = get_fanspeed(val, fanconfig)
            # Speed based on GPU Temp
            val = argonsysinfo_getgputemp()
            xbmc.log(msg='Argon40: current GPU temperature : ' + str(val), level=xbmc.LOGDEBUG)
            gpuspeed = get_fanspeed(val, fangpuconfig)
            # Speed based on SSD/NVMe Temp
            val = argonsysinfo_getmaxhddtemp()
            xbmc.log(msg='Argon40: current SSD/NVMe temperature : ' + str(val), level=xbmc.LOGDEBUG)
            hddspeed = get_fanspeed(val, fanhddconfig)
            # Speed based on PMIC Temp
            val = argonsysinfo_getpmictemp()
            xbmc.log(msg='Argon40: current PMIC temperature : ' + str(val), level=xbmc.LOGDEBUG)
            pmicspeed = get_fanspeed(val, fanpmicconfig)
            xbmc.log(msg='Argon40: CPU fan speed value : ' + str(newspeed), level=xbmc.LOGDEBUG)
            xbmc.log(msg='Argon40: GPU fan speed value : ' + str(gpuspeed), level=xbmc.LOGDEBUG)
            xbmc.log(msg='Argon40: SSD/NVMe fan speed value : ' + str(hddspeed), level=xbmc.LOGDEBUG)
            xbmc.log(msg='Argon40: PMIC fan speed value : ' + str(pmicspeed), level=xbmc.LOGDEBUG)

            # Use faster fan speed
            if gpuspeed > newspeed:
                newspeed = gpuspeed
            if hddspeed > newspeed:
                newspeed = hddspeed
            if pmicspeed > newspeed:
                newspeed = pmicspeed

            if newspeed < prevspeed:
                thread_sleep(30, abort_flag)
            prevspeed = newspeed
            try:
                argonregister_setfanspeed(bus, newspeed, argonregsupport)
                thread_sleep(30, abort_flag)
            except IOError:
                temp = ''
                thread_sleep(60, abort_flag)
            if abort_flag.is_set():
                break
        if abort_flag.is_set():
            break


def checksetup():
    """Used to enabled i2c and UART"""
    configfile = '/flash/config.txt'

    # Add argon remote control
    lockfile = '/storage/.config/argon40_rc.lock'
    if not os.path.exists(lockfile):
        copykeymapfile()
        mergercmapsfile()
        removelircfile()

    # Check if i2c exists
    isenabled = False
    with open(configfile, 'r') as fp:
        for curline in fp:
            if not curline:
                continue
            tmpline = curline.strip()
            if not tmpline:
                continue
            if tmpline == 'dtparam=i2c=on':
                isenabled = True
                break
    if isenabled:
        return()

    os.system("mount -o remount,rw /flash")
    with open(configfile, 'a') as fp:
        fp.write('dtparam=i2c=on\n')
        fp.write('enable_uart=1\n')
        fp.write('dtoverlay=gpio-ir,gpio_pin=23\n')
    os.system('mount -o remount,ro /flash')


def copykeymapfile():
    """Copy RC keytable file to rc_keymaps directory"""
    srcfile = '/storage/.kodi/addons/script.service.argonforty-device/resources/data/argon40.toml'
    dstfile = '/storage/.config/rc_keymaps/argon40.toml'
    if os.path.isfile(dstfile):
        tmpdsthash = getFileHash(dstfile)
        tmpsrchash = getFileHash(srcfile)
        if tmpdsthash == tmpsrchash:
            return()
    try:
        copyfile(srcfile, dstfile)
    except:
        return()


def copyrcmapsfile():
    """Copy RC maps conf file to directory .config"""
    srcfile = '/storage/.kodi/addons/script.service.argonforty-device/resources/data/rc_maps.cfg'
    dstfile = '/storage/.config/rc_maps.cfg'
    if os.path.isfile(dstfile):
        tmpdsthash = getFileHash(dstfile)
        tmpsrchash = getFileHash(srcfile)
        if tmpdsthash == tmpsrchash:
            return()
    try:
        copyfile(srcfile, dstfile)
    except:
        return()


def mergercmapsfile():
    """
    Copy the the default RC maps conf file to directory .config and add the line for the Argon REMOTE
    If rc_maps.cfg file already exists, just add the reference to argon40.toml file if the line is missing.
    """
    srcfile = '/etc/rc_maps.cfg'
    dstfile = '/storage/.config/rc_maps.cfg'
    # Check if argon40 toml is already included
    if os.path.isfile(dstfile):
        isincluded = False
        with open(dstfile, 'r') as fp:
            for curline in fp:
                if not curline:
                    continue
                tmpline = curline.strip()
                if not tmpline:
                    continue
                if tmpline == 'gpio_ir_recv\t*\targon40.toml' or tmpline == '*\t*\targon40.toml':
                    isincluded = True
                    break
        if isincluded:
            return()
    else:
        try:
            copyfile(srcfile, dstfile)
        except:
            return()

    with open(dstfile, 'a') as fp:
        fp.write('gpio_ir_recv\t*\targon40.toml\n')


def removelircfile():
    """Remove old argon remote LIRC conf file"""
    dstfile = '/storage/.config/lircd.conf'
    if os.path.isfile(dstfile):
        try:
            os.remove(dstfile)
        except:
            return()


def copyshutdownscript():
    """Copy Shutdown script to directory .config"""
    srcfile = '/storage/.kodi/addons/script.service.argonforty-device/resources/data/shutdown.sh'
    dstfile = '/storage/.config/shutdown.sh'
    if os.path.isfile(dstfile):
        tmpdsthash = getFileHash(dstfile)
        tmpsrchash = getFileHash(srcfile)
        if tmpdsthash == tmpsrchash:
            return()
    try:
        copyfile(srcfile, dstfile)
    except:
        return()


def getFileHash(fname):
    """Check file hash"""
    try:
        fp = open(fname, 'rb')
        content = fp.read()
        fp.close()
        return zlib.crc32(content)
    except:
        return 0


def cleanup():
    """Cleanup"""
    # Turn off Fan
    # (2024-02-29) disabled, because throws TimeoutException during shutdown with remote control
    # argonregister_setfanspeed(bus, 0)
    pass
    # GPIO
    # gpiozero automatically restores the pin settings at the end of the script


if bus is None:
    checksetup()
else:
    # Respect user-specific remote control settings
    lockfile = '/storage/.config/argon40_rc.lock'
    if not os.path.exists(lockfile):
        copykeymapfile()
        mergercmapsfile()
        removelircfile()
    copyshutdownscript()
