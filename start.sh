#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
# Starts the emulator and the virtual deck: see start.py.
exec python3 "$(dirname "$0")/start.py" "$@"
