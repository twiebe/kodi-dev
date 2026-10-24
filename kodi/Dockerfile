# Kodi comes from Debian. DEBIAN_SUITE picks the suite, KODI_VERSION is an apt
# version glob within it (see .env.example for which suite has which version).
ARG DEBIAN_SUITE=forky
FROM debian:${DEBIAN_SUITE}-slim

ARG UID=1000
ARG GID=1000
ARG KODI_VERSION=2:21.3*

# Kodi 21 (Omega) from Debian, a virtual X display with software GL (mesa),
# a VNC server to watch it, and tools for screenshots and builtin commands.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        "kodi=${KODI_VERSION}" \
        "kodi-bin=${KODI_VERSION}" \
        "kodi-data=${KODI_VERSION}" \
        "kodi-eventclients-kodi-send=${KODI_VERSION}" \
        xvfb \
        x11vnc \
        x11-utils \
        imagemagick \
        libgl1-mesa-dri \
        libegl-mesa0 \
        mesa-utils \
        pulseaudio \
        python3 \
        ca-certificates \
        procps \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g ${GID} kodi \
    && useradd -m -u ${UID} -g ${GID} -s /bin/bash kodi

COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh
COPY install_deps.py enable_addons.py /usr/local/lib/kodi-dev/
COPY userdata/ /usr/local/share/kodi-dev/userdata/

RUN install -d -m 1777 /tmp/.X11-unix

ENV DISPLAY=:99 \
    LIBGL_ALWAYS_SOFTWARE=1

USER kodi
WORKDIR /home/kodi

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
