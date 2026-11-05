"""Unit tests for kdev's pure helpers: python3 -m unittest discover tests"""
import importlib.machinery
import importlib.util
import os
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
loader = importlib.machinery.SourceFileLoader('kdev', os.path.join(ROOT, 'kdev'))
spec = importlib.util.spec_from_loader('kdev', loader)
kdev = importlib.util.module_from_spec(spec)
loader.exec_module(kdev)


class PoolName(unittest.TestCase):
    def test_default_pool(self):
        for value in (None, '', '1'):  # KDEV_POOL=1: "on the pool", as the skin's tests set it
            self.assertEqual(kdev.pool_name(value), 'pool')

    def test_named_pool(self):
        self.assertEqual(kdev.pool_name('e2e'), 'e2e')

    def test_a_name_must_make_valid_instance_names(self):
        for value in ('E2E', 'a b', '-x', 'x' * 29):
            with self.assertRaises(SystemExit):
                kdev.pool_name(value)


class PoolLock(unittest.TestCase):
    def test_free_without_a_lock_file(self):
        with mock.patch.object(kdev, 'INSTANCES', '/nonexistent'):
            self.assertEqual(kdev.pool_in_use(), '')

    def test_held_while_a_run_has_the_flock(self):
        import fcntl
        import tempfile
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(kdev, 'INSTANCES', folder):
            os.makedirs(os.path.join(folder, kdev.POOL))
            path = kdev.pool_lock_file()
            with open(path, 'w') as held:
                held.write('pid 42 since 01:00')
                held.flush()
                fcntl.flock(held, fcntl.LOCK_EX)
                self.assertEqual(kdev.pool_in_use(), 'pid 42 since 01:00')
                with self.assertRaises(SystemExit):
                    kdev.pool_free_or_die('up')
            self.assertEqual(kdev.pool_in_use(), '')


class PoolSize(unittest.TestCase):
    def size(self, available, cores=14, **kw):
        return kdev.pool_size(available, cores, **kw)[0]

    def test_memory_bound(self):
        # 5.5 GB available: (5.5 - 1.5 reserve) / 1.0 per worker (Kodi, Jellyfin, fault proxy) = 4
        self.assertEqual(self.size(5.5), 4)

    def test_cores_bound(self):
        self.assertEqual(self.size(20, cores=6), 3)

    def test_maximum(self):
        self.assertEqual(self.size(64, cores=64), 8)

    def test_at_least_one(self):
        self.assertEqual(self.size(0.5), 1)
        self.assertEqual(self.size(4, cores=1), 1)

    def test_running_pool_counts_as_available(self):
        # A running pool already took its memory: 2.5 GB left + 3 workers
        self.assertEqual(self.size(2.5, running=3), 4)

    def test_explains_the_calculation(self):
        n, text = kdev.pool_size(5.5, 14)
        for part in ('5.5', '1.5', '1.0', '= 4', '7', '8', 'N = 4'):
            self.assertIn(part, text)


class WorkerCompose(unittest.TestCase):
    def test_default_setup_needs_no_file(self):
        self.assertIsNone(kdev.worker_compose([]))

    def test_mounts_the_addons_in_kodi_only(self):
        text = kdev.worker_compose(['/w/skin:/home/kodi/.kodi/addons/skin.x'])
        self.assertIn('  kodi:\n    volumes:\n      - /w/skin:/home/kodi/.kodi/addons/skin.x\n', text)
        # every worker has its own Jellyfin: no shared network, no service switched off
        for word in ('networks', 'profiles', 'jellyfin'):
            self.assertNotIn(word, text)

    def test_cpus_limit_the_kodi(self):
        text = kdev.worker_compose(['/a:/home/kodi/.kodi/addons/a'], cpus=1.5)
        self.assertIn('    cpus: 1.5\n    volumes:', text)
        self.assertIn('    cpus: 2\n', kdev.worker_compose([], cpus=2))
        self.assertIsNone(kdev.worker_compose([], cpus=None))


class Restart(unittest.TestCase):
    """The entrypoint starts a new Kodi as soon as the old one quits: restart waits for the
    old process only and never kills the new one."""

    def restart(self, pids):
        calls = []
        with mock.patch.object(kdev, 'compose', return_value='kodi\n'), \
                mock.patch.object(kdev, 'kodi_pids', side_effect=pids), \
                mock.patch.object(kdev, 'kodi_exec', side_effect=lambda *a, **k: calls.append(a)), \
                mock.patch.object(kdev, 'rpc'), mock.patch.object(kdev, 'wait_for'), \
                mock.patch.object(kdev.time, 'sleep'), mock.patch('builtins.print'):
            kdev.cmd_restart(None)
        return [c for c in calls if c[0] in ('kill', 'pkill')]

    def test_new_kodi_up_at_once_is_left_alone(self):
        self.assertEqual(self.restart([{'100'}, {'200'}]), [])

    def test_old_kodi_that_hangs_is_killed(self):
        hanging = [{'100'}] * 30
        self.assertEqual(self.restart(hanging), [('kill', '-KILL', '100')])


class FreeSlot(unittest.TestCase):
    def test_first_unused(self):
        self.assertEqual(kdev.free_slot({1, 2}, set()), 3)

    def test_skips_slot_with_a_port_in_use(self):
        # Slot 1 is free here, but another checkout's instance holds its Jellyfin port
        self.assertEqual(kdev.free_slot(set(), {8106}), 2)
        self.assertEqual(kdev.free_slot(set(), {5901}), 2)

    def test_slot_ports(self):
        self.assertEqual(kdev.slot_ports(2), {'JELLYFIN_PORT': 8116, 'FAULTPROXY_PORT': 8117,
                                              'KODI_RPC_PORT': 8100, 'KODI_VNC_PORT': 5902})


