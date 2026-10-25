"""Enable every add-on from the user add-ons folder once Kodi's JSON-RPC is up.

Kodi disables add-ons it finds on disk that were not installed through Kodi
itself. Mounted dev add-ons and their dependencies would stay disabled.

Add-on ids listed in temp/kodi-dev-keep-disabled (one per line) are left
alone, e.g. to keep the Jellyfin add-ons quiet during perf runs.
"""
import json
import os
import sys
import time
import urllib.request

URL = 'http://127.0.0.1:8080/jsonrpc'


def rpc(method, params=None):
    body = {'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}
    req = urllib.request.Request(URL, json.dumps(body).encode(),
                                 {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(req, timeout=10))


def main(addons_dir):
    addons_dir = os.path.realpath(addons_dir)
    for _ in range(120):
        try:
            rpc('JSONRPC.Ping')
            break
        except OSError:
            time.sleep(1)
    else:
        print('kodi-dev: JSON-RPC not reachable, add-ons not enabled', file=sys.stderr)
        return

    keep_disabled = os.path.join(os.path.dirname(addons_dir), 'temp', 'kodi-dev-keep-disabled')
    try:
        with open(keep_disabled) as f:
            skip = set(f.read().split())
    except OSError:
        skip = set()
    result = rpc('Addons.GetAddons', {'enabled': False, 'properties': ['path']})
    for addon in result.get('result', {}).get('addons', []):
        if addon['addonid'] in skip:
            print('kodi-dev: left {} disabled'.format(addon['addonid']))
        elif os.path.realpath(addon['path']).startswith(addons_dir + os.sep):
            rpc('Addons.SetAddonEnabled', {'addonid': addon['addonid'], 'enabled': True})
            print('kodi-dev: enabled {}'.format(addon['addonid']))
    # Marker for `kdev wait`: Kodi is up and dev add-ons are enabled
    open('/tmp/kodi-dev-ready', 'w').close()


if __name__ == '__main__':
    main(sys.argv[1])
