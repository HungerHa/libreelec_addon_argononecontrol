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
import re
import sys
from shutil import copyfile
from threading import Event
import time
import zlib

# For LibreELEC/Lakka, note that we need to add system paths
sys.path.append('/storage/.kodi/addons/virtual.rpi-tools/lib')
sys.path.append('/storage/.kodi/addons/virtual.system-tools/lib')
# workaround for lgpio issue
# https://github.com/gpiozero/gpiozero/issues/1106
os.environ['LG_WD'] = '/tmp'
gpiod_spec = importlib.util.find_spec('gpiod')
lgpio_spec = importlib.util.find_spec('lgpio')

if gpiod_spec is not None:
    import gpiod
    import select
    import threading
    from gpiod.line import Bias, Edge, Direction
elif lgpio_spec is not None:
    import lgpio
else:
    from gpiozero import Button

import xbmc
import xbmcaddon

from resources.lib.argonregister import *
from resources.lib.argonsysinfo import *
from resources.lib import systemfan

SHUTDOWN_PIN = 4
PWM_FAN_PERIOD = 41566 # default 41566 (~ 24.058 kHz) from cooling_fan overlay
PWM_FAN_CHANNEL = '3' # default RP1 PWM1_CHAN3
PWM_FAN_CH_POLARITY = 'inversed' # default 'inversed' for RPi5 fan

# Initialize I2C Bus
bus = argonregister_initializebusobj()
fansettingupdate = False
power_btn_triggered = False
power_button_mon = Event()
powerbutton_remap = False
pulse_signal = False
addon_count = 0
fanspeed_hdd = False
fanspeed_kernel = False
rp1_detection = True
rp1_fanctrl = False

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


if gpiod_spec is not None:
    """Translate the EdgeType to string"""
    def edge_type_str(event):
        if event.event_type is event.Type.RISING_EDGE:
            return "Rising"
        if event.event_type is event.Type.FALLING_EDGE:
            return "Falling"
        return "Unknown"


    def async_watch_line_value(chip_path, line_offset, done_fd):
        """Observe the pin edges"""
        # Assume a button connecting the pin to ground,
        # so pull it up and provide some debounce.
        with gpiod.request_lines(
            chip_path,
            consumer="Argon ONE Control: async-watch-line-value",
            config={
                line_offset: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.BOTH,
                    bias=Bias.PULL_DOWN,
                )
            },
        ) as request:
            poll = select.poll()
            poll.register(request.fd, select.POLLIN)
            # Other fds could be registered with the poll and be handled
            # separately using the return value (fd, event) from poll():
            poll.register(done_fd, select.POLLIN)
            global power_btn_triggered
            global pulse_signal
            while True:
                for fd, _event in poll.poll():
                    if fd == done_fd:
                        # perform any cleanup before exiting...
                        return
                    # handle any edge events
                    for event in request.read_edge_events():
                        if event.event_type is event.Type.RISING_EDGE:
                            power_btn_triggered = True
                            pulse_signal = True
                        if event.event_type is event.Type.FALLING_EDGE:
                            pulse_signal = False
                        xbmc.log(
                            msg='Argon ONE Control: offset: {}  type: {:<7}  event #{}'.format(
                                event.line_offset, edge_type_str(event), event.line_seqno
                            ), level=xbmc.LOGDEBUG
                        )


