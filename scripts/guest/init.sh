#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Runs inside the unit's root filesystem, in place of two things the emulator
# has no kernel or init for: the end of /root/pdj/apl_start, which starts the
# app, and udev's rules for a USB stick. On the unit, plugging one in makes
# udev write "connect" to the message queue /proc/udev_usbctn1
# (75-usb-caution.rules), then mount it, run /root/pdj/decrypt_autoexec.sh
# (if the stick holds autoexec.bin, that is opened with the unit's key and
# its autoexec.sh run with the stick's mount point) and only then write
# "mount <path>" to /proc/udev_usb1 (12-usb-memory-auto-mount.rules), which
# is how the app learns of the stick. Taking it out writes "umount <path>" and
# "disconnect". The shim keeps those queues as the kernel does.
#
#   init.sh             power-on: the stick as udev finds it, then the app;
#                       stays until run.sh ends it
#   init.sh plug        a stick has just been plugged in ("usb 1")
#   init.sh unplug      and taken out ("usb 0")
#
# DJSDEV_DIRECT=1 (a test's shortcut, DJS_FAST_BOOT=1 on the host): when the stick
# holds an autoexec, the app is not started here first and stopped again by the
# patch: the patch starts it once, with the mods. That saves a whole boot of the
# app; the restart itself is what the tests without the shortcut see.
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
        still_in_iso
    fi
}

# On the unit, decrypt_autoexec.sh unmounts /mnt/iso and lets go of the
# stick's autoexec.bin as soon as autoexec.sh returns; while a process is
# still in there it cannot, and the stick stays busy (USB STOP then hangs).
# Here nothing is unmounted, so say so instead.
still_in_iso() {
    sleep 1
    for p in /proc/[0-9]*; do
        case $(readlink "$p/cwd" 2> /dev/null) in
        /mnt/iso | /mnt/iso/*)
            echo "[djsemu] WARNING: ...$(tr '\0' ' ' < "$p/cmdline" | tail -c 60) is still in" \
                "/mnt/iso: on the unit, the autoexec image could not be unmounted"
            ;;
        esac
    done
}

plug() {
    echo -n connect > /proc/udev_usbctn1
    autoexec
    echo -n "mount $USB" > /proc/udev_usb1
}

case $1 in
plug)
    plug
    exit 0
    ;;
unplug)
    echo -n "umount $USB" > /proc/udev_usb1
    echo -n disconnect > /proc/udev_usbctn1
    exit 0
    ;;
esac

# A stick that is in at power-on is mounted, and its autoexec run, before
# apl_start gets to the app; the queues keep what udev wrote for it.
[ "$DJSDEV_USB" = 0 ] || plug
cd /root/pdj
if [ "$DJSDEV_DIRECT" = 1 ] && [ "$DJSDEV_USB" != 0 ] && [ -f /mnt/iso/autoexec.sh ]; then
    echo "[djsemu] the stick's autoexec starts the app"
else
    echo "[djsemu] start $APP"
    $APP &
fi

# The stick's autoexec leaves the restart of the app (with the mods) to a copy of itself, detached; on this
# emulator that copy has now and then died without a word, and the app ran without the mods. So: if the mods
# were put in /tmp but the app does not have them some time later, the autoexec is run again, which does the
# restart as it does for a stick plugged in later (twice at most).
if [ "$DJSDEV_USB" != 0 ] && [ -f /mnt/iso/autoexec.sh ]; then
    (
        tries=0
        while [ $tries -lt 2 ]; do
            sleep 40
            [ -f /tmp/djs1000-mods/libmods.so ] || break
            # any of the app's processes (qemu, its wrapper, one on its way out) having the mods is enough
            have=0
            for pid in $(pidof EP113_Main_R); do
                grep -q libmods.so "/proc/$pid/maps" 2> /dev/null && have=1
            done
            [ $have = 1 ] && break
            echo "[djsemu] the mods did not start: running the stick's autoexec again"
            (cd /mnt/iso && ./autoexec.sh "$USB")
            tries=$((tries + 1))
        done
    ) &
fi

# The unit runs until it is switched off, and an autoexec may well stop the
# app to start it again: so this stays, and run.sh ends it once no app has
# run for a while.
while :; do
    sleep 3600
done
