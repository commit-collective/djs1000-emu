#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Run the DJS-1000 app (EP113_Main_R) under qemu-arm user mode, in the rootfs
# scripts/setup.sh assembled in $DJS_HOME (default ~/djs), with the djsdev shim
# standing in for the board's devices. The app draws on a display of its own
# (Xvfb) that nobody sees: the virtual deck shows its screen. With
# DJS_WINDOW=1, or without Xvfb, its window opens on DISPLAY (:0, WSLg's, by
# default: the app opens ":0.0" whatever DISPLAY says).
#
#   scripts/run.sh [seconds] [extra qemu-arm args, e.g. "-g 1234" for gdb]
#
# seconds: how long to run. 0 for no limit.
# The shim is rebuilt from shim/djsdev.c on every run. The app's output goes
# to stdout/stderr. The panel command pipe is $DJS_HOME/root/tmp/djspanel.
set -u
REPO="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")"
DJS="${DJS_HOME:-$HOME/djs}"
ROOT=$DJS/root
secs=${1:-60}
shift || true
# An emulator of a slot (see start.py) has a tag among the arguments of every process of its guest, and finds
# and ends only those.
TAG="${DJSDEV_TAG:-}"
# The ids of the processes of this emulator whose command line matches the pattern (with a tag: those that have it in
# their environment. The guest is run by proot or by a chroot, and the program is in the command line in both).
pids_of() {
    for p in $(pgrep -f "$1"); do
        [ "$p" = "$$" ] && continue
        if [ -z "$TAG" ] || grep -qaP "DJSDEV_TAG=$TAG\x00" "/proc/$p/environ" 2> /dev/null; then echo "$p"; fi
    done
}

if [ -n "$(pids_of EP113_Main_R)" ]; then
    echo "the emulator is already running: stop it first (python start.py stop)" >&2
    exit 1
fi
test -x "$ROOT/root/pdj/EP113_Main_R" || { echo "no rootfs in $ROOT: run scripts/setup.sh first" >&2; exit 1; }
mkdir -p "$ROOT/opt/djsemu" "$ROOT/mnt/debug" "$ROOT/var/log" "$ROOT/root/data" "$ROOT/tmp" "$DJS/run"
# What /root/pdj/apl_start does before it starts the app, as far as it applies
# here: fresh browse/ and project/ working folders, and the mount points.
rm -rf "$ROOT/root/pdj/browse" "$ROOT/root/pdj/project"
mkdir -p "$ROOT/root/pdj/browse" "$ROOT/root/pdj/project" "$ROOT/mnt/usb" "$ROOT/mnt/emmc"
# The pads' factory calibration, which lives on the unit's data partition:
# for each pad, the sensor reading at which a hit begins (217-454). Without
# it the app takes every pad as held down for ever, and blinks them all red.
# $DJS_DATA stands in for that partition (default: root/data in the rootfs).
# A fresh folder is a unit with its settings as they left the factory.
DATA="${DJS_DATA:-$ROOT/root/data}"
mkdir -p "$DATA"
CAL="$DATA/PadCalibration.xml"
if [ ! -s "$CAL" ]; then
    {
        printf '<?xml version="1.0" encoding="UTF-8"?>\n\n<PadCalibrationData'
        for k in Final Provisional1 Provisional2 Provisional3; do
            for n in $(seq -w 1 16); do printf ' Pad%s_%s="336"' "$n" "$k"; done
        done
        printf '/>\n'
    } > "$CAL"
fi
# The USB drive: a folder on the host ($DJS_USB, default $DJS_HOME/usb), which
# the shim reports as a drive mounted on /media/usb1/sda1.
USB="${DJS_USB:-$DJS/usb}"
mkdir -p "$USB" "$ROOT/media/usb1/sda1"
# The unit's internal storage (the eMMC, a FAT volume mounted on /mnt/emmc: the factory samples and projects, and the
# user's): a folder on the host, $DJS_EMMC, if there is one. Without it /mnt/emmc is an empty folder.
EMMC="${DJS_EMMC:-}"
[ -z "$EMMC" ] && [ -d "$DJS/emmc/PIONEER DJ SAMPLER" ] && EMMC="$DJS/emmc"      # or $DJS_HOME/emmc, when it holds one
[ -n "$EMMC" ] && mkdir -p "$EMMC"
# The unit's /tmp is in RAM: empty at each start, with the USB message queues
# the shim keeps there (see queue_put() in shim/djsdev.c).
find "$ROOT/tmp" -mindepth 1 -delete
arm-linux-gnueabihf-gcc -O2 -fPIC -shared -nostdlib -mfloat-abi=softfp -marm \
    -o "$ROOT/opt/djsemu/libdjsdev.so" "$REPO/shim/djsdev.c" \
    "$ROOT/lib/libdl.so.2" "$ROOT/lib/libc.so.6" "$ROOT/lib/libpthread.so.0" || exit 1