def power_btn_pressed(chip=None, gpio=None, level=None, timestamp=None):
    global power_btn_triggered
    power_btn_triggered = True
    if timestamp is not None:
        xbmc.log(msg='Argon ONE Control: power button pressed event -> {}, {}, {}, {}'.format(chip, gpio, level, timestamp), level=xbmc.LOGDEBUG)


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
        xbmc.log(msg='Argon ONE Control: power button monitoring was not running', level=xbmc.LOGDEBUG)
        return

    global power_btn_triggered
    power_btn_triggered = False
    if gpiod_spec is not None:
        xbmc.log(msg='Argon ONE Control: power button monitoring via gpiod', level=xbmc.LOGDEBUG)
        #Initialize GPIO
        # open the gpio chip and set the pin 4 as input (pull down)
        if gpiod.is_gpiochip_device('/dev/gpiochip4'):
            # temporary RPi5 gpiochip assignment up to kernel 6.6.45
            # https://github.com/raspberrypi/linux/pull/6144
            gpiochip = '/dev/gpiochip4'
        else:
            # common
            gpiochip = '/dev/gpiochip0'

        # run the async executor (select.poll) in a thread to demonstrate a graceful exit.
        done_fd = os.eventfd(0)

        def bg_thread():
            try:
                async_watch_line_value(gpiochip, SHUTDOWN_PIN, done_fd)
            except OSError as ex:
                xbmc.log(msg='Argon ONE Control: gpiod background thread failing', level=xbmc.LOGDEBUG)
            xbmc.log(msg='Argon ONE Control: gpiod background thread exiting...', level=xbmc.LOGDEBUG)

        t = threading.Thread(target=bg_thread)
        t.start()
    elif lgpio_spec is not None:
        xbmc.log(msg='Argon ONE Control: power button monitoring via lgpio', level=xbmc.LOGDEBUG)
        #Initialize GPIO
        # open the gpio chip and set the pin 4 as input (pull down)
        lgpio.exceptions = False
        h = lgpio.gpiochip_open(4)
        if h >= 0:
            # RPi5 mapping until kernel 6.6.45
            chip = 4
        else:
            # common mapping / RPi5 kernel version >= 6.6.45
            chip = 0
            h = lgpio.gpiochip_open(0)
        lgpio.exceptions = True
        #lgpio.gpio_claim_input(h, SHUTDOWN_PIN, lFlags=lgpio.SET_PULL_DOWN)
        err = lgpio.gpio_claim_alert(h, SHUTDOWN_PIN, eFlags=lgpio.RISING_EDGE, lFlags=lgpio.SET_PULL_DOWN)
        if err < 0:
            xbmc.log(msg="GPIO in use {}:{} ({})".format(chip, SHUTDOWN_PIN, lgpio.error_text(err)), level=xbmc.LOGDEBUG)
        cb_power_btn = lgpio.callback(h, SHUTDOWN_PIN, edge=lgpio.RISING_EDGE, func=power_btn_pressed)
    else:
        xbmc.log(msg='Argon ONE Control: power button monitoring via gpiozero', level=xbmc.LOGDEBUG)
        # pull down the pin
        btn = Button(SHUTDOWN_PIN, pull_up=False)
        btn.when_pressed = power_btn_pressed

    while True:
        if not power_button_mon.is_set():
            xbmc.log(msg='Argon ONE Control: power button monitoring has been disabled', level=xbmc.LOGDEBUG)
        power_button_mon.wait()
        if abort_flag.is_set():
            break
        pulsetime = 1
        time.sleep(0.001)
        if power_btn_triggered:
            power_btn_triggered = False
            xbmc.log(msg='Argon ONE Control: power button was pressed', level=xbmc.LOGDEBUG)
            time.sleep(0.01)
            # wait until the button is released
            if gpiod_spec is not None:
                # gpiod in use
                while pulse_signal:
                    time.sleep(0.01)
                    pulsetime += 1
                    if abort_flag.is_set() or not power_button_mon.is_set():
                        xbmc.log(msg='Argon ONE Control: button monitoring loop 2 aborted', level=xbmc.LOGDEBUG)
                        break
            elif lgpio_spec is not None:
                # lgpio in use
                while lgpio.gpio_read(h, SHUTDOWN_PIN) == 1:
                    time.sleep(0.01)
                    pulsetime += 1
                    if abort_flag.is_set() or not power_button_mon.is_set():
                        xbmc.log(msg='Argon ONE Control: button monitoring loop 2 aborted', level=xbmc.LOGDEBUG)
                        break
            else:
                # gpiozero in use
                while btn.is_pressed:
                    time.sleep(0.01)
                    pulsetime += 1
                    if abort_flag.is_set() or not power_button_mon.is_set():
                        xbmc.log(msg='Argon ONE Control: button monitoring loop 2 aborted', level=xbmc.LOGDEBUG)
                        break

            xbmc.log(msg='Argon ONE Control: power button was released', level=xbmc.LOGDEBUG)
            if pulsetime >= 2 and pulsetime <= 3:
                if powerbutton_remap:
                    xbmc.shutdown()
                else:
                    xbmc.restart()
            elif pulsetime >= 4 and pulsetime <= 5:
                xbmc.shutdown()
        if abort_flag.is_set():
            xbmc.log(msg='Argon ONE Control: button monitoring loop 1 aborted', level=xbmc.LOGDEBUG)
            break
    # freeing the GPIO resources
    if gpiod_spec is not None:
        # gpiod in use
        # stop background thread
        t.join(0.2)
        if t.is_alive():
            os.eventfd_write(done_fd, 1)
            t.join()
        os.close(done_fd)
    elif lgpio_spec is not None:
        # lgpio in use
        cb_power_btn.cancel()
        cb_power_btn = None
        free_pin = lgpio.gpio_free(h, SHUTDOWN_PIN)
        if free_pin == 0:
            xbmc.log(msg='Argon ONE Control: power button GPIO pin freed', level=xbmc.LOGDEBUG)
        close_chip = lgpio.gpiochip_close(h)
        if close_chip < 0:
            xbmc.log(msg='Argon ONE Control: GPIO chip could not be closed', level=xbmc.LOGDEBUG)
    else:
        # gpiozero in use
        btn.close()
        if btn.closed:
            xbmc.log(msg='Argon ONE Control: power button pin freed', level=xbmc.LOGDEBUG)
    xbmc.log(msg='Argon ONE Control: power button monitoring stopped', level=xbmc.LOGDEBUG)


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


