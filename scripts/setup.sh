#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-or-later
#
# From a DJS-1000 update file to the root filesystem its application runs in.
#
#   scripts/setup.sh [--rebuild] <DJS1000.UPD> [aes256.key]
#
# Decrypts the update, unpacks it, and assembles the unit's root filesystem
# in $DJS_HOME (default ~/djs), which must be on a Linux filesystem: the
# archives hold symlinks, device nodes and case-sensitive names. Nothing from
# the update is written into this repository.
#
# The key file is the unit's own /usr/local/pdj/aes256.key, from a unit you
# own: it is not part of this project. A copy is kept as $DJS_HOME/aes256.key
# (readable by you alone), where the tools look for it. With one already
# there the second argument can be left out.
#
# Needs (Ubuntu 24.04): qemu-user-static binfmt-support squashfs-tools
# p7zip-full gcc-arm-linux-gnueabihf openssl python3. And xvfb, to run the
# app without its own window (scripts/run.sh does without it if it is not
# there).
set -eu
REPO="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")"
DJS="${DJS_HOME:-$HOME/djs}"
REBUILD=0
if [ "${1:-}" = --rebuild ]; then
    REBUILD=1
    shift
fi
UPD="${1:?usage: setup.sh <DJS1000.UPD> <aes256.key>}"
KEY="${2:-$DJS/aes256.key}"
test -f "$KEY" || { echo "no key file: usage: setup.sh <DJS1000.UPD> <aes256.key>" >&2; exit 1; }

test -f "$UPD" || { echo "no update file: $UPD" >&2; exit 1; }

# Resolve before creating anything. Only a dedicated workspace is safe.
DJS="$(realpath -m "$DJS")"
case "$DJS" in
    / | /home | /root | /usr | /etc | /var | /opt | /tmp | /mnt | /media | "$HOME" | "$REPO")
        echo "unsafe DJS_HOME: $DJS (choose a dedicated emulator folder)" >&2; exit 1 ;;
esac
case "$HOME/" in "$DJS/"*) echo "DJS_HOME contains your home directory" >&2; exit 1 ;; esac
case "$REPO/" in "$DJS/"*) echo "DJS_HOME contains the repository" >&2; exit 1 ;; esac
if [ -d "$DJS" ] && [ -n "$(ls -A "$DJS")" ]; then
    if [ "$REBUILD" != 1 ]; then
        echo "$DJS is not empty. Use --rebuild to back up and replace its firmware files." >&2
        exit 1
    fi
    if [ ! -f "$DJS/.djs1000-emu" ] && [ ! -f "$DJS/root/root/pdj/EP113_Main_R" ]; then
        echo "$DJS is not a recognised installation. Choose an empty folder." >&2
        exit 1
    fi
fi

for t in qemu-arm-static unsquashfs 7z arm-linux-gnueabihf-gcc openssl python3; do
    command -v "$t" >/dev/null || { echo "missing: $t (see the package list at the top of this script)" >&2; exit 1; }
done
PARENT="$DJS"
while [ ! -d "$PARENT" ]; do PARENT="$(dirname "$PARENT")"; done
case "$(df -T "$PARENT" | awk 'NR==2 {print $2}')" in
    9p | drvfs | fuseblk | vfat | exfat | ntfs*)
        echo "$DJS is on a non-Linux filesystem. Set DJS_HOME to a Linux path" >&2; exit 1 ;;
esac

UPD="$(readlink -f "$UPD")"
KEY="$(readlink -f "$KEY")"
mkdir -p "$DJS"
mkdir "$DJS/.setup-lock" || { echo "another setup may be running in $DJS" >&2; exit 1; }
STAGE="$(mktemp -d "$DJS/.setup.XXXXXXXX")"
trap 'rmdir "$DJS/.setup-lock"; echo "Setup workspace: $STAGE"' EXIT
cd "$STAGE"
python3 "$REPO/tools/decrypt_upd.py" "$UPD" update.iso "$KEY"
7z x -y -oiso update.iso >/dev/null

# rootfs2-4 are the system, rootfs1 the unit tests. "Cannot mknod" for the
# device nodes is expected without root.
mkdir -p unpack root
for i in 1 2 3 4; do
    mkdir -p "unpack/tar$i"
    if ! LC_ALL=C tar xzf "iso/images/rootfs$i.tar.gz" -C "unpack/tar$i" 2>tar-errors; then
        # Only unprivileged device-node creation is expected to fail.
        if ! grep -q 'Cannot mknod: Operation not permitted' tar-errors ||
           grep -Ev 'Cannot mknod: Operation not permitted|Exiting with failure status due to previous errors' tar-errors; then
            cat tar-errors >&2
            exit 1
        fi
    fi
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

test -x root/root/pdj/EP113_Main_R || { echo "no EP113_Main_R in the update?" >&2; exit 1; }

# Only publish after extraction succeeds. Keep the old root, including settings.
BACKUP="$(mktemp -d "$DJS/previous.XXXXXXXX")"
for name in root iso update.iso; do
    if [ -e "$DJS/$name" ] || [ -L "$DJS/$name" ]; then
        mv -- "$DJS/$name" "$BACKUP/$name"
    fi
    mv -- "$STAGE/$name" "$DJS/$name"
done
if [ "$KEY" != "$(readlink -f "$DJS/aes256.key")" ]; then
    install -m 600 "$KEY" "$DJS/aes256.key"
fi
chmod 600 "$DJS/aes256.key"
touch "$DJS/.djs1000-emu"
echo "Previous files, if any: $BACKUP"
cd "$DJS"
# STAGE is an absolute mktemp directory under the verified workspace.
case "$STAGE" in "$DJS"/.setup.*) rm -rf -- "$STAGE" ;; *) exit 1 ;; esac
STAGE="complete"
echo "ready: $DJS/root ($(du -sh root | cut -f1)), firmware $(cat iso/images/release.txt 2>/dev/null)"
echo "run it: $REPO/scripts/run.sh 600"
