#!/bin/bash
# Installs add-on zips into the Flatpak Kodi, then starts Kodi. A running Kodi is asked to quit
# first; add-on settings (addon_data) stay untouched.
#
#   ./install-kodi-addons.sh                 the newest zip in the current directory of the Nightcity
#                                            skin, the Confuse skin, TMDb Helper and Jellyfin. Newest
#                                            means the latest modification time.
#   ./install-kodi-addons.sh A.zip [B.zip]   only these zips, any add-on: its id is the folder in the
#                                            zip that holds addon.xml.
#   --skin NAME                              also switch Kodi to this skin, with either of the above:
#                                            nightcity, confuse or a full id like skin.estuary. The skin
#                                            has to be installed or among the zips.
#   --lang CODE                              also start Kodi in this language, with any of the above:
#                                            de, fr, es, it, pl, ja, en, or a full code like pt_br or
#                                            de_de. A language Kodi does not have yet is downloaded
#                                            from mirrors.kodi.tv for the installed Kodi version.
#                                            Japanese, Chinese and Korean switch the skin's fonts to
#                                            Arial (Kodi's own font with those scripts), any other
#                                            language back to Default. TMDb Helper, when installed,
#                                            looks titles up in the same language (English: en-US,
#                                            TMDb's own).
#
# Kodi registers an add-on it finds on disk as disabled, so every add-on installed here is enabled
# in Kodi's add-on database as well.
set -euo pipefail

APP=tv.kodi.Kodi
DATA="$HOME/.var/app/$APP/data"
ADDONS="$DATA/addons"

kodi_running() {
    flatpak ps --columns=application | grep -qx "$APP"
}

stop_kodi() {
    kodi_running || return 0
    echo "Stopping Kodi..."
    pkill -TERM -x kodi.bin || true  # it saves its settings on TERM; flatpak kill would not let it
    for _ in $(seq 1 40); do
        kodi_running || return 0
        sleep 0.5
    done
    echo "Kodi did not quit within 20 s, nothing was changed. Close it and run this again." >&2
    exit 1
}

install_addon() {
    local id=$1 zip=$2 tmp
    tmp=$(mktemp -d "$DATA/.install.XXXXXX")
    trap 'rm -rf "$tmp"' RETURN
    python3 -m zipfile -e "$zip" "$tmp"
    if [ ! -f "$tmp/$id/addon.xml" ]; then
        echo "$zip has no $id/addon.xml, $id stays as it was." >&2
        return 1
    fi
    rm -rf "${ADDONS:?}/$id"  # all of it: files a new version no longer has must go too
    mv "$tmp/$id" "$ADDONS/$id"
    echo "Installed $zip"
}

# the add-on id of a zip: the top folder that holds addon.xml
zip_id() {
    python3 - "$1" <<'PY'
import sys, zipfile
try:
    names = zipfile.ZipFile(sys.argv[1]).namelist()
except (OSError, zipfile.BadZipFile) as e:
    sys.exit(f'{sys.argv[1]}: {e}')
ids = sorted({n.split('/')[0] for n in names if n.count('/') == 1 and n.endswith('/addon.xml')})
if len(ids) != 1:
    sys.exit(f'{sys.argv[1]}: no single add-on folder with addon.xml in it')
print(ids[0])
PY
}

# --skin NAME and --lang CODE anywhere among the arguments; the rest are zips
skin=
lang=
zips=()
while [ $# -gt 0 ]; do
    case $1 in
        --skin) [ $# -ge 2 ] || { echo "--skin needs a name, nothing was changed." >&2; exit 1; }
                skin=$2; shift 2 ;;
        --skin=*) skin=${1#--skin=}; shift ;;
        --lang) [ $# -ge 2 ] || { echo "--lang needs a code, nothing was changed." >&2; exit 1; }
                lang=$2; shift 2 ;;
        --lang=*) lang=${1#--lang=}; shift ;;
        -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
        *) zips+=("$1"); shift ;;
    esac
done
case $skin in
    ''|skin.*) ;;
    *) skin=skin.$skin ;;
