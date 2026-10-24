"""Install the dependencies of every add-on in the Kodi add-ons folder.

Reads each addon.xml, resolves <import addon="..."> entries recursively against
the official Kodi repository and unpacks missing add-ons. Add-ons that ship with
Kodi (xbmc.*, kodi.*, everything in the system add-ons folder) are skipped.
"""
import gzip
import io
import os
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

REPO = os.environ.get('KODI_REPO_URL', 'https://mirrors.kodi.tv/addons/omega').rstrip('/')
SYSTEM_ADDONS = '/usr/share/kodi/addons'
INDEX_MAX_AGE = 24 * 3600


def read_addon_xml(path):
    try:
        return ET.parse(path).getroot()
    except (OSError, ET.ParseError):
        return None


def imports(root):
    for imp in root.iter('import'):
        if imp.get('optional') != 'true':
            yield imp.get('addon')


def load_index(cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    cached = os.path.join(cache_dir, 'addons.xml')
    if not os.path.exists(cached) or time.time() - os.path.getmtime(cached) > INDEX_MAX_AGE:
        data = urllib.request.urlopen(REPO + '/addons.xml.gz', timeout=30).read()
        with open(cached, 'wb') as f:
            f.write(gzip.decompress(data))
    return {a.get('id'): a for a in ET.parse(cached).getroot().findall('addon')}


def is_builtin(addon_id):
    return (addon_id.startswith(('xbmc.', 'kodi.'))
            or os.path.isdir(os.path.join(SYSTEM_ADDONS, addon_id)))


def main(addons_dir):
    cache_dir = os.path.join(addons_dir, '..', 'kodi-dev-cache')
    installed = {name for name in os.listdir(addons_dir)
                 if os.path.exists(os.path.join(addons_dir, name, 'addon.xml'))}

    pending = []
    for name in sorted(installed):
        root = read_addon_xml(os.path.join(addons_dir, name, 'addon.xml'))
        if root is None:
            print('kodi-dev: cannot read {}/addon.xml'.format(name), file=sys.stderr)
            continue
        pending.extend(imports(root))

    index = None
    while pending:
        addon_id = pending.pop()
        if addon_id in installed or is_builtin(addon_id):
            continue
        if index is None:
            index = load_index(cache_dir)
        entry = index.get(addon_id)
        if entry is None:
            print('kodi-dev: {} not found in {}'.format(addon_id, REPO), file=sys.stderr)
            continue
        version = entry.get('version')
        url = '{0}/{1}/{1}-{2}.zip'.format(REPO, addon_id, version)
        print('kodi-dev: installing {} {}'.format(addon_id, version))
        data = urllib.request.urlopen(url, timeout=60).read()
        zipfile.ZipFile(io.BytesIO(data)).extractall(addons_dir)
        installed.add(addon_id)
        pending.extend(imports(entry))


if __name__ == '__main__':
    main(sys.argv[1])
