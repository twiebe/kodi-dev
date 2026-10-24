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
```

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

## Known quirks

- Kodi waits for add-on service threads on exit. If they do not stop,
  `kdev restart` kills Kodi after 20 seconds (it says so).
- Seeking lands on keyframes, which are up to 25 s apart in the test clips.