# The guest environment goes through qemu's -E, not a guest `env`, so that a
# gdb attached with -g debugs the app itself rather than env.
cd "$DJS"

# The app draws through X. With Xvfb installed it is given a display of its
# own that nobody sees (the virtual deck shows its screen). DJS_WINDOW=1, or
# no Xvfb, puts its window on $DISPLAY instead.
XVFB_PID=
XDISPLAY=
if [ -z "${DJS_WINDOW:-}" ] && command -v Xvfb > /dev/null; then
    # A display is looked for among the sockets in use, not among the files
    # of /tmp/.X11-unix: under WSLg that folder is read-only, and Xvfb is
    # reached by its abstract socket alone. Emulators that start together take turns (a lock), or two would
    # choose the same one.
    exec 8> /tmp/.djsemu-xvfb.lock
    flock 8
    listening() { grep -q "@/tmp/.X11-unix/X$1\$" /proc/net/unix || [ -e "/tmp/.X11-unix/X$1" ]; }
    n=77
    while listening "$n"; do n=$((n + 1)); done
    Xvfb ":$n" -screen 0 1024x768x24 -nolisten tcp > "$DJS/run/xvfb.log" 2>&1 &
    XVFB_PID=$!
    for _ in $(seq 1 50); do listening "$n" && break; sleep 0.1; done
    if listening "$n" && kill -0 "$XVFB_PID" 2> /dev/null; then
        # The app opens ":0.0" whatever DISPLAY says: the shim takes that
        # connection to this display.
        XDISPLAY="-E DJSDEV_XDISPLAY=$n"
    else
        kill "$XVFB_PID" 2> /dev/null
        echo "Xvfb did not start (see $DJS/run/xvfb.log): using the display ${DISPLAY:-:0}" >&2
        XVFB_PID=
    fi
    flock -u 8
fi
WATCH_PID=
trap 'for p in $XVFB_PID $WATCH_PID; do kill "$p" 2> /dev/null; done' EXIT

