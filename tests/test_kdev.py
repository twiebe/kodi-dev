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


if __name__ == '__main__':
    unittest.main()