esac
# de -> resource.language.de_de; en is en_gb, the short codes whose country differs are spelled out
lang=${lang#resource.language.}
lang=${lang,,}
case $lang in
    '') ;;
    en) lang=en_gb ;;
    ja) lang=ja_jp ;;
    ko) lang=ko_kr ;;
    zh) lang=zh_cn ;;
    pt) lang=pt_pt ;;
    [a-z][a-z]_[a-z][a-z]) ;;
    [a-z][a-z]) lang=${lang}_$lang ;;
    *) echo "--lang $lang: not a language code like de or pt_br, nothing was changed." >&2; exit 1 ;;
esac
[ -z "$lang" ] || lang=resource.language.$lang
set -- ${zips[@]+"${zips[@]}"}

# a setting in guisettings.xml, while Kodi is stopped; Kodi starts with it
set_setting() {
    local file="$DATA/userdata/guisettings.xml"
    mkdir -p "$DATA/userdata"
    python3 - "$file" "$1" "$2" <<'PY'
import os, sys, xml.etree.ElementTree as ET
path, key, value = sys.argv[1:4]
if os.path.exists(path):
    tree = ET.parse(path)
    root = tree.getroot()
else:
    root = ET.Element('settings', version='2')
    tree = ET.ElementTree(root)
setting = next((s for s in root.iter('setting') if s.get('id') == key), None)
if setting is None:
    setting = ET.SubElement(root, 'setting', id=key)
setting.attrib.pop('default', None)  # marked as Kodi's default, the value would not count
setting.text = value
tree.write(path, encoding='utf-8')
PY
}

# enable add-ons in Kodi's add-on database (the newest Addons<n>.db); one Kodi has not seen yet is
# entered as installed and enabled, so its scan on start leaves it that way
tmdbhelper_language() {
    # TMDb Helper's "language" setting is an index into its LANGUAGES (tmdbhelper/lib/addon/consts.py,
    # read from the installed copy so the two cannot drift): Kodi's de_de is TMDb's de-DE, a
    # country TMDb lacks takes the first of that language, English stays en-US
    local consts="$ADDONS/plugin.video.themoviedb.helper/resources/tmdbhelper/lib/addon/consts.py"
    [ -f "$consts" ] || return 0
    python3 - "$consts" "$DATA/userdata/addon_data/plugin.video.themoviedb.helper/settings.xml" "$1" <<'PY'
import ast, os, re, sys, xml.etree.ElementTree as ET
consts, path, code = sys.argv[1:4]
match = re.search(r'^LANGUAGES = (\([^)]*\))', open(consts, encoding='utf-8').read(), re.M)
if not match:
    sys.exit(0)
languages = ast.literal_eval(match.group(1))
lang, _, country = code.partition('_')
wanted = 'en-US' if lang == 'en' else '{}-{}'.format(lang, country.upper())
if wanted not in languages:
    wanted = next((l for l in languages if l.startswith(lang + '-')), None)
if wanted is None:
    print('TMDb Helper has no {}, its language stays as it was'.format(code))
    sys.exit(0)
if os.path.exists(path):
    tree = ET.parse(path)
    root = tree.getroot()
else:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    root = ET.Element('settings', version='2')
    tree = ET.ElementTree(root)
setting = next((s for s in root.iter('setting') if s.get('id') == 'language'), None)
if setting is None:
    setting = ET.SubElement(root, 'setting', id='language')
setting.attrib.pop('default', None)
setting.text = str(languages.index(wanted))
tree.write(path, encoding='utf-8')
print('TMDb Helper looks up in {}'.format(wanted))
PY
}

enable_addons() {
    python3 - "$DATA/userdata/Database" "$@" <<'PY'
import datetime, pathlib, re, sqlite3, sys
folder, ids = pathlib.Path(sys.argv[1]), sys.argv[2:]
dbs = sorted(folder.glob('Addons*.db'), key=lambda p: int(re.sub(r'\D', '', p.stem) or 0))
if not dbs:
    sys.exit(0)  # a Kodi never started: nothing to enable in yet
con = sqlite3.connect(dbs[-1])
now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
for addon in ids:
    if con.execute('UPDATE installed SET enabled=1, disabledReason=0 WHERE addonID=?', (addon,)).rowcount == 0:
        con.execute('INSERT INTO installed(addonID, enabled, installDate) VALUES(?, 1, ?)', (addon, now))
con.commit()
PY
}

