# SPDX-License-Identifier: GPL-2.0-or-later
"""Requests to a user-selected Deckbench, including phone-pairing tokens."""
from urllib.parse import parse_qs, urlsplit, urlunsplit
from urllib.request import Request


def request(base, path, method='GET'):
    parts = urlsplit(base)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Deckbench needs an http:// or https:// URL without user credentials')
    token = (parse_qs(parts.fragment).get('token') or parse_qs(parts.query).get('token') or [''])[0]
    host = '127.0.0.1' if parts.hostname == 'localhost' else parts.hostname
    if ':' in host:
        host = '[' + host + ']'
    netloc = host + (':' + str(parts.port) if parts.port else '')
    url = urlunsplit((parts.scheme, netloc, parts.path.rstrip('/') + '/' + path.lstrip('/'), '', ''))
    return Request(url, method=method, headers={'Authorization': 'Bearer ' + token} if token else {})