def is_pitwo():
    """
    Detect if the current PCB is a RPi2
    """
    try:
        with open("/proc/cpuinfo", "r") as cpuinfo:
            for line in cpuinfo.readlines():
                revision = re.search(r'^Revision\s*:\s*[ 123][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]04[0-9a-fA-F]$', line)
                if revision is not None:
                    return True
        return False
    except IOError:
        return False


def is_pifour():
    """
    Detect if the current PCB is a RPi4
    """
    try:
        with open("/proc/cpuinfo", "r") as cpuinfo:
            for line in cpuinfo.readlines():
                revision = re.search(r'^Revision\s*:\s*[ 123][0-9a-fA-F][0-9a-fA-F]3[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]$', line)
                if revision is not None:
                    return True
        return False
    except IOError:
        return False


def is_pifive():
    """
    Detect if the current PCB is a RPi5
    """
    try:
        with open("/proc/cpuinfo", "r") as cpuinfo:
            for line in cpuinfo.readlines():
                revision = re.search(r'^Revision\s*:\s*[ 123][0-9a-fA-F][0-9a-fA-F]4[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]$', line)
                if revision is not None:
                    return True
        return False
    except IOError:
        return False


def load_config():
    """
    This function retrieves the fanspeed configuration list from a file, arranged by temperature.
    It ignores lines beginning with "#" and checks if the line is a valid temperature-speed pair.
    The temperature values are formatted to uniform length, so the lines can be sorted properly.
    """
    ADDON = xbmcaddon.Addon()

    global fanspeed_hdd
    global power_button_mon
    global powerbutton_remap
    global fanspeed_kernel
    global rp1_detection

    fanspeed_kernel = ADDON.getSettingBool('fanspeed_kernel')
    powerbutton = ADDON.getSettingBool('powerbutton')
    powerbutton_remap = ADDON.getSettingBool('powerbutton_remap')
    if powerbutton:
        if not power_button_mon.is_set():
            xbmc.log(msg='Argon ONE Control: power button monitoring has been enabled', level=xbmc.LOGDEBUG)
        power_button_mon.set()
    else:
        power_button_mon.clear()

    newconfig = []
    newhddconfig = []
    newgpuconfig = []
    newpmicconfig = []

    cmdset_legacy = ADDON.getSettingBool('cmdset_legacy')
    fanspeed_disable = ADDON.getSettingBool('fanspeed_disable')
    if fanspeed_disable:
        return [['90=100'], newgpuconfig, newhddconfig, newpmicconfig, cmdset_legacy]
    fanspeed_alwayson = ADDON.getSettingBool('fanspeed_alwayson')
    if fanspeed_alwayson:
        return [['1=100'], newgpuconfig, newhddconfig, newpmicconfig, cmdset_legacy]
    fanspeed_gpu = ADDON.getSettingBool('fanspeed_gpu')
    fanspeed_hdd = ADDON.getSettingBool('fanspeed_hdd')
    fanspeed_pmic = ADDON.getSettingBool('fanspeed_pmic')
    rp1_detection = ADDON.getSettingBool('rp1_detection')
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

    return [ newconfig, newgpuconfig, newhddconfig, newpmicconfig, cmdset_legacy ]


