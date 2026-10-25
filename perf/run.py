#!/usr/bin/env python3
"""Run a GUI scenario in kodi-dev and measure Kodi and the TMDb Helper service.

    perf/run.py SCENARIO [--seconds 60] [--service on|off] [--label TEXT]

Scenarios:
  idle-home      Home window, no input
  scroll-movies  movie list (videodb), one "right" every --step seconds
                 (0.2: holding the key, 1.5: browsing item by item)
  settings       settings menu, moving up and down between the categories

Measured:
  - CPU time of kodi.bin (all threads) per second of the run
  - System.FPS, sampled every second (Kodi only renders when something changes)
  - from the PERF lines of perf/tmdbhelper_perf.py: calls and time per Kodi API,
    and the duration of each focus change the service handled

--service off restarts Kodi with the TMDb Helper service switched off (marker
file, see perf/install_hook.sh), on restarts it with the service if needed. Results are printed and appended to perf/results.jsonl.
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, 'data', 'kodi', 'temp', 'kodi.log')
RESULTS = os.path.join(ROOT, 'perf', 'results.jsonl')
RPC = 'http://localhost:8080/jsonrpc'


def rpc(method, params=None):
    body = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}).encode()
    request = urllib.request.Request(RPC, body, {'Content-Type': 'application/json'})
    return json.load(urllib.request.urlopen(request, timeout=10)).get('result')


def builtin(command):
    # kodi-send like `kdev builtin`: some builtins sent through
    # XBMC.ExecuteBuiltin are silently ignored (ActivateWindow, SetProperty)
    subprocess.run(['docker', 'compose', 'exec', '-T', 'kodi', 'kodi-send', '--action=' + command],
                   cwd=ROOT, capture_output=True, check=True)


THREAD_GROUPS = (
    ('render', lambda name, main: name.startswith('llvmpipe')),  # software OpenGL of the container
    ('gui', lambda name, main: main),  # Kodi main thread: input, GUI logic, render submission
    ('python', lambda name, main: name in ('LanguageInvoker', 'Image Thread', 'Cron Thread')),
)


def kodi_cpu_seconds():
    """CPU seconds of kodi.bin per thread group (render, gui, python, other)."""
    out = subprocess.run(
        ['docker', 'compose', 'exec', '-T', 'kodi', 'sh', '-c',
         'p=$(pgrep -x kodi.bin); getconf CLK_TCK; for t in /proc/$p/task/*; do '
         'echo "${t##*/}|$p|$(cat $t/comm)|$(cut -d")" -f2- $t/stat)"; done'],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
    ticks = int(out[0])
    groups = {'render': 0.0, 'gui': 0.0, 'python': 0.0, 'other': 0.0}
    for line in out[1:]:
        tid, pid, name, stat = line.split('|', 3)
        fields = stat.split()
        seconds = (int(fields[11]) + int(fields[12])) / ticks  # utime + stime
        for group, match in THREAD_GROUPS:
            if match(name, tid == pid):
                groups[group] += seconds
                break
        else:
            groups['other'] += seconds
    return groups


def fps():
    value = rpc('XBMC.GetInfoLabels', {'labels': ['System.FPS']})['System.FPS']
    try:
        return float(value)
    except ValueError:
        return None


def current_item():
    labels = rpc('XBMC.GetInfoLabels', {'labels': ['Window.Property(xmlfile)', 'System.CurrentControl', 'ListItem.Label']})
    return [labels['Window.Property(xmlfile)'], labels['System.CurrentControl'] + ' / ' + labels['ListItem.Label']]


SERVICE_OFF = os.path.join(ROOT, 'data', 'kodi', 'temp', 'kodi-dev-service-off')


def set_service(on):
    """Restart Kodi if the service state has to change (see perf/install_hook.sh)."""
    if on != os.path.exists(SERVICE_OFF):
        return
    if on:
        os.remove(SERVICE_OFF)
    else:
        open(SERVICE_OFF, 'w').close()
    subprocess.run([os.path.join(ROOT, 'kdev'), 'restart'], check=True, capture_output=True)
    quiet_other_addons()
    time.sleep(20)  # skin start-up, widgets loading


QUIET = ('plugin.video.jellyfin', 'plugin.video.jellycon')
KEEP_DISABLED = os.path.join(ROOT, 'data', 'kodi', 'temp', 'kodi-dev-keep-disabled')


def quiet_other_addons():
    # The Jellyfin add-ons under test would add their own load and open
    # dialogs. The keep-disabled list stops kodi-dev from enabling them again
    # on the next start; remove the file to get them back.
    with open(KEEP_DISABLED, 'w') as f:
        f.write('\n'.join(QUIET) + '\n')
    for addon in QUIET:
        try:
            rpc('Addons.SetAddonEnabled', {'addonid': addon, 'enabled': False})
        except Exception:
            pass
    time.sleep(2)
    builtin('Dialog.Close(all,true)')


def prepare(scenario):
    # Arctic Fuse opens its options panel on its own on an empty Home and on
    # Back, so close dialogs after switching windows and do not use Back.
    builtin('Dialog.Close(all,true)')
    # GUI.ActivateWindow: ActivateWindow through XBMC.ExecuteBuiltin is
    # ignored when the settings window is open
    window = {
        'idle-home': {'window': 'home'},
        'scroll-movies': {'window': 'videos', 'parameters': ['videodb://movies/titles/', 'return']},
        'settings': {'window': 'settings'},
    }[scenario]
    expected = {'scroll-movies': 10025, 'settings': 10004}.get(scenario)
    for _ in range(3):
        rpc('GUI.ActivateWindow', window)
        time.sleep(4)
        builtin('Dialog.Close(all,true)')
        time.sleep(2)
        current = rpc('GUI.GetProperties', {'properties': ['currentwindow']})['currentwindow']['id']
        if expected in (None, current):
            return
    raise SystemExit('could not open the window for {}, at window {}'.format(scenario, current))


def act(scenario, tick):
    if scenario == 'scroll-movies':
        rpc('Input.Right')  # Arctic Fuse shows the movies as a horizontal row
    elif scenario == 'settings':
        rpc('Input.Down' if (tick // 6) % 2 == 0 else 'Input.Up')


PERF_API = re.compile(r'PERF api thread=(\S+) api=(\S+) calls=(\d+) total_ms=([\d.]+) avg_ms=[\d.]+ max_ms=([\d.]+)')
PERF_FINALISE = re.compile(r'PERF finalise ms=([\d.]+) property_calls=(\d+)')


def parse_log(offset):
    with open(LOG, encoding='utf-8', errors='replace') as f:
        f.seek(offset)
        text = f.read()
    apis = {}
    for thread, api, calls, total, longest in PERF_API.findall(text):
        entry = apis.setdefault(api, {'calls': 0, 'total_ms': 0.0, 'max_ms': 0.0})
        entry['calls'] += int(calls)
        entry['total_ms'] += float(total)
        entry['max_ms'] = max(entry['max_ms'], float(longest))
    finalise = [(float(ms), int(calls)) for ms, calls in PERF_FINALISE.findall(text)]
    return apis, finalise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('scenario', choices=('idle-home', 'scroll-movies', 'settings'))
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--step', type=float, default=0.2)
    parser.add_argument('--service', choices=('on', 'off'), default='on')
    parser.add_argument('--label', default='')
    args = parser.parse_args()

    set_service(args.service == 'on')
    quiet_other_addons()
    prepare(args.scenario)

    first_item = current_item()
    offset = os.path.getsize(LOG)
    cpu_start, start = kodi_cpu_seconds(), time.monotonic()
    samples, tick, next_sample = [], 0, start
    while time.monotonic() - start < args.seconds:
        act(args.scenario, tick)
        tick += 1
        if time.monotonic() >= next_sample:
            samples.append(fps())
            next_sample += 1
        time.sleep(args.step)
    elapsed = time.monotonic() - start
    last_item = current_item()
    cpu_end = kodi_cpu_seconds()
    cpu = {group: round((cpu_end[group] - cpu_start[group]) / elapsed, 3) for group in cpu_end}
    time.sleep(11)  # let the hook write its last 10 s report
    apis, finalise = parse_log(offset)

    samples = [s for s in samples if s is not None]
    result = {
        'time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'scenario': args.scenario, 'service': args.service, 'label': args.label,
        'seconds': round(elapsed, 1),
        'first_item': first_item, 'last_item': last_item,
        'kodi_cpu_cores': cpu,
        'fps_median': statistics.median(samples) if samples else None,
        'fps_min': min(samples) if samples else None,
        'api': {k: {'calls': v['calls'], 'total_ms': round(v['total_ms'], 1), 'max_ms': v['max_ms']}
                for k, v in sorted(apis.items())},
        'finalise_count': len(finalise),
        'finalise_ms_median': statistics.median(ms for ms, _ in finalise) if finalise else None,
        'finalise_ms_max': max(ms for ms, _ in finalise) if finalise else None,
        'finalise_property_calls_median': statistics.median(c for _, c in finalise) if finalise else None,
    }
    with open(RESULTS, 'a') as f:
        f.write(json.dumps(result) + '\n')

    print('{scenario} service={service} {label}'.format(**result))
    print('  window {}, item {!r} -> {!r}'.format(result['first_item'][0], result['first_item'][1], result['last_item'][1]))
    if args.scenario != 'idle-home' and first_item == last_item:
        print('  WARNING: focus did not move, the run did not navigate')
    print('  kodi.bin CPU in cores: {}, FPS median {} (min {})'.format(
        ' '.join('{}={}'.format(k, v) for k, v in cpu.items()), result['fps_median'], result['fps_min']))
    for api, v in result['api'].items():
        print('  {:32} {:6} calls {:9.1f} ms total  {:6.2f} ms avg  {:6.1f} ms max'.format(
            api, v['calls'], v['total_ms'], v['total_ms'] / v['calls'], v['max_ms']))
    if finalise:
        print('  focus changes handled: {}, median {:.0f} ms, max {:.0f} ms, median {} property calls'.format(
            result['finalise_count'], result['finalise_ms_median'], result['finalise_ms_max'],
            result['finalise_property_calls_median']))


if __name__ == '__main__':
    main()
