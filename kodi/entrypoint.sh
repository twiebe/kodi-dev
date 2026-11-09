#!/bin/bash
# Starts Xvfb, a VNC server and Kodi. Kodi is restarted automatically when it
# exits (e.g. after `kdev restart`), the container only stops on SIGTERM.
set -u

KODI_HOME="$HOME/.kodi"
SEED=/usr/local/share/kodi-dev/userdata
RESOLUTION="${KODI_RESOLUTION:-1280x720}"

mkdir -p "$KODI_HOME/userdata" "$KODI_HOME/addons" "$KODI_HOME/temp" "$KODI_HOME/screenshots"

# Seed settings only on first start, so changes made in Kodi survive restarts
for f in guisettings.xml advancedsettings.xml; do
    [ -e "$KODI_HOME/userdata/$f" ] || cp "$SEED/$f" "$KODI_HOME/userdata/$f"
done

python3 /usr/local/lib/kodi-dev/install_deps.py "$KODI_HOME/addons" \
    || echo "kodi-dev: dependency install failed, continuing" >&2

rm -f /tmp/.X99-lock
Xvfb :99 -screen 0 "${RESOLUTION}x24" -nolisten tcp &
for _ in $(seq 50); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done

# No sound card: a PulseAudio null sink plays audio in real time into nothing.
# (A plain ALSA null device does not pace playback, video then runs too fast.)
pulseaudio --daemonize --exit-idle-time=-1 -n \
    --load=module-null-sink --load=module-native-protocol-unix

x11vnc -display :99 -forever -shared -nopw -quiet -rfbport 5900 >/dev/null 2>&1 &

stopping=0
kodi_pid=
trap 'stopping=1; [ -n "$kodi_pid" ] && kill "$kodi_pid" 2>/dev/null' TERM INT

while [ "$stopping" = 0 ]; do
    rm -f /tmp/kodi-dev-ready
    # KODI_FPS_CAP: at most that many frames a second (swapcap.c); nothing throttles Kodi on Xvfb.
    # A test overrides it for a while in temp/fps_cap of the mounted Kodi folder.
    preload=
    if [ "${KODI_FPS_CAP:-0}" -gt 0 ] 2>/dev/null; then
        rm -f "$KODI_HOME/temp/fps_cap"
        export KODI_FPS_CAP_FILE="$KODI_HOME/temp/fps_cap"
        preload=/usr/local/lib/kodi-dev/libswapcap.so
    fi
    LD_PRELOAD=$preload kodi --standalone --windowing=x11 --audio-backend=pulseaudio &
    kodi_pid=$!
    python3 /usr/local/lib/kodi-dev/enable_addons.py "$KODI_HOME/addons" &
    wait "$kodi_pid"
    kodi_pid=
    [ "$stopping" = 0 ] && { echo "kodi-dev: Kodi exited, restarting" >&2; sleep 1; }
done
