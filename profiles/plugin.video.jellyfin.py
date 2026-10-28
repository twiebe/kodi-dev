"""kodi-dev profile for Jellyfin for Kodi: sign the add-on in as the Jellyfin test
user (tester unless KDEV_USER says otherwise).

Writes data.json (server, user, token) and the server and user settings; other
settings, the synced library and the sync state stay as they are. Without a
library sync done before, the add-on asks for the libraries to sync on its next
start. kdev runs it while Kodi is stopped. The token is requested with the
DeviceId the add-on itself sends (its jellyfin_guid file).
"""
import json
import os
import re
import time
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
    for key, value in (('username', user_name), ('serverName', server['ServerName']), ('server', address)):
        text = set_setting(text, key, value)
    with open(settings_path, 'w') as f:
        f.write(text)
    print('kdev: Jellyfin for Kodi signed in as {} against {}'.format(user_name, address))