# the newest zip of a language for the installed Kodi from mirrors.kodi.tv, into a folder
download_language() {
    local id=$1 dir=$2 major name
    major=$(flatpak info "$APP" 2>/dev/null | sed -n 's/^ *Version: *\([0-9]*\).*/\1/p' | head -n 1)
    case $major in
        19) name=matrix ;; 20) name=nexus ;; 22) name=piers ;;
        *) name=omega ;;
    esac
    python3 - "https://mirrors.kodi.tv/addons/$name/$id/" "$dir" <<'PY'
import re, sys, urllib.request
url, folder = sys.argv[1:3]
try:
    listing = urllib.request.urlopen(url, timeout=30).read().decode('utf-8', 'replace')
except OSError as e:
    sys.exit(f'{url}: {e}')
zips = sorted(set(re.findall(r'href="([^"/]+\.zip)"', listing)),
              key=lambda n: [int(x) for x in re.findall(r'\d+', n.rsplit('-', 1)[-1])])
if not zips:
    sys.exit(f'{url}: no zip there')
path = f'{folder}/{zips[-1]}'
urllib.request.urlretrieve(url + zips[-1], path)
print(path)
PY
}

declare -A newest=()
if [ $# -gt 0 ]; then
    # only the zips given; all are checked before Kodi is stopped
    for zip in "$@"; do
        if [ ! -f "$zip" ]; then
            echo "$zip: no such file, nothing was changed." >&2
            exit 1
        fi
        id=$(zip_id "$zip") || { echo "Nothing was changed." >&2; exit 1; }
        if [ -n "${newest[$id]:-}" ]; then
            echo "$id is given twice (${newest[$id]} and $zip), nothing was changed." >&2
            exit 1
        fi
        newest[$id]=$zip
    done
else
    for id in skin.nightcity skin.confuse plugin.video.themoviedb.helper plugin.video.jellyfin; do
        zip=$(ls -t -- "$id"-*.zip 2>/dev/null | head -n 1 || true)
        if [ -n "$zip" ]; then
            newest[$id]=$zip
        else
            echo "No $id-*.zip here, $id stays as it was."
        fi
    done
    if [ ${#newest[@]} -eq 0 ]; then
        echo "Nothing to install in $PWD." >&2
        exit 1
    fi
fi

# a language that is neither installed nor among the zips is downloaded, before Kodi is stopped;
# English comes with Kodi
if [ -n "$lang" ] && [ "$lang" != resource.language.en_gb ] && [ -z "${newest[$lang]:-}" ] && [ ! -f "$ADDONS/$lang/addon.xml" ]; then
    langdir=$(mktemp -d)
    trap 'rm -rf "$langdir"' EXIT
    echo "Downloading $lang..."
    newest[$lang]=$(download_language "$lang" "$langdir") || { echo "$lang could not be downloaded, nothing was changed." >&2; exit 1; }
fi

# Estuary comes with Kodi, it is not in the add-on folder
if [ -n "$skin" ] && [ "$skin" != skin.estuary ] && [ -z "${newest[$skin]:-}" ] && [ ! -f "$ADDONS/$skin/addon.xml" ]; then
    echo "$skin is neither installed nor among the zips, nothing was changed." >&2
    exit 1
fi

stop_kodi
mkdir -p "$ADDONS"
for id in "${!newest[@]}"; do
    install_addon "$id" "${newest[$id]}"
done
enable_addons "${!newest[@]}"
[ -z "$lang" ] || [ "$lang" = resource.language.en_gb ] || enable_addons "$lang"
if [ -n "$skin" ]; then
    set_setting lookandfeel.skin "$skin"
    echo "Kodi starts with $skin"
fi
if [ -n "$lang" ]; then
    set_setting locale.language "$lang"
    case $lang in
        resource.language.ja_*|resource.language.zh_*|resource.language.ko_*) font=Arial ;;
        *) font=Default ;;
    esac
    set_setting lookandfeel.font "$font"
    echo "Kodi starts in ${lang#resource.language.}, fonts $font"
    tmdbhelper_language "${lang#resource.language.}"
fi

exec flatpak run "$APP"
