"""tools/install-kodi-addons.sh against a fake Flatpak home: a stub flatpak, made-up add-on zips, an
add-on database with Kodi's table. No network and no Kodi: python3 -m unittest discover tests"""
import os
import pathlib
import sqlite3
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'install-kodi-addons.sh'
FLATPAK = """#!/bin/sh
case "$1" in
    run) echo "STARTED $2" ;;
    info) echo "     Version: 21.3" ;;
esac
exit 0
"""


def make_zip(folder, addon_id, version):
    path = folder / '{}-{}.zip'.format(addon_id, version)
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('{}/addon.xml'.format(addon_id), '<addon id="{}" version="{}"/>'.format(addon_id, version))
    return path


class InstallScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name)
        self.home, self.cwd, self.bin = base / 'home', base / 'zips', base / 'bin'
        self.data = self.home / '.var' / 'app' / 'tv.kodi.Kodi' / 'data'
        for folder in (self.cwd, self.bin, self.data / 'addons', self.data / 'userdata' / 'Database'):
            folder.mkdir(parents=True)
        (self.bin / 'flatpak').write_text(FLATPAK)
        (self.bin / 'flatpak').chmod(0o755)
        self.db = self.data / 'userdata' / 'Database' / 'Addons33.db'
        con = sqlite3.connect(self.db)
        con.execute('CREATE TABLE installed (id INTEGER PRIMARY KEY, addonID TEXT UNIQUE, enabled BOOLEAN, '
                    'installDate TEXT, lastUpdated TEXT, lastUsed TEXT, origin TEXT NOT NULL DEFAULT "", '
                    'disabledReason INTEGER NOT NULL DEFAULT 0)')
        con.execute("INSERT INTO installed(addonID, enabled, installDate, disabledReason) VALUES('skin.confuse', 0, 'x', 1)")
        con.commit()
        con.close()

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        env = dict(os.environ, HOME=str(self.home), PATH='{}:{}'.format(self.bin, os.environ['PATH']))
        return subprocess.run(['bash', str(SCRIPT), *args], cwd=self.cwd, env=env, capture_output=True, text=True)

    def setting(self, key):
        path = self.data / 'userdata' / 'guisettings.xml'
        if not path.exists():
            return None
        return next((s.text for s in ET.parse(path).getroot().iter('setting') if s.get('id') == key), None)

    def enabled(self):
        con = sqlite3.connect(self.db)
        try:
            return dict(con.execute('SELECT addonID, enabled FROM installed'))
        finally:
            con.close()

    def version(self, addon_id):
        return ET.parse(self.data / 'addons' / addon_id / 'addon.xml').getroot().get('version')

    def test_without_arguments_the_newest_zip_of_each_default_addon(self):
        old = make_zip(self.cwd, 'skin.nightcity', '0.1')
        make_zip(self.cwd, 'skin.nightcity', '0.2')
        os.utime(old, (0, 0))
        make_zip(self.cwd, 'skin.confuse', '1.0')
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.version('skin.nightcity'), '0.2')
        self.assertIn('STARTED tv.kodi.Kodi', result.stdout)
        self.assertEqual(self.enabled(), {'skin.confuse': 1, 'skin.nightcity': 1})

    def test_zips_given_install_only_those(self):
        make_zip(self.cwd, 'skin.nightcity', '0.1')
        given = make_zip(self.cwd, 'script.other', '2.0')
        result = self.run_script(given.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in (self.data / 'addons').iterdir()), ['script.other'])

    def test_skin_and_a_language_beyond_the_skin_fonts(self):
        make_zip(self.cwd, 'skin.confuse', '1.0')
        (self.data / 'addons' / 'resource.language.ja_jp').mkdir()
        (self.data / 'addons' / 'resource.language.ja_jp' / 'addon.xml').write_text('<addon/>')
        result = self.run_script('--skin', 'confuse', '--lang', 'ja')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.setting('lookandfeel.skin'), 'skin.confuse')
        self.assertEqual(self.setting('locale.language'), 'resource.language.ja_jp')
        self.assertEqual(self.setting('lookandfeel.font'), 'Arial')
        self.assertEqual(self.enabled()['resource.language.ja_jp'], 1)

    def test_a_latin_language_takes_the_default_fonts(self):
        make_zip(self.cwd, 'skin.confuse', '1.0')
        lang = make_zip(self.cwd, 'resource.language.de_de', '11.0')
        result = self.run_script('skin.confuse-1.0.zip', lang.name, '--lang=de_DE')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.setting('locale.language'), 'resource.language.de_de')
        self.assertEqual(self.setting('lookandfeel.font'), 'Default')

    def test_english_comes_with_kodi(self):
        make_zip(self.cwd, 'skin.confuse', '1.0')
        result = self.run_script('--lang', 'en')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.setting('locale.language'), 'resource.language.en_gb')

    def test_refusals_change_nothing(self):
        make_zip(self.cwd, 'skin.confuse', '1.0')
        for args in (['--lang', 'xyz1'], ['--skin', 'unknown'], ['missing.zip'], ['--skin']):
            result = self.run_script(*args)
            self.assertEqual(result.returncode, 1, args)
            self.assertIn('nothing was changed', result.stderr, args)
            self.assertNotIn('STARTED', result.stdout, args)
        self.assertFalse((self.data / 'addons' / 'skin.confuse').exists())
        self.assertIsNone(self.setting('lookandfeel.skin'))


if __name__ == '__main__':
    unittest.main()