def temp_check(abort_flag):
    """
    This function is the thread that monitors temperature and sets the fan speed.
    The value is fed to get_fanspeed to get the new fan speed.
    To prevent unnecessary fluctuations, lowering fan speed is delayed by 30 seconds.

    Location of config file varies based on OS
    """
    global fansettingupdate
    global fanspeed_hdd
    global pwmchip

    cmdset_detect = True
    argonregsupport = True
    fanconfig = ['65=100', '60=55', '55=10']
    fanhddconfig = ['50=100', '40=55', '30=30']

    prevspeed=-1

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

        if not fanspeed_kernel:
            # Force the old I2C message style without register support to
            # prevent the MCU from hanging on early firmware revisions.
            cmdset_legacy = tmpconfig[4]
            if cmdset_legacy:
                cmdset_detect = True
                argonregsupport = False
                xbmc.log(msg='Argon ONE Control: legacy command set only', level=xbmc.LOGDEBUG)
            else:
                if cmdset_detect:
                    xbmc.log(msg='Argon ONE Control: command set detection', level=xbmc.LOGDEBUG)
                    argonregsupport = argonregister_checksupport(bus)
                    cmdset_detect = False
                xbmc.log(msg='Argon ONE Control: command set with register support : ' + str(argonregsupport), level=xbmc.LOGDEBUG)

        fansettingupdate = False
        if fanspeed_kernel:
            thread_sleep(60, abort_flag)
        else:
            while not fansettingupdate:
                # Speed based on CPU Temp
                val = argonsysinfo_getcputemp()
                xbmc.log(msg='Argon ONE Control: current CPU temperature : ' + str(val), level=xbmc.LOGDEBUG)
                newspeed = get_fanspeed(val, fanconfig)
                # Speed based on GPU Temp
                val = argonsysinfo_getgputemp()
                xbmc.log(msg='Argon ONE Control: current GPU temperature : ' + str(val), level=xbmc.LOGDEBUG)
                gpuspeed = get_fanspeed(val, fangpuconfig)
                # Speed based on SSD/NVMe Temp
                if fanspeed_hdd:
                    val = argonsysinfo_getmaxhddtemp()
                    xbmc.log(msg='Argon ONE Control: current SSD/NVMe temperature : ' + str(val), level=xbmc.LOGDEBUG)
                else:
                    val = 0
                    xbmc.log(msg='Argon ONE Control: SSD/NVMe temperature ignored.', level=xbmc.LOGDEBUG)
                hddspeed = get_fanspeed(val, fanhddconfig)
                # Speed based on PMIC Temp
                val = argonsysinfo_getpmictemp()
                xbmc.log(msg='Argon ONE Control: current PMIC temperature : ' + str(val), level=xbmc.LOGDEBUG)
                pmicspeed = get_fanspeed(val, fanpmicconfig)
                xbmc.log(msg='Argon ONE Control: CPU fan speed value : ' + str(newspeed), level=xbmc.LOGDEBUG)
                xbmc.log(msg='Argon ONE Control: GPU fan speed value : ' + str(gpuspeed), level=xbmc.LOGDEBUG)
                xbmc.log(msg='Argon ONE Control: SSD/NVMe fan speed value : ' + str(hddspeed), level=xbmc.LOGDEBUG)
                xbmc.log(msg='Argon ONE Control: PMIC fan speed value : ' + str(pmicspeed), level=xbmc.LOGDEBUG)

                # Use faster fan speed
                if gpuspeed > newspeed:
                    newspeed = gpuspeed
                if hddspeed > newspeed:
                    newspeed = hddspeed
                if pmicspeed > newspeed:
                    newspeed = pmicspeed

                if newspeed == prevspeed:
                    thread_sleep(30, abort_flag)
                    if abort_flag.is_set():
                        break
                    continue
                elif newspeed < prevspeed:
                    thread_sleep(30, abort_flag)
                try:
                    if rp1_fanctrl and rp1_detection:
                        systemfan.set_pwm_duty(pwmchip=pwmchip, channel=PWM_FAN_CHANNEL, dutycycle=newspeed)
                    else:
                        argonregister_setfanspeed(bus, newspeed, argonregsupport)
                    thread_sleep(30, abort_flag)
                    prevspeed = newspeed
                except IOError:
                    temp = ''
                    thread_sleep(60, abort_flag)
                if abort_flag.is_set():
                    break
        if abort_flag.is_set():
            break


