#!/usr/bin/python3
#
# Misc methods to configure the RPi5 fan PWM via sysfs.
# The output pin GPIO45 (FAN_PWM) must be inverted.
# $ pinctrl FAN_PWM
# 45: a0    pd | hi // FAN_PWM/GPIO45 = PWM1_CHAN3

import os
import glob

PWM_SYSFS = "/sys/class/pwm/"


def determine_pwmchip(address='1f0009c000.pwm'):
    """
    Search for RP1 PWM1 @1f0009c000.pwm
    It is usually pwmchip0, but the order is not guaranteed if other overlays are added,
    so it must be determined dynamically.

    Returns a string with the pwmchip, if found.
    """
    # cat /sys/kernel/debug/pwm
    # RPi2 @3f20c000.pwm
    # RPi5 @1f0009c000.pwm
    pwmchip = None
    for chip in glob.glob(PWM_SYSFS + 'pwmchip*'):
        if (os.path.basename(os.readlink(chip + '/device'))) == address:
            pwmchip = os.path.basename(chip)
    return pwmchip


def enable_kernel_fan_driver():
    """
    Load kernel fan control module
    """
    os.system("modprobe pwm_fan")


def disable_kernel_fan_driver():
    """
    Unload kernel fan control module
    """
    os.system("rmmod pwm_fan")


def export_pwm_channel(pwmchip='pwmchip0', channel='3'):
    """
    Enables the PWM channel, default: PWM1_CHAN3 for RPi5
    """
    try:
        with open("/sys/class/pwm/" + pwmchip + "/export", "w") as exportfp:
            exportfp.write(channel)
        return True
    except IOError:
        return False


def unexport_pwm_channel(pwmchip='pwmchip0', channel='3'):
    """
    Disables the PWM channel, default: PWM1_CHAN3 for RPi5
    """
    try:
        with open("/sys/class/pwm/" + pwmchip + "/unexport", "w") as unexportfp:
            unexportfp.write(channel)
        return True
    except IOError:
        return False


def get_pwm_period(pwmchip='pwmchip0', channel='3'):
    """
    Get the PWM total period (ns)
    """
    try:
        with open("/sys/class/pwm/" + pwmchip + "/pwm" + channel + "/period", "r") as periodfp:
            period = int(periodfp.readline())
        return period
    except IOError:
        return -1


def set_pwm_period(pwmchip='pwmchip0', channel='3', period=41566):
    """
    Set the PWM total period (ns), RPi5 FW default: 41566 (~24.058 kHz)
    """
    try:
        with open("/sys/class/pwm/" + pwmchip + "/pwm" + channel + "/period", "w") as periodfp:
            periodfp.write(str(period))
        return period
    except IOError:
        return -1


def get_pwm_polarity(pwmchip='pwmchip0', channel='3', polarity='inversed'):
    """
    Get the PWM polarity 'normal' or 'inversed'.
    """
    try:
        with open(PWM_SYSFS + pwmchip + "/pwm" + channel + "/polarity", "r") as polarityfp:
            polarity = polarityfp.readline()
        return polarity
    except IOError:
        return None


def set_pwm_polarity(pwmchip='pwmchip0', channel='3', polarity='inversed'):
    """
    Set the PWM polarity 'normal' or 'inversed', default: inversed
    The polarity can only be changed if PWM is not enabled.
    In addition, the period must have been set once in advance.
    """
    try:
        with open(PWM_SYSFS + pwmchip + "/pwm" + channel + "/polarity", "w") as polarityfp:
            polarityfp.write(polarity)
        return True
    except IOError:
        return False


def get_pwm_pulsewidth(pwmchip='pwmchip0', channel='3'):
    """
    Get the PWM pulse width (ns) (duty_cycle).
    """
    try:
        with open(PWM_SYSFS + pwmchip + "/pwm" + channel + "/duty_cycle", "r") as duty_cyclefp:
            pulsewidth = int(duty_cyclefp.readline())
        return pulsewidth
    except IOError:
        return -1


def set_pwm_pulsewidth(pwmchip='pwmchip0', channel='3', pulsewidth=0):
    """
    Set the PWM pulse width (ns) (duty_cycle).
    """
    try:
        with open(PWM_SYSFS + pwmchip + "/pwm" + channel + "/duty_cycle", "w") as duty_cyclefp:
            duty_cyclefp.write(str(pulsewidth))
        return pulsewidth
    except IOError:
        return -1


def get_pwm_duty(pwmchip='pwmchip0', channel='3'):
    """
    Set the PWM duty cycle value in percent.
    """
    period = get_pwm_period(pwmchip, channel)
    dutycycle = round(float(get_pwm_pulsewidth(pwmchip, channel))*100 / float(period))
    return dutycycle


def set_pwm_duty(pwmchip='pwmchip0', channel='3', dutycycle=100):
    """
    Set the PWM duty cycle value in percent.
    """
    period = get_pwm_period(pwmchip, channel)
    pulsewidth = round(float(period) * float(dutycycle)/100)
    set_pwm_pulsewidth(pwmchip, channel, pulsewidth)


def enable_pwm(pwmchip='pwmchip0', channel='3'):
    """ Enable the PWM output"""
    try:
        with open(PWM_SYSFS + pwmchip + "/pwm" + channel + "/enable", "w") as enablefp:
            enablefp.write('1')
        return 1
    except IOError:
        return -1


def disable_pwm(pwmchip='pwmchip0', channel='3'):
    """ Disable the PWM output"""
    try:
        with open(PWM_SYSFS + pwmchip + "/pwm" + channel + "/enable", "w") as enablefp:
            enablefp.write('0')
        return 0
    except IOError:
        return -1


def start_fan():
    """
    Overrides kernel fan control and
    set PWM duty cycle to 100%
    """
    os.system("pinctrl FAN_PWM op dl")


def stop_fan():
    """
    Overrides kernel fan control and
    set PWM duty cycle to 0%
    """
    os.system("pinctrl FAN_PWM op dh")
