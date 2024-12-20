# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2024-present Team LibreELEC (https://libreelec.tv)

PKG_NAME="argonforty-device"
PKG_VERSION="1.1.3"
PKG_SHA256="592677527ada7413ce446a7411a4666b1e7c94a43d1b51abd3e3bc942571eee5"
PKG_REV="0"
PKG_ARCH="arm aarch64"
PKG_LICENSE="MIT"
PKG_SITE="https://github.com/HungerHa/libreelec_package_argonforty-device"
PKG_URL="https://github.com/HungerHa/libreelec_package_argonforty-device/archive/refs/tags/v$PKG_VERSION.tar.gz"
PKG_SECTION="script.service"
PKG_SHORTDESC="ArgonForty Device Configuration"
PKG_LONGDESC="Installs services to manage ArgonForty devices such as power button, fan speed and Argon REMOTE.\
\
This will also enable I2C, IR receiver and UART."
PKG_TOOLCHAIN="manual"
PKG_IS_ADDON="yes"
PKG_ADDON_NAME="ArgonForty Device Configuration"
PKG_ADDON_TYPE="xbmc.service"
PKG_ADDON_PROJECTS="ARM"

addon() {
  mkdir -p ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -P ${PKG_BUILD}/source/addon.xml ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -P ${PKG_BUILD}/changelog.txt ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -P ${PKG_BUILD}/README.md ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -P ${PKG_BUILD}/source/LICENSE ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -P ${PKG_BUILD}/source/default.py ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -P ${PKG_BUILD}/source/main.py ${ADDON_BUILD}/${PKG_ADDON_ID}
  cp -PR ${PKG_BUILD}/source/resources ${ADDON_BUILD}/${PKG_ADDON_ID}
}

post_install_addon() {
  rm ${ADDON_BUILD}/${PKG_ADDON_ID}/resources/fanart.png
}