class DockerPorts(unittest.TestCase):
    def test_parses_published_host_ports(self):
        lines = ['127.0.0.1:8117->8096/tcp', '', '127.0.0.1:5901->5900/tcp, 127.0.0.1:8090->8080/tcp',
                 '0.0.0.0:9000->9000/tcp, :::9000->9000/tcp', '8096/tcp']
        self.assertEqual(kdev.parse_docker_ports(lines), {8117, 5901, 8090, 9000})



class Builtin(unittest.TestCase):
    """A builtin goes to Kodi as a builtin to execute, not as a button action: Kodi drops actions
    while the topmost modal dialog plays its close animation."""

    def run_builtin(self, command):
        calls = []
        with mock.patch.object(kdev, 'kodi_exec', side_effect=lambda *a, **k: calls.append(a)):
            kdev.cmd_builtin(mock.Mock(command=command))
        return calls

    def test_sends_an_execbuiltin_packet(self):
        (call,) = self.run_builtin('SetFocus(9109)')
        self.assertNotIn('kodi-send', call)
        self.assertEqual(call[:2], ('python3', '-c'))
        self.assertIn('ACTION_EXECBUILTIN', call[2])
        self.assertEqual(call[3:], ('SetFocus(9109)',))


class MusicLibrary(unittest.TestCase):
    """The seeded music: what the skins' music tests need (several albums for a home row, an
    artist with two albums, albums with several tracks), each track tagged and with a cover."""

    def test_albums_for_a_home_row_and_an_artist_with_two(self):
        albums = [(artist, album) for artist, _, _, albums in kdev.MUSIC for album, _, _ in albums]
        self.assertGreaterEqual(len(albums), 7)
        self.assertTrue(any(len(albums) > 1 for _, _, _, albums in kdev.MUSIC))
        self.assertTrue(any(len(tracks) >= 5 for _, _, _, albums in kdev.MUSIC for _, _, tracks in albums))

    def test_tracks_are_tagged_in_folders_by_artist_and_album(self):
        tracks = kdev.music_tracks()
        first = tracks[0]
        self.assertEqual(first['path'], 'Neon Drift/Afterglow Avenue/01 - Midnight Grid.mp3')
        self.assertEqual(first['tags'], {'title': 'Midnight Grid', 'artist': 'Neon Drift',
                                         'album_artist': 'Neon Drift', 'album': 'Afterglow Avenue',
                                         'track': '1/5', 'date': '2019', 'genre': 'Synthwave'})
        self.assertEqual(len({t['path'] for t in tracks}), len(tracks))
        self.assertEqual(len({t['frequency'] for t in tracks}), len(tracks))  # a tone of its own

    def test_cover_per_album_and_pictures_per_artist(self):
        images = {i['path']: i for i in kdev.music_images()}
        for artist, _, _, albums in kdev.MUSIC:
            self.assertIn(artist + '/folder.jpg', images)
            self.assertIn(artist + '/backdrop.jpg', images)
            for album, _, _ in albums:
                self.assertEqual(images['{}/{}/cover.jpg'.format(artist, album)]['text'], album)

    def test_commands_only_for_missing_files(self):
        tracks, images = kdev.music_tracks(), kdev.music_images()
        done = {'music/' + t['path'] for t in tracks[1:]} | {'music/' + i['path'] for i in images[1:]}
        commands = kdev.music_commands('/out', lambda rel: rel in done)
        self.assertEqual(len(commands), 2)
        track, image = commands
        self.assertEqual(track[-1], '/out/music/' + tracks[0]['path'])
        self.assertIn('album=Afterglow Avenue', track)
        self.assertIn('track=1/5', track)
        self.assertIn(str(kdev.MUSIC_SECONDS), ' '.join(track))
        self.assertEqual(image[-1], '/out/music/' + images[0]['path'])
        self.assertIn('-frames:v', image)


class JellyfinProfile(unittest.TestCase):
    """profiles/plugin.video.jellyfin.py: no first start dialogs, kdev syncs the libraries."""

    profile = kdev.load_profile('plugin.video.jellyfin')

    def test_libraries_to_sync_skips_synced_ones(self):
        sync = {'Whitelist': ['m1', 'Mixed:x2'], 'Libraries': []}
        libraries = {'Movies': 'm1', 'Mixed': 'x2', 'Music': 'u3', 'Shows': 's4'}
        self.assertEqual(self.profile.libraries_to_sync(sync, libraries), ['u3', 's4'])

    def test_nothing_synced_yet(self):
        self.assertEqual(self.profile.libraries_to_sync({}, {'Music': 'u3'}), ['u3'])

    def test_one_sync_for_all_libraries(self):
        # Kodi splits builtin parameters at commas: the id list goes URL encoded
        self.assertEqual(self.profile.sync_command(['u3', 's4']),
                         'RunPlugin(plugin://plugin.video.jellyfin/?mode=synclib&id=u3%2Cs4)')

    def test_sync_done_once_whitelisted_and_nothing_left(self):
        done = self.profile.sync_done
        self.assertTrue(done({'Whitelist': ['u3', 's4'], 'Libraries': []}, ['u3', 's4']))
        self.assertFalse(done({'Whitelist': ['u3', 's4'], 'Libraries': ['s4']}, ['u3', 's4']))
        self.assertFalse(done({'Whitelist': ['u3'], 'Libraries': []}, ['u3', 's4']))


if __name__ == '__main__':
    unittest.main()