def checksetup():
    """Used to enable I2C and UART"""
    configfile = '/flash/config.txt'

    # Add argon remote control
    lockfile = '/storage/.config/argon40_rc.lock'
    if not os.path.exists(lockfile):
        copykeymapfile()
        mergercmapsfile()
        removelircfile()

    # Check if I2C line exists
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
        fp.write('\n')
        fp.write('# Argon ONE Control: fan control, power button events, IR support for ONE V1/2/3\n')
        fp.write('dtparam=i2c=on\n')
        fp.write('enable_uart=1\n')
        fp.write('dtoverlay=gpio-ir,gpio_pin=23\n')
    os.system('mount -o remount,ro /flash')


def setup_rpi5_cooling_fan_overlay():
    """
    Used to modify cooling_fan overlay values in config.txt
    https://github.com/raspberrypi/rpi-firmware/blob/master/overlays/README
    https://github.com/raspberrypi/rpi-firmware/blob/master/bcm2712-rpi-5-b.dtb
    https://github.com/raspberrypi/linux/blob/rpi-6.18.y/arch/arm64/boot/dts/broadcom/bcm2712-rpi-5-b.dts
    """
    ADDON = xbmcaddon.Addon()

    configfile = '/flash/config.txt'
    tmpconfigfile = '/tmp/config.new'

    # Check if values already set or changed
    xbmc.log(msg='Argon ONE Control: Check kernel fan overlay values', level=xbmc.LOGDEBUG)
    isconfigured = False
    haschanged = False
    with open(configfile, 'r') as lines, open(tmpconfigfile, 'w') as newconfig:
        for curline in lines:
            if not curline:
                continue
            tmpline = curline.strip()
            if not tmpline:
                newconfig.write(curline)
                continue
            if tmpline.startswith('dtparam=cooling_fan='):
                isconfigured = True
                # 2025/11/02: Dropped because disabling the cooling_fan overlay
                #             could cause the fan to run continuously at full speed.
                # if ADDON.getSettingBool('fanspeed_disable'):
                #     if tmpline == 'dtparam=cooling_fan=on':
                #         tmpline = 'dtparam=cooling_fan=off'
                #         haschanged = True
                # elif tmpline == 'dtparam=cooling_fan=off':
                if tmpline == 'dtparam=cooling_fan=off':
                    tmpline = 'dtparam=cooling_fan=on'
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp0='):
                if ADDON.getSettingBool('fanspeed_alwayson'):
                    if tmpline != 'dtparam=fan_temp0=0':
                        tmpline = 'dtparam=fan_temp0=0'
                        haschanged = True
                elif tmpline != 'dtparam=fan_temp0=' + str(int(ADDON.getSetting('cputemp_a')) * 1000):
                    tmpline = 'dtparam=fan_temp0=' + str(int(ADDON.getSetting('cputemp_a')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp0_hyst='):
                if tmpline != 'dtparam=fan_temp0_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_a')) * 1000):
                    tmpline = 'dtparam=fan_temp0_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_a')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp0_speed='):
                if ADDON.getSettingBool('fanspeed_alwayson'):
                    if tmpline != 'dtparam=fan_temp0_speed=128':
                        tmpline = 'dtparam=fan_temp0_speed=128'
                        haschanged = True
                elif tmpline != 'dtparam=fan_temp0_speed=' + str(round(float(ADDON.getSetting('fanspeed_a')) * 255/100)):
                    tmpline = 'dtparam=fan_temp0_speed=' + str(round(float(ADDON.getSetting('fanspeed_a')) * 255/100))
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp1='):
                if tmpline != 'dtparam=fan_temp1=' + str(int(ADDON.getSetting('cputemp_b')) * 1000):
                    tmpline = 'dtparam=fan_temp1=' + str(int(ADDON.getSetting('cputemp_b')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp1_hyst='):
                if tmpline != 'dtparam=fan_temp1_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_b')) * 1000):
                    tmpline = 'dtparam=fan_temp1_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_b')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp1_speed='):
                if ADDON.getSettingBool('fanspeed_alwayson'):
                    if tmpline != 'dtparam=fan_temp1_speed=128':
                        tmpline = 'dtparam=fan_temp1_speed=128'
                        haschanged = True
                elif tmpline != 'dtparam=fan_temp1_speed=' + str(round(float(ADDON.getSetting('fanspeed_b')) * 255/100)):
                    tmpline = 'dtparam=fan_temp1_speed=' + str(round(float(ADDON.getSetting('fanspeed_b')) * 255/100))
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp2='):
                if tmpline != 'dtparam=fan_temp2=' + str(int(ADDON.getSetting('cputemp_c')) * 1000):
                    tmpline = 'dtparam=fan_temp2=' + str(int(ADDON.getSetting('cputemp_c')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp2_hyst='):
                if tmpline != 'dtparam=fan_temp2_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_c')) * 1000):
                    tmpline = 'dtparam=fan_temp2_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_c')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp2_speed='):
                if ADDON.getSettingBool('fanspeed_alwayson'):
                    if tmpline != 'dtparam=fan_temp2_speed=128':
                        tmpline = 'dtparam=fan_temp2_speed=128'
                        haschanged = True
                elif tmpline != 'dtparam=fan_temp2_speed=' + str(round(float(ADDON.getSetting('fanspeed_c')) * 255/100)):
                    tmpline = 'dtparam=fan_temp2_speed=' + str(round(float(ADDON.getSetting('fanspeed_c')) * 255/100))
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp3='):
                if tmpline != 'dtparam=fan_temp3=' + str(int(ADDON.getSetting('cputemp_d')) * 1000):
                    tmpline = 'dtparam=fan_temp3=' + str(int(ADDON.getSetting('cputemp_d')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp3_hyst='):
                if tmpline != 'dtparam=fan_temp3_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_d')) * 1000):
                    tmpline = 'dtparam=fan_temp3_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_d')) * 1000)
                    haschanged = True
            if tmpline.startswith('dtparam=fan_temp3_speed='):
                if ADDON.getSettingBool('fanspeed_alwayson'):
                    if tmpline != 'dtparam=fan_temp3_speed=128':
                        tmpline = 'dtparam=fan_temp3_speed=128'
                        haschanged = True
                elif tmpline != 'dtparam=fan_temp3_speed=' + str(round(float(ADDON.getSetting('fanspeed_d')) * 255/100)):
                    tmpline = 'dtparam=fan_temp3_speed=' + str(round(float(ADDON.getSetting('fanspeed_d')) * 255/100))
                    haschanged = True
            newconfig.write(tmpline +'\n')

    # Do not change config.txt file if values are unchanged
    if isconfigured and not haschanged:
        xbmc.log(msg='Argon ONE Control: Kernel fan overlay values already set', level=xbmc.LOGDEBUG)
        os.system("rm " + tmpconfigfile)
        return()
    elif not isconfigured:
        # Append initial fan overlay values to config.txt
        xbmc.log(msg='Argon ONE Control: Append kernel fan overlay values to config.txt', level=xbmc.LOGDEBUG)
        with open(configfile, 'a') as fp:
            fp.write('\n')
            fp.write('# Argon ONE Control: RPi5 fan overlay settings\n')
            # 2025/11/02: Dropped because disabling the cooling_fan overlay
            #             could cause the fan to run continuously at full speed.
            # if ADDON.getSettingBool('fanspeed_disable'):
            #     fp.write('dtparam=cooling_fan=off\n')
            # else:
            fp.write('dtparam=cooling_fan=on\n')
            if ADDON.getSettingBool('fanspeed_alwayson'):
                fp.write('dtparam=fan_temp0=0')
            else:
                fp.write('dtparam=fan_temp0=' + str(int(ADDON.getSetting('cputemp_a')) * 1000) + '\n')
            fp.write('dtparam=fan_temp0_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_a')) * 1000) + '\n')
            if ADDON.getSettingBool('fanspeed_alwayson'):
                fp.write('dtparam=fan_temp0_speed=128')
            elif ADDON.getSettingBool('fanspeed_disable'):
                fp.write('dtparam=fan_temp0_speed=0')
            else:
                fp.write('dtparam=fan_temp0_speed=' + str(round(float(ADDON.getSetting('fanspeed_a')) * 255/100)) + '\n')
            fp.write('dtparam=fan_temp1=' + str(int(ADDON.getSetting('cputemp_b')) * 1000) + '\n')
            fp.write('dtparam=fan_temp1_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_b')) * 1000) + '\n')
            if ADDON.getSettingBool('fanspeed_alwayson'):
                fp.write('dtparam=fan_temp1_speed=128')
            elif ADDON.getSettingBool('fanspeed_disable'):
                fp.write('dtparam=fan_temp1_speed=0')
            else:
                fp.write('dtparam=fan_temp1_speed=' + str(round(float(ADDON.getSetting('fanspeed_b')) * 255/100)) + '\n')
            fp.write('dtparam=fan_temp2=' + str(int(ADDON.getSetting('cputemp_c')) * 1000) + '\n')
            fp.write('dtparam=fan_temp2_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_c')) * 1000) + '\n')
            if ADDON.getSettingBool('fanspeed_alwayson'):
                fp.write('dtparam=fan_temp2_speed=128')
            elif ADDON.getSettingBool('fanspeed_disable'):
                fp.write('dtparam=fan_temp2_speed=0')
            else:
                fp.write('dtparam=fan_temp2_speed=' + str(round(float(ADDON.getSetting('fanspeed_c')) * 255/100)) + '\n')
            fp.write('dtparam=fan_temp3=' + str(int(ADDON.getSetting('cputemp_d')) * 1000) + '\n')
            fp.write('dtparam=fan_temp3_hyst=' + str(int(ADDON.getSetting('cputemp_hyst_d')) * 1000) + '\n')
            if ADDON.getSettingBool('fanspeed_alwayson'):
                fp.write('dtparam=fan_temp3_speed=128')
            elif ADDON.getSettingBool('fanspeed_disable'):
                fp.write('dtparam=fan_temp3_speed=0')
            else:
                fp.write('dtparam=fan_temp3_speed=' + str(round(float(ADDON.getSetting('fanspeed_d')) * 255/100)) + '\n')
        return()

    # Apply changed overlay values to config.txt
    xbmc.log(msg='Argon ONE Control: Set kernel fan overlay values', level=xbmc.LOGDEBUG)
    os.system("mount -o remount,rw /flash")
    os.system("mv " + tmpconfigfile + " " + configfile)
    os.system('mount -o remount,ro /flash')


