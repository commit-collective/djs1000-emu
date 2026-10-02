#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Runs inside the unit's root filesystem, in place of two things the emulator
# has no kernel or init for: the end of /root/pdj/apl_start, which starts the
# app, and udev's rule for a USB stick (12-usb-memory-auto-mount.rules), which
# after mounting it runs /root/pdj/decrypt_autoexec.sh: if the stick holds
# autoexec.bin, that is opened with the unit's key and its autoexec.sh is run
# with the stick's mount point.
#
#   init.sh             power-on: the stick's autoexec if there is one, then
#                       the app; stays until run.sh ends it
#   init.sh autoexec    a stick has just been plugged in
#
# run.sh has already opened autoexec.bin (the loop device it takes needs
# root) and put what it holds on /mnt/iso, where the unit mounts it.
APP=/root/pdj/EP113_Main_R
USB=/media/usb1/sda1

autoexec() {
    if [ -f "$USB/autoexec.bin" ] && [ -f /mnt/iso/autoexec.sh ]; then
        echo "[djsemu] autoexec.sh from the USB drive"
        (cd /mnt/iso && ./autoexec.sh "$USB")
        echo "[djsemu] autoexec.sh returned $?"
    fi
}

if [ "$1" = autoexec ]; then
    autoexec
    exit 0
fi

# A stick that is in at power-on is mounted, and its autoexec run, before
# apl_start gets to the app.
[ "$DJSDEV_USB" = 0 ] || autoexec
cd /root/pdj
echo "[djsemu] start $APP"
$APP &

# The unit runs until it is switched off, and an autoexec may well stop the
# app to start it again: so this stays, and run.sh ends it once no app has
# run for a while.
while :; do
    sleep 3600
done
