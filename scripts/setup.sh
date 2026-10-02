#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# From a DJS-1000 update file to the root filesystem its application runs in.
#
#   scripts/setup.sh <DJS1000.UPD>
#
# Decrypts the update, unpacks it, and assembles the unit's root filesystem
# in $DJS_HOME (default ~/djs), which must be on a Linux filesystem: the
# archives hold symlinks, device nodes and case-sensitive names. Nothing from
# the update is written into this repository.
#
# Needs (Ubuntu 24.04): qemu-user-static binfmt-support proot squashfs-tools
# p7zip-full gcc-arm-linux-gnueabihf openssl python3; and xvfb, to run the
# app without its own window (scripts/run.sh does without it if it is not
# there).
set -eu
REPO="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")"
DJS="${DJS_HOME:-$HOME/djs}"
UPD="${1:?usage: setup.sh <DJS1000.UPD>}"

for t in qemu-arm-static proot unsquashfs 7z arm-linux-gnueabihf-gcc openssl python3; do
    command -v "$t" >/dev/null || { echo "missing: $t (see the package list at the top of this script)" >&2; exit 1; }
done
case "$(df -T "$(dirname "$DJS")" | awk 'NR==2 {print $2}')" in
    9p | drvfs | fuseblk | vfat | exfat | ntfs*)
        echo "$DJS is on a Windows filesystem; set DJS_HOME to a Linux path" >&2; exit 1 ;;
esac

mkdir -p "$DJS"
cd "$DJS"
python3 "$REPO/tools/decrypt_upd.py" "$UPD" update.iso
rm -rf iso root unpack
7z x -y -oiso update.iso >/dev/null

# rootfs2-4 are the system, rootfs1 the unit tests; "Cannot mknod" for the
# device nodes is expected without root.
mkdir -p unpack root
for i in 1 2 3 4; do
    mkdir -p "unpack/tar$i"
    tar xzf "iso/images/rootfs$i.tar.gz" -C "unpack/tar$i" 2>/dev/null || true
done
for t in tar2 tar3 tar4 tar1; do cp -a "unpack/$t/." root/; done

# The SquashFS images, at the mount points their contents imply.
mkdir -p root/usr/bin root/usr/lib root/usr/share root/root
for s in bin lib share; do
    unsquashfs -q -f -d "unpack/sfs_$s" "iso/images/$s.sfs" >/dev/null
    cp -a "unpack/sfs_$s/." "root/usr/$s/"
done

# The application, /root/pdj.
tar xzf iso/images/pdj.tar.gz -C root/root
rm -rf unpack

test -x root/root/pdj/EP113_Main_R || { echo "no EP113_Main_R in the update?" >&2; exit 1; }
echo "ready: $DJS/root ($(du -sh root | cut -f1)), firmware $(cat iso/images/release.txt 2>/dev/null)"
echo "run it: $REPO/scripts/run.sh 600"
