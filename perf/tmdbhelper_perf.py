"""Timing hook for the TMDb Helper service, imported first in its service.py.

Wraps the Kodi API calls the service makes (info labels, conditions, window
properties) and logs per thread every INTERVAL seconds how often each was
called and how long the calls took. Each of these calls takes Kodi's GUI
lock, so their duration includes the wait for the render thread.

Also logs every focus change the service handles (on_finalise): how long it
took and how many window property calls it made.

Log lines start with "PERF " and are machine readable (key=value).
"""
import threading
import time

import xbmc
import xbmcgui

INTERVAL = 10

_lock = threading.Lock()
_stats = {}  # (thread name, api) -> [count, total seconds, max seconds]
_local = threading.local()


def _record(api, seconds):
    key = (threading.current_thread().name, api)
    with _lock:
        entry = _stats.setdefault(key, [0, 0.0, 0.0])
        entry[0] += 1
        entry[1] += seconds
        entry[2] = max(entry[2], seconds)
    if api.startswith('Window.') and api != 'Window.getProperty':
        _local.property_calls = getattr(_local, 'property_calls', 0) + 1


def _wrap(func, api):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            _record(api, time.perf_counter() - start)
    return wrapper


xbmc.getInfoLabel = _wrap(xbmc.getInfoLabel, 'xbmc.getInfoLabel')
_getCondVisibility = xbmc.getCondVisibility
_conditions = {}  # condition -> [count, total seconds]
_keys = {}  # (set|clear, property key) -> count


def getCondVisibility(condition):
    start = time.perf_counter()
    try:
        return _getCondVisibility(condition)
    finally:
        seconds = time.perf_counter() - start
        _record('xbmc.getCondVisibility', seconds)
        with _lock:
            entry = _conditions.setdefault(condition, [0, 0.0])
            entry[0] += 1
            entry[1] += seconds


xbmc.getCondVisibility = getCondVisibility
for _name in ('getCurrentWindowId', 'getCurrentWindowDialogId'):
    setattr(xbmcgui, _name, _wrap(getattr(xbmcgui, _name), 'xbmcgui.' + _name))

_Window = xbmcgui.Window


def _count_key(action, key):
    with _lock:
        _keys[(action, key)] = _keys.get((action, key), 0) + 1


class Window:
    """Stands in for xbmcgui.Window; times the property calls."""

    def __init__(self, *args, **kwargs):
        self._window = _Window(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._window, name)

    def setProperty(self, key, value):
        _count_key('set', key)
        start = time.perf_counter()
        try:
            return self._window.setProperty(key, value)
        finally:
            _record('Window.setProperty', time.perf_counter() - start)

    def clearProperty(self, key):
        _count_key('clear', key)
        start = time.perf_counter()
        try:
            return self._window.clearProperty(key)
        finally:
            _record('Window.clearProperty', time.perf_counter() - start)

    def getProperty(self, key):
        start = time.perf_counter()
        try:
            return self._window.getProperty(key)
        finally:
            _record('Window.getProperty', time.perf_counter() - start)


xbmcgui.Window = Window


def _report():
    monitor = xbmc.Monitor()
    while not monitor.waitForAbort(INTERVAL):
        with _lock:
            stats = dict(_stats)
            _stats.clear()
            conditions = dict(_conditions)
            _conditions.clear()
            keys = dict(_keys)
            _keys.clear()
        for (action, key), count in sorted(keys.items(), key=lambda i: -i[1])[:15]:
            xbmc.log('PERF property action={} calls={} key={}'.format(action, count, key), xbmc.LOGINFO)
        for condition, (count, total) in conditions.items():
            xbmc.log('PERF condition calls={} total_ms={:.1f} condition={}'.format(
                count, total * 1000, condition.replace(' ', '')), xbmc.LOGINFO)
        for (thread, api), (count, total, longest) in sorted(stats.items()):
            xbmc.log('PERF api thread={} api={} calls={} total_ms={:.1f} avg_ms={:.3f} max_ms={:.1f} interval_s={}'.format(
                thread.replace(' ', '_'), api, count, total * 1000, total * 1000 / count, longest * 1000, INTERVAL), xbmc.LOGINFO)


def _patch_finalise():
    from tmdbhelper.lib.monitor.listitemtools import ListItemMonitorFunctions
    original = ListItemMonitorFunctions.on_finalise

    def on_finalise(self):
        _local.property_calls = 0
        start = time.perf_counter()
        try:
            return original(self)
        finally:
            xbmc.log('PERF finalise ms={:.1f} property_calls={} label={}'.format(
                (time.perf_counter() - start) * 1000, _local.property_calls,
                xbmc.getInfoLabel('ListItem.Label').replace(' ', '_')), xbmc.LOGINFO)

    ListItemMonitorFunctions.on_finalise = on_finalise


_patch_finalise()
threading.Thread(target=_report, name='PERF_report', daemon=True).start()
