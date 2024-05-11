#!/bin/bash
#
# Little helper script to build the add-on archive
#
addon_id="$(sed -n 's:<addon id=\"\(.*\)\" name.*:\1:p' source/addon.xml)"
addon_version="$(sed -n 's:<addon id.*version=\"\(.*\)\" .*:\1:p' source/addon.xml)"
archive_name="libreelec_argondevice_${addon_version}.zip"
archive_dir=~/Documents/Argon40
package_dir=${addon_id}

mkdir -p ${package_dir}
cp changelog.txt ${package_dir}
cp source/addon.xml ${package_dir}
cp source/default.py ${package_dir}
cp source/main.py ${package_dir}
cp source/LICENSE ${package_dir}
cp source/README.md ${package_dir}
cp -r source/resources ${package_dir}
if [ -f ${archive_dir}/${archive_name} ]; then
    echo "Add-on archive for this version already exists."
else
    zip -r9 ${archive_dir}/${archive_name} ${package_dir}
fi
rm -r ${package_dir}
