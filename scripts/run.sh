#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# Run the DJS-1000 app (EP113_Main_R) under qemu-arm user mode, in the rootfs
# scripts/setup.sh assembled in $DJS_HOME (default ~/djs), with the djsdev shim
# standing in for the board's devices. Its window opens on the X server at
# DISPLAY (:0, WSLg's, by default).
#
#   scripts/run.sh [seconds] [extra qemu-arm args, e.g. "-g 1234" for gdb]
#
# The shim is rebuilt from shim/djsdev.c on every run. The app's output goes
# to stdout/stderr; the panel command pipe is $DJS_HOME/root/tmp/djspanel.
set -u
REPO="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")"
DJS="${DJS_HOME:-$HOME/djs}"
ROOT=$DJS/root
secs=${1:-60}
shift || true

if pgrep -f 'qemu-arm-static.*EP113_Main_R' > /dev/null; then
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
CAL="$ROOT/root/data/PadCalibration.xml"
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
rm -f "$ROOT/tmp/djspanel" "$ROOT"/tmp/djsshot.*
arm-linux-gnueabihf-gcc -O2 -fPIC -shared -nostdlib -mfloat-abi=softfp -marm \
    -o "$ROOT/opt/djsemu/libdjsdev.so" "$REPO/shim/djsdev.c" \
    "$ROOT/lib/libdl.so.2" "$ROOT/lib/libc.so.6" "$ROOT/lib/libpthread.so.0" || exit 1

# The guest environment goes through qemu's -E, not a guest `env`, so that a
# gdb attached with -g debugs the app itself rather than env.
cd "$DJS"
QENV="-E DISPLAY=${DISPLAY:-:0} -E HOME=/root -E PATH=/usr/bin:/bin:/usr/sbin:/sbin"
QENV="$QENV -E LD_LIBRARY_PATH=/usr/lib:/lib -E LD_PRELOAD=/opt/djsemu/libdjsdev.so"
exec timeout "$secs" proot -q "qemu-arm-static $QENV $*" -r "$ROOT" \
    -b /dev -b /proc -b /sys -b /tmp/.X11-unix -b "$USB:/media/usb1/sda1" -w /root/pdj \
    /root/pdj/EP113_Main_R
