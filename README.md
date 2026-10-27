# kodi-dev

Isolated test environment for Kodi add-ons: Kodi 21.3 (Omega) and a Jellyfin
server in Docker, seeded with test media and users, driven from the command
line with `./kdev`. Everything runs locally and binds to `127.0.0.1` only.

The goal is that add-on changes can be tested end to end (by a person or by an
agent) without a real Kodi box: start Kodi, browse the add-on, play media,
read the log, take screenshots and check the server state.

## What is inside

| Service    | What it is                                                         | Port (127.0.0.1) |
|------------|--------------------------------------------------------------------|------------------|
| `kodi`     | Debian with Kodi `${KODI_VERSION}` (default 21.3), Xvfb + software GL, PulseAudio null sink | 8080 JSON-RPC, 5900 VNC |
| `jellyfin` | `jellyfin/jellyfin:${JELLYFIN_VERSION}` (default 12.3)              | 8096             |
| `faultproxy` | Proxy in front of Jellyfin that fails selected requests (`kdev fault`) | 8097           |

- The add-on under test is bind-mounted into Kodi's add-ons folder, so code
  changes are live. Python service code needs `./kdev restart`.
- Add-on dependencies (`<import addon=...>`) are installed from the official
  Kodi Omega repository on container start, and all user add-ons are enabled.
- Kodi logs at debug level. Its profile lives in `data/kodi/` (log:
  `data/kodi/temp/kodi.log`).
- Kodi itself has no hardware video decoding and no sound output. Playback
  runs in software, audio goes into a null sink in real time.

## Kodi version

Kodi is installed from Debian packages, set in `.env`:

```sh
KODI_DEBIAN_SUITE=forky     # 21.3 is in forky (testing), 21.2 in trixie (Debian 13)
KODI_VERSION=2:21.3*        # apt version glob
```

`./kdev up` rebuilds the image after a change; each suite gets its own image
tag, so switching back and forth does not rebuild every time. Only versions a
Debian suite currently ships are available, and testing moves on: if a build
fails with "version not found", check with
`docker run --rm debian:forky-slim sh -c 'apt-get update -qq; apt-cache madison kodi'`.

## Setup

```sh
cp .env.example .env   # set ADDON_DIR and ADDON_ID
./kdev up              # build and start, waits until Kodi and Jellyfin are ready
./kdev seed            # test media, Jellyfin setup, add-on profile
```

The add-on folder must contain an `addon.xml`. JellyCon generates it:
`python build.py --version py3` in the JellyCon checkout.

Start over from nothing: `./kdev reset --yes` (deletes `data/`).

### Test data

`./kdev seed` is idempotent and writes everything it created to `data/seed.json`.

- Jellyfin admin `admin` / `admin`, an API key `kodi-dev` for scripts
- Users `tester` / `tester` and `nopass` (no password)
- Libraries `Movies` (Kdev Alpha, Kdev Beta) and `Shows` (Kdev Show, S01E01-03).
  Clips are 10 minutes of test pattern with a tone, generated with ffmpeg,
  metadata comes from `.nfo` files (no internet lookups). Ten minutes because
  Jellyfin ignores resume positions in items shorter than 5 minutes.

### Add-on profiles

`profiles/<addon id>.py` is applied by `./kdev seed` when `ADDON_ID` matches.
It gets the `kdev` module and the seed data and prepares the add-on, e.g. logs
it in. `profiles/plugin.video.jellycon.py` writes JellyCon's settings and
`auth.json` for user `tester`, so Kodi starts logged in without any dialogs.

## kdev commands

```sh
./kdev up | down | wait | restart | reset --yes | seed

# Kodi
./kdev ls 'plugin://plugin.video.jellycon/'            # list a directory (runs the plugin)
./kdev rpc Player.GetActivePlayers                     # any JSON-RPC method
./kdev rpc Player.Open '{"item":{"file":"plugin://..."}}'
./kdev action down down select contextmenu back        # remote control input
./kdev builtin 'RunPlugin(plugin://...)'               # Kodi builtin via kodi-send
./kdev screenshot [name]                               # prints the PNG path
./kdev log [-n 50] [-g pattern] [-a]                   # log of the current Kodi run

# Jellyfin
./kdev userdata tester 'Kdev Alpha'                    # played state + resume position
./kdev user tester [enable|disable]                    # e.g. to provoke 401s
./kdev jf GET /Users                                   # any API call with the admin key

# Fault injection (add-on must use http://faultproxy:8096 as server address)
./kdev fault add 'IncludeItemTypes=Movie' --times 1    # answer with 500 once
./kdev fault add '^/system/info$' --method GET --status 503
./kdev fault add 'PlayedItems' --drop --times 4        # close the connection, no answer
./kdev fault add '/Sessions/Playing' --delay 30        # pass on after 30 s (read timeout)
./kdev fault add 'IncludeItemTypes=Audio' --delay 8 --times 1  # hold one request, e.g. to quit Kodi mid-sync
./kdev fault add '/MediaSegments/' --body '{"Items":[]}'   # canned answer (200, JSON)
./kdev fault show | clear                              # rules and requests they hit
```

## Fault injection