# A stick's autoexec.bin. The unit opens it with its key through a loop
# device and mounts what it holds on /mnt/iso (decrypt_autoexec.sh). That
# needs root, so it is opened here, once, and init.sh runs its autoexec.sh as
# the unit would. It must hold an ISO 9660 file system, and a changed
# autoexec.bin is seen at the next start.
AUTO="$DJS/run/autoexec"
rm -rf "$AUTO" "$DJS/run/autoexec.iso"
mkdir -p "$AUTO" "$ROOT/mnt/iso"
if [ -f "$USB/autoexec.bin" ]; then
    if python3 "$REPO/tools/decrypt_upd.py" --raw "$USB/autoexec.bin" "$DJS/run/autoexec.iso" > /dev/null &&
        7z x -y -o"$AUTO" "$DJS/run/autoexec.iso" > /dev/null; then
        # As Linux shows a plain ISO 9660 disc: lower-case names, no ".1",
        # every file executable.
        for f in "$AUTO"/*; do
            n=$(basename "$f" | tr 'A-Z' 'a-z')
            n=${n%;1}
            [ "$f" = "$AUTO/$n" ] || mv "$f" "$AUTO/$n"
        done
        chmod -R u+rwx "$AUTO"
        echo "[djsemu] autoexec.bin on the USB drive: $(ls "$AUTO" | tr '\n' ' ')"
    else
        echo "[djsemu] autoexec.bin on the USB drive could not be opened (key? not ISO 9660?): ignored" >&2
        rm -rf "$AUTO"; mkdir -p "$AUTO"
    fi
    rm -f "$DJS/run/autoexec.iso"
fi

# What runs inside: init.sh, which stands in for the unit's start-up (the
# stick's autoexec, then the app), with a pidof and a killall that find the
# unit's programs under qemu. With extra qemu arguments (gdb), the app alone.
mkdir -p "$ROOT/opt/djsemu/bin"
install -m 755 "$REPO/scripts/guest/init.sh" "$ROOT/opt/djsemu/init.sh"
install -m 755 "$REPO/scripts/guest/pidof" "$ROOT/opt/djsemu/bin/pidof"
install -m 755 "$REPO/scripts/guest/pidof" "$ROOT/opt/djsemu/bin/killall"
kill $(pids_of /opt/djsemu/init.sh) 2> /dev/null    # one left by a stopped emulator
if [ $# -eq 0 ]; then
    set -- /bin/sh /opt/djsemu/init.sh
    QARGS=
    # The emulator ends when the app has: none seen for 25 seconds, once
    # one has been (an autoexec may stop the app to start it again, which
    # on a cold or busy machine takes more than the five seconds it took
    # once: the emulator was then ended in the middle of the restart).
    (
        seen=0
        gone=0
        while [ "$gone" -lt 25 ]; do
            sleep 1
            if [ -n "$(pids_of /root/pdj/EP113_Main_R)" ]; then
                seen=1
                gone=0
            elif [ "$seen" = 1 ]; then
                gone=$((gone + 1))
            fi
        done
        kill $(pids_of /opt/djsemu/init.sh) 2> /dev/null
    ) &
    WATCH_PID=$!
else
    QARGS="$*"
    set -- /root/pdj/EP113_Main_R
fi

QENV="${TAG:+-E DJSDEV_TAG=$TAG }-E DISPLAY=${DISPLAY:-:0} -E HOME=/root -E PATH=/opt/djsemu/bin:/usr/bin:/bin:/usr/sbin:/sbin"
QENV="$QENV -E LD_LIBRARY_PATH=/usr/lib:/lib -E LD_PRELOAD=/opt/djsemu/libdjsdev.so $XDISPLAY"
[ -n "${DJSDEV_USB:-}" ] && QENV="$QENV -E DJSDEV_USB=$DJSDEV_USB"
[ -n "${DJSDEV_DIRECT:-}" ] && QENV="$QENV -E DJSDEV_DIRECT=$DJSDEV_DIRECT"
# The unit's console (its serial port), where a process started by a stick's
# autoexec may send its output: a file here, $DJS_HOME/run/console.log.
: > "$DJS/run/console.log"
if [ -z "${DJS_PROOT:-}" ] && unshare -rm true 2> /dev/null; then
    # Without proot: a chroot in a user namespace of our own (no root needed), unless DJS_PROOT is set or user
    # namespaces are not allowed. proot stops the guest at every system call and the app makes very many: the app is
    # ready in 17 s here, against 45 s. The same places are bound. The
    # processes of the guest under qemu are the kernel's (binfmt_misc), and carry the tag in their environment.
    export ROOT USB DATA AUTO EMMC QENV QARGS DJS DJSDEV_TAG="${TAG:-}"
    mkdir -p "$ROOT/tmp/.X11-unix" "$ROOT/dev" "$ROOT/proc" "$ROOT/sys" "$ROOT/media/usb1/sda1" "$ROOT/root/data" "$ROOT/mnt/iso"
    install -m 755 "$(command -v qemu-arm-static)" "$ROOT/usr/bin/qemu-arm-static"
    timeout "$secs" unshare -rm bash -c '
        mount --rbind /dev "$ROOT/dev" && mount --bind "$DJS/run/console.log" "$ROOT/dev/console" &&
        mount --rbind /proc "$ROOT/proc" && mount --rbind /sys "$ROOT/sys" &&
        mount --rbind /tmp/.X11-unix "$ROOT/tmp/.X11-unix" && mount --bind "$USB" "$ROOT/media/usb1/sda1" &&
        mount --bind "$DATA" "$ROOT/root/data" && mount --bind "$AUTO" "$ROOT/mnt/iso" &&
        { [ -z "$EMMC" ] || mount --bind "$EMMC" "$ROOT/mnt/emmc"; } || exit 1
        exec chroot "$ROOT" /bin/sh -c '"'"'cd /root/pdj && exec /usr/bin/qemu-arm-static $QENV $QARGS "$@"'"'"' sh "$@"
    ' sh "$@"
else
timeout "$secs" proot -q "qemu-arm-static $QENV $QARGS" -r "$ROOT" \
    -b /dev -b "$DJS/run/console.log:/dev/console" -b /proc -b /sys -b /tmp/.X11-unix \
    -b "$USB:/media/usb1/sda1" -b "$DATA:/root/data" -b "$AUTO:/mnt/iso" ${EMMC:+-b "$EMMC:/mnt/emmc"} -w /root/pdj "$@"
fi
