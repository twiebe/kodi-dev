#!/bin/sh
# All scenarios with the TMDb Helper service off and on, 60 s each, twice.
# Switching the service restarts Kodi (see run.py --service).
set -eu
cd "$(dirname "$0")"
for rep in 1 2; do
    for service in off on; do
        ./run.py idle-home --service $service --label "rep$rep"
        ./run.py scroll-movies --step 0.2 --service $service --label "hold rep$rep"
        ./run.py scroll-movies --step 1.5 --service $service --label "browse rep$rep"
        ./run.py settings --step 0.5 --service $service --label "rep$rep"
    done
done