`faultproxy` passes every request through to Jellyfin unless it matches a rule
from `kdev fault add`. A rule answers with a status (`--status`, default
500), a canned body (`--body TEXT`, status 200 unless `--status` is given,
`--content-type` defaults to `application/json`), drops the connection
(`--drop`) or delays the request (`--delay`). MATCH is a regular expression
searched in the request path including the query string, ignoring case. The
first matching rule wins.
Rules live in `data/faults/faults.json`, are read on every request and counted
down with `--times`; hits are logged to `data/faults/faults.log` (emptied by
`kdev fault clear`). WebSocket connections and chunked request bodies are
piped through unchanged.

Each request gets its own upstream connection, so every request is checked
even when the client keeps its connection open.

To wait for a delayed request before acting, poll the log:
`until ./kdev fault show | grep -q DELAY; do sleep 0.5; done`.

To route an add-on through it, set its server address to
`http://faultproxy:8096` (from the host: `http://localhost:8097`).

Watch Kodi live with a VNC client on `localhost:5900` (no password) of the
machine running Docker.

## Multiple add-ons

`compose.yaml` mounts one add-on. For more, add a `compose.override.yaml`
(git-ignored):

```yaml
services:
  kodi:
    volumes:
      - /path/to/other.addon:/home/kodi/.kodi/addons/other.addon.id
```

Every mounted folder needs an `addon.xml`. Add-ons that generate it (JellyCon,
Jellyfin for Kodi: `python build.py`) keep it git-ignored, so a fresh clone or
`git worktree` has none: copy it over. Without it Kodi logs "Unable to find
plugin" and disables the add-on; enable it again with
`./kdev rpc Addons.SetAddonEnabled '{"addonid":"<id>","enabled":true}'`.

### Jellyfin for Kodi (plugin.video.jellyfin)

There is no profile for it yet. After mounting it, sign in once by hand
(VNC, or `kdev action`): server `http://jellyfin:8096` (or
`http://faultproxy:8096` for fault injection), "Manual login", `tester` /
`tester`. Its state lives in `data/kodi/userdata/addon_data/plugin.video.jellyfin/`
and in `Database/jellyfin.db`, the synced items in `MyVideos*.db` and
`MyMusic*.db`.

- An interrupted full sync stays in `sync.json` (`Libraries`,
  `RestorePoint`). The next start asks "Resume the previous sync?", and until
  that is answered every new sync is refused with "A sync is already running".
  To start clean, stop Kodi (`docker compose stop kodi`), empty both keys and
  start it again (`kdev restart` starts a stopped Kodi).
- `RunPlugin(plugin://plugin.video.jellyfin/?mode=synclib&id=<library id>)`
  adds and syncs a library, `mode=updatelib` updates one, `mode=removelib`
  removes it. Library ids: `./kdev jf GET /Library/VirtualFolders` (`ItemId`).
- Unit tests and linters run outside Docker: `pip install pytest black flake8`
  into a venv, then `pytest`, `black --check .`, `flake8` in the checkout.

## Testing tips

- Read Kodi's databases from the host with `sqlite3`, e.g.
  `data/kodi/userdata/Database/MyVideos131.db`. Rows of a transaction that is
  still open are not visible there yet. To change them, stop Kodi first.
- `kdev log` shows the current Kodi run only; `kdev log -a` includes the
  previous one (`kodi.old.log`), which is where an exit or crash ends up after
  `kdev restart`.
- `kdev screenshot NAME` takes a name, not a path; it prints where the PNG is.
- `kdev user tester disable` makes JellyCon show its "login rejected" dialog;
  after enabling the user again, `kdev seed` refreshes JellyCon's login.
- Media you add for a test (folders under `data/media/`, extra libraries)
  stays until removed: delete the folder, then
  `./kdev jf POST /Library/Refresh`, or the library with
  `./kdev jf DELETE '/Library/VirtualFolders?name=<name>'`.

## Performance measurements

`perf/` measures Kodi with the Arctic Fuse 3 skin and the TMDb Helper service:

1. `perf/setup_skin.py` copies the local checkouts of the skin, TMDb Helper
   and Skin Variables into `data/kodi/addons` and downloads what they need.
2. `perf/install_hook.sh` adds a timing hook to the TMDb Helper copy. It logs
   `PERF` lines with the Kodi API calls of the service and how long they took.
3. `./kdev restart`, then switch the skin to Arctic Fuse 3.
4. `perf/run.py SCENARIO [--service on|off]` runs a scenario (`idle-home`,
   `scroll-movies`, `settings`) for 60 s and prints Kodi's CPU per thread
   group, the frame rate and the service's API timings. `perf/matrix.sh` runs
   all of them with the service off and on, twice.

`perf/run.py` keeps the Jellyfin add-ons disabled through
`data/kodi/temp/kodi-dev-keep-disabled`; delete that file to get them back.
`perf/plugin.video.kodidev.slowwidget` is a widget source that answers after
`?delay=` seconds, to see a skin's loading indicators.

## Known quirks

- Kodi waits for add-on service threads on exit and kills each service after
  5 seconds. JellyCon always, and Jellyfin for Kodi right after start, take
  that long, so with both mounted Kodi can need more than 20 seconds to exit.
  `kdev restart` then kills it (it says so); nothing is lost but the log tail.
- Seeking lands on keyframes, which are up to 25 s apart in the test clips.
