#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Read Linux/WSL adapters and save an explicit restart-only selection."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


# What run.sh passes to the shim (shim/network.h), from the fields of the chosen row. Every name is always given, empty
# when nothing is chosen, so a value left in the caller's environment cannot leak in.
KEYS = {'DJSDEV_INTERFACE': 'interface', 'DJSDEV_ADDRESS': 'address', 'DJSDEV_NETMASK': 'netmask',
        'DJSDEV_BROADCAST': 'broadcast', 'DJSDEV_IFINDEX': 'index'}


def interfaces():
    result = subprocess.run(['ip', '-j', '-4', 'address', 'show'], capture_output=True,
                            text=True, timeout=10, check=True)
    rows = []
    for item in json.loads(result.stdout):
        name = item['ifname']
        if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,15}', name) or 'UP' not in item.get('flags', []):
            continue
        for address in item.get('addr_info', []):
            if address.get('family') != 'inet':
                continue
            ip = ipaddress.IPv4Interface('%s/%s' % (address['local'], address['prefixlen']))
            if ip.ip.is_loopback or ip.ip.is_unspecified or ip.ip.is_multicast:
                continue
            rows.append({'interface': name, 'address': str(ip.ip), 'prefix': ip.network.prefixlen,
                         'netmask': str(ip.netmask), 'broadcast': str(ip.network.broadcast_address),
                         'index': int(item['ifindex']), 'mac': item.get('address', '')})
    return rows


def read(home):
    try:
        data = json.loads((home / 'network.json').read_text())
    except FileNotFoundError:
        return {'interface': '', 'address': ''}
    if not isinstance(data, dict) or not isinstance(data.get('interface'), str) or not isinstance(data.get('address'), str):
        raise ValueError('Invalid saved network selection')
    return data


def resolve(selection, rows):
    if not selection['interface']:
        return {}
    found = [row for row in rows if row['interface'] == selection['interface'] and row['address'] == selection['address']]
    if len(found) != 1:
        raise ValueError('The selected backend adapter/address is unavailable. Open the network picker or use --network default')
    return found[0]


def save(home, interface, address):
    selection = {'interface': interface, 'address': address}
    if interface:
        resolve(selection, interfaces())
    home.mkdir(parents=True, exist_ok=True)
    fd, path = tempfile.mkstemp(prefix='network-', dir=home)
    try:
        with os.fdopen(fd, 'w') as target:
            json.dump(selection, target)
        os.replace(path, home / 'network.json')
    finally:
        if os.path.exists(path):
            os.unlink(path)
    return selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path(os.environ.get('DJS_HOME', Path.home() / 'djs')))
    parser.add_argument('action', choices=('list', 'select', 'environment', 'matches'))
    parser.add_argument('interface', nargs='?', default='')
    parser.add_argument('address', nargs='?', default='')
    args = parser.parse_args()
    try:
        selection = read(args.home) if args.action != 'select' else None
        if args.action == 'list':
            print(json.dumps({'interfaces': interfaces(), 'selected': selection}))
        elif args.action == 'select':
            print(json.dumps(save(args.home, args.interface, args.address)))
        else:
            chosen = resolve(selection, interfaces()) if selection['interface'] else {}
            environment = {key: str(chosen[field]) if chosen else '' for key, field in KEYS.items()}
            if args.action == 'matches':
                data = Path('/proc/%d/environ' % int(args.interface)).read_bytes().split(b'\0')
                current = dict(part.decode().split('=', 1) for part in data if b'=' in part and part.startswith(b'DJSDEV_'))
                print(json.dumps(all(current.get(key, '') == value for key, value in environment.items())))
            else:
                print(json.dumps(environment))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, 'Network setup: %s\n' % error)


if __name__ == '__main__':
    main()
