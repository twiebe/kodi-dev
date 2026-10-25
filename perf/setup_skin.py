#!/usr/bin/env python3
"""Install Arctic Fuse 3 with TMDb Helper and Skin Variables into kodi-dev.

    perf/setup_skin.py [--local DIR ...]

Copies the local checkouts given with --local (default: the three in
/workspaces) into data/kodi/addons, so they can be instrumented without
touching the checkouts, and downloads the add-ons they import from the
jurialmunkey repository (texturemaker, arctic resources, newer
jurialmunkey/infotagger modules). The rest comes from the Kodi Omega
repository through install_deps.py on the next Kodi start (`./kdev restart`).
"""
import argparse
import io
import os
import shutil
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS = os.path.join(ROOT, 'data', 'kodi', 'addons')
LOCAL = [
    '/workspaces/skin-arctic-fuse-3',
    '/workspaces/plugin-video-themoviedb-helper',
    '/workspaces/script-skinvariables',
]
JURIALMUNKEY = 'https://raw.githubusercontent.com/jurialmunkey/repository.jurialmunkey/master/{}/zips/'
REPOS = [JURIALMUNKEY.format('omega'), JURIALMUNKEY.format('repo')]
SYSTEM_ADDONS = '/usr/share/kodi/addons'  # inside the container; script.module.pil comes from there
BUILTIN = ('xbmc.', 'kodi.', 'script.module.pil')


def addon_xml(path):
    return ET.parse(os.path.join(path, 'addon.xml')).getroot()


def imports(root):
    for imp in root.iter('import'):
        if imp.get('optional') != 'true':
            yield imp.get('addon')


def load_indexes():
    indexes = []
    for repo in REPOS:
        data = urllib.request.urlopen(repo + 'addons.xml', timeout=30).read()
        indexes.append((repo, {a.get('id'): a for a in ET.fromstring(data).findall('addon')}))
    return indexes


def copy_local(path):
    addon_id = addon_xml(path).get('id')
    target = os.path.join(ADDONS, addon_id)
    if os.path.lexists(target):
        shutil.rmtree(target)
    shutil.copytree(path, target, ignore=shutil.ignore_patterns('.git', '__pycache__'))
    print('copied {} -> {}'.format(path, os.path.relpath(target, ROOT)))
    return addon_id


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', nargs='*', default=LOCAL)
    args = parser.parse_args()

    local_ids = [copy_local(path) for path in args.local]
    pending = [i for addon_id in local_ids for i in imports(addon_xml(os.path.join(ADDONS, addon_id)))]
    indexes = load_indexes()
    done = set(local_ids)
    while pending:
        addon_id = pending.pop()
        if addon_id in done or addon_id.startswith(BUILTIN):
            continue
        done.add(addon_id)
        for repo, index in indexes:
            entry = index.get(addon_id)
            if entry is not None:
                break
        else:
            continue  # left to install_deps.py (Kodi Omega repository)
        version = entry.get('version')
        target = os.path.join(ADDONS, addon_id)
        if os.path.exists(os.path.join(target, 'addon.xml')) and addon_xml(target).get('version') == version:
            print('{} {} already installed'.format(addon_id, version))
        else:
            if os.path.lexists(target):
                shutil.rmtree(target)
            url = '{0}{1}/{1}-{2}.zip'.format(repo, addon_id, version)
            zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())).extractall(ADDONS)
            print('installed {} {}'.format(addon_id, version))
        pending.extend(imports(entry))
    print('next: perf/install_hook.sh, ./kdev restart, then switch the skin to Arctic Fuse 3 (Settings > Interface > Skin)')


if __name__ == '__main__':
    sys.exit(main())
