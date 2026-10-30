"""kodi-dev profile for Jellyfin for Kodi: sign the add-on in as the Jellyfin test
user (tester unless KDEV_USER says otherwise) and sync the seeded libraries.

seed() writes data.json (server, user, token) and the server and user settings,
and marks the first start as done, so the add-on asks nothing (no library
choice, no question about the Kodi Sync Queue plugin kodi-dev does not have,
add-on paths: Kodi plays through Jellyfin and needs no access to the media).
Other settings and the synced library stay as they are, an interrupted sync is
dropped. kdev runs it while Kodi is stopped. The token is requested with the
DeviceId the add-on itself sends (its jellyfin_guid file).

started() runs once Kodi is up again: it syncs the seeded libraries (Movies,
Shows, Music) the add-on does not sync yet into Kodi's library, the way
"Add libraries" in the add-on does, and waits until that is done.
"""
import json
import os
import re
import time
import urllib.parse
import uuid

ADDON_ID = 'plugin.video.jellyfin'


def set_setting(text, key, value):
    line = '    <setting id="{}">{}</setting>'.format(key, value)
    pattern = r'[ \t]*<setting id="{}"[^>]*?(/>|>[^<]*</setting>)'.format(re.escape(key))
    if re.search(pattern, text):
        return re.sub(pattern, lambda m: line, text, count=1)
    return text.replace('</settings>', line + '\n</settings>')


def seed(kdev, seed_data, args):
    user_name = kdev.kodi_user()
    addon_data = os.path.join(kdev.KODI_HOME, 'userdata', 'addon_data', ADDON_ID)
    os.makedirs(addon_data, exist_ok=True)

    guid_path = os.path.join(addon_data, 'jellyfin_guid')
    if not os.path.exists(guid_path) or not open(guid_path).read().strip():
        with open(guid_path, 'w') as f:
            f.write(str(uuid.uuid4()))
    device_id = open(guid_path).read().strip()

    user = seed_data['users'][user_name]
    auth = 'MediaBrowser Client="Kodi", Device="Kodi", DeviceId="{}", Version="kodi-dev"'.format(device_id)
    login = kdev.jf_ok('POST', '/Users/AuthenticateByName',
                       {'Username': user_name, 'Pw': user['password']}, auth=auth)
    server = kdev.jf_ok('GET', '/System/Info/Public')
    address = seed_data['server']['internal']
    with open(os.path.join(addon_data, 'data.json'), 'w') as f:
        json.dump({'Servers': [{
            'AccessToken': login['AccessToken'],
            'DateLastAccessed': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'Id': server['Id'],
            'Name': server['ServerName'],
            'UserId': login['User']['Id'],
            'Users': [{'Id': login['User']['Id'], 'IsSignedInOffline': True}],
            'address': address,
        }]}, f, indent=4)

    settings_path = os.path.join(addon_data, 'settings.xml')
    text = open(settings_path).read() if os.path.exists(settings_path) else '<settings version="2">\n</settings>\n'
    for key, value in (('username', user_name), ('serverName', server['ServerName']), ('server', address),
                       ('SyncInstallRunDone', 'true'), ('kodiCompanion', 'false'), ('enableMusic', 'true'),
                       ('useDirectPaths', '0')):
        text = set_setting(text, key, value)
    with open(settings_path, 'w') as f:
        f.write(text)

    # An interrupted sync would ask "Resume the previous sync?" on start; started() syncs
    # what is not synced yet again
    sync = read_sync(kdev)
    if sync.get('Libraries') or sync.get('RestorePoint'):
        sync.update(Libraries=[], RestorePoint={})
        with open(sync_path(kdev), 'w') as f:
            json.dump(sync, f, indent=4)
    print('kdev: Jellyfin for Kodi signed in as {} against {}'.format(user_name, address))


def libraries_to_sync(sync, libraries):
    """Ids of LIBRARIES ({name: id}) not in the add-on's sync state SYNC (sync.json) yet."""
    synced = {library.split(':')[-1] for library in sync.get('Whitelist', [])}
    return [library_id for library_id in libraries.values() if library_id not in synced]


def sync_command(library_ids):
    # Kodi splits builtin parameters at commas
    query = urllib.parse.urlencode({'mode': 'synclib', 'id': ','.join(library_ids)})
    return 'RunPlugin(plugin://{}/?{})'.format(ADDON_ID, query)


def sync_done(sync, library_ids):
    return set(library_ids) <= set(sync.get('Whitelist', [])) and not sync.get('Libraries')


def sync_path(kdev):
    return os.path.join(kdev.KODI_HOME, 'userdata', 'addon_data', ADDON_ID, 'sync.json')


def read_sync(kdev):
    try:
        return json.load(open(sync_path(kdev)))
    except (OSError, ValueError):
        return {}


def started(kdev, seed_data, args):
    missing = libraries_to_sync(read_sync(kdev), seed_data.get('libraries', {}))
    if not missing:
        return
    # the add-on takes sync requests once its library thread has started
    startup = 'Window(Home).Property(jellyfin_startup)'
    kdev.wait_for(lambda: kdev.rpc('XBMC.GetInfoLabels', {'labels': [startup]})[startup] == 'true',
                  120, 'Jellyfin for Kodi to start')
    print('kdev: Jellyfin for Kodi syncs {} libraries into Kodi'.format(len(missing)))
    kdev.builtin(sync_command(missing))
    kdev.wait_for(lambda: sync_done(read_sync(kdev), missing), 600, 'the library sync of Jellyfin for Kodi')
    print('kdev: library sync done')
