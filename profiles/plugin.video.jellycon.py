"""kodi-dev profile for JellyCon: log the add-on in as the Jellyfin test user
(tester unless KDEV_USER says otherwise).

Writes the add-on settings (server, user, debug logging) and the auth.json that
JellyCon reads its token from; kdev runs it while Kodi is stopped. The token is requested with
the same DeviceId JellyCon itself sends, so the server sees one consistent device.
"""
import hashlib
import json
import os
import uuid

ADDON_ID = 'plugin.video.jellycon'

SETTINGS = {
    'server_address': None,  # filled from seed data
    'username': None,  # the instance's user
    'save_user_to_settings': 'true',
    'verify_cert': 'false',
    'log_debug': 'true',
}


def seed(kdev, seed_data, args):
    user_name = kdev.kodi_user()
    temp = os.path.join(kdev.KODI_HOME, 'temp')
    addon_data = os.path.join(kdev.KODI_HOME, 'userdata', 'addon_data', ADDON_ID)
    os.makedirs(temp, exist_ok=True)
    os.makedirs(addon_data, exist_ok=True)

    guid_path = os.path.join(temp, 'jellycon_guid')
    if not os.path.exists(guid_path) or not open(guid_path).read().strip():
        with open(guid_path, 'w') as f:
            f.write(uuid.uuid4().hex)
    client_id = open(guid_path).read().strip()
    device_id = '{}-{}'.format(client_id, hashlib.md5(user_name.encode()).hexdigest())

    user = seed_data['users'][user_name]
    auth = 'MediaBrowser Client="Kodi JellyCon", Device="JellyCon", DeviceId="{}", Version="kodi-dev"'.format(device_id)
    login = kdev.jf_ok('POST', '/Users/AuthenticateByName',
                       {'Username': user_name, 'Pw': user['password']}, auth=auth)

    with open(os.path.join(addon_data, 'auth.json'), 'w') as f:
        json.dump({user_name: {'user_id': login['User']['Id'], 'token': login['AccessToken']}}, f, indent=4)

    server = seed_data['server']['internal']
    # Marks the "first connection, run a speed test?" dialog as answered
    values = dict(SETTINGS, server_address=server, username=user_name, server_speed_check_data=server + '-skipped')
    lines = ['<settings version="2">']
    lines += ['    <setting id="{}">{}</setting>'.format(k, v) for k, v in values.items()]
    lines.append('</settings>')
    with open(os.path.join(addon_data, 'settings.xml'), 'w') as f:
        f.write('\n'.join(lines) + '\n')

    print('kdev: JellyCon logged in as {} against {}'.format(user_name, values['server_address']))
