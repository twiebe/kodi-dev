#!/bin/sh
# Put the timing hook into the TMDb Helper copy in data/kodi/addons (made by
# perf/setup_skin.py), and let data/kodi/temp/kodi-dev-service-off switch the
# service off. Takes effect after ./kdev restart.
set -eu
DIR=$(cd "$(dirname "$0")" && pwd)
ADDON=$DIR/../data/kodi/addons/plugin.video.themoviedb.helper/resources
cp "$DIR/tmdbhelper_perf.py" "$ADDON/tmdbhelper_perf.py"
if ! grep -q 'kodi-dev-service-off' "$ADDON/service.py"; then
    sed -i.orig '/^import tmdbhelper_perf/d' "$ADDON/service.py"
    {
        echo 'import os  # kodi-dev perf hook, must come first'
        echo 'import xbmcvfs'
        echo "SERVICE_OFF = os.path.exists(xbmcvfs.translatePath('special://temp/kodi-dev-service-off'))"
        echo 'if not SERVICE_OFF:'
        echo '    import tmdbhelper_perf  # noqa: F401'
        sed "s/^if __name__ == '__main__':/if __name__ == '__main__' and not SERVICE_OFF:/" "$ADDON/service.py"
    } > "$ADDON/service.py.new"
    mv "$ADDON/service.py.new" "$ADDON/service.py"
    rm -f "$ADDON/service.py.orig"
fi
echo "hook installed, run ./kdev restart"
