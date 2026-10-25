#!/bin/bash
# Render the whole episode in 60 s chunks (resumable), then mux with the dialog audio.
# Needs Xvfb for the faster Mesa renderer: Xvfb :99 -screen 0 1920x1080x24 &
set -e
cd "$(dirname "$0")"
export DISPLAY=${DISPLAY:-:99}
DUR=$(python3 -c "import json;print(json.load(open('web/timeline.json'))['duration'])")
mkdir -p out/chunks
n=$(python3 -c "import math;print(math.ceil($DUR/60))")
for i in $(seq 0 $((n-1))); do
  f=out/chunks/c$(printf %02d $i).mp4
  [ -s $f ] || (cd web && node render.mjs video $((i*60)) $((i*60+60)) ../$f)
done
ls out/chunks/c*.mp4 | sed "s#^out/chunks/#file '#;s/$/'/" > out/chunks/list.txt
ffmpeg -y -loglevel error -f concat -safe 0 -i out/chunks/list.txt -i out/dialog.wav \
  -c:v copy -c:a aac -b:a 192k -shortest out/episode.mp4
echo "out/episode.mp4"