def copykeymapfile():
    """Copy RC keytable file to rc_keymaps directory"""
    srcfile = '/storage/.kodi/addons/service.argononecontrol/resources/data/argon40.toml'
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
    srcfile = '/storage/.kodi/addons/service.argononecontrol/resources/data/rc_maps.cfg'
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
    srcfile = '/storage/.kodi/addons/service.argononecontrol/resources/data/shutdown.sh'
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
    if fanspeed_kernel:
        setup_rpi5_cooling_fan_overlay()
    if rp1_fanctrl:
        systemfan.disable_pwm(pwmchip, PWM_FAN_CHANNEL)
        systemfan.unexport_pwm_channel(pwmchip, PWM_FAN_CHANNEL)
    # GPIO
    # gpiozero automatically restores the pin settings at the end of the script


__addon__ = xbmcaddon.Addon()
__addonname__ = __addon__.getAddonInfo('name')
__icon__ = __addon__.getAddonInfo('icon')

if bus is None:
    checksetup()
    # Send message to GUI about reboot required
    msg_line = "I2C not enabled yet. Fan control requires a reboot."
    msg_time = 15000 #in miliseconds
    xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%(__addonname__, msg_line, msg_time, __icon__))
else:
    # Respect user-specific remote control settings
    lockfile = '/storage/.config/argon40_rc.lock'
    if not os.path.exists(lockfile):
        copykeymapfile()
        mergercmapsfile()
        removelircfile()
    copyshutdownscript()

    fanspeed_kernel = __addon__.getSettingBool('fanspeed_kernel')
    powerbutton = __addon__.getSettingBool('powerbutton')
    rp1_detection = __addon__.getSettingBool('rp1_detection')
    if rp1_detection and not fanspeed_kernel:
        # # Debug mode: Load PWM overlay to make pwmchipN available
        # xbmc.log(msg='Argon ONE Control: Check for overlay', level=xbmc.LOGDEBUG)
        # if not os.path.isdir('/sys/class/pwm/pwmchip0'):
        #     os.system("dtoverlay pwm")
        #     time.sleep(0.1)

        # Detect cooling_fan/PWM overlay
        if os.path.isdir('/sys/class/pwm/pwmchip0'):
            xbmc.log(msg='Argon ONE Control: PWM overlay loaded', level=xbmc.LOGDEBUG)
            # Execute only if RPi5
            if is_pifive():
                xbmc.log(msg='Argon ONE Control: RPi5 detected', level=xbmc.LOGDEBUG)
                xbmc.log(msg='Argon ONE Control: Unload PWM_FAN module', level=xbmc.LOGDEBUG)
                systemfan.disable_kernel_fan_driver()
                # Search for RP1 PWM1 register address
                pwmchip = systemfan.determine_pwmchip(address='1f0009c000.pwm')
                if pwmchip is not None:
                    # Configure FAN_PWM output
                    xbmc.log(msg='Argon ONE Control: Configure RP1 PWM1_CHAN3 output @' + pwmchip, level=xbmc.LOGDEBUG)
                    systemfan.export_pwm_channel(pwmchip, PWM_FAN_CHANNEL)
                    systemfan.set_pwm_period(pwmchip, PWM_FAN_CHANNEL, PWM_FAN_PERIOD)
                    systemfan.set_pwm_polarity(pwmchip, PWM_FAN_CHANNEL, PWM_FAN_CH_POLARITY)
                    systemfan.enable_pwm(pwmchip, PWM_FAN_CHANNEL)
                    rp1_fanctrl = True

    # Send message to GUI about add-on start
    if rp1_fanctrl:
        msg_line = "ONE V5 / NEO 5 / Active Cooler detected."
    elif fanspeed_kernel:
        msg_line = "ONE V5 / NEO 5 / Active Cooler control via cooling_fan overlay."
    else:
        msg_line = "Fan control/power button event monitoring has started."
    msg_time = 5000 #in miliseconds
    xbmc.executebuiltin('Notification(%s, %s, %d, %s)'%(__addonname__, msg_line, msg_time, __icon__))
    addon_count = addon_count + 1
    xbmc.log(msg='Argon ONE Control: Add-on started. ' + str(addon_count), level=xbmc.LOGDEBUG)
