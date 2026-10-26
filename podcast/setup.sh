#!/bin/bash
# Download the open models, assets and JS dependencies the podcast pipeline needs, and build the two hosts.
set -e
cd "$(dirname "$0")"
mkdir -p .cache web/models
pip install -q sherpa-onnx soundfile numpy scipy
REL=https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models
# Supertonic 3 English TTS (MIT), packaged by sherpa-onnx
[ -d .cache/sherpa-onnx-supertonic-3-tts-int8-2026-05-11 ] || curl -sL $REL/sherpa-onnx-supertonic-3-tts-int8-2026-05-11.tar.bz2 | tar xj -C .cache
# Kokoro v1.1 Chinese+English TTS (Apache-2.0), for Chinese episodes
[ -d .cache/kokoro-multi-lang-v1_1 ] || curl -sL $REL/kokoro-multi-lang-v1_1.tar.bz2 | tar xj -C .cache
# Hosts: VRoid Studio sample models (pixiv; commercial use and modification allowed)
if [ ! -f web/models/AvatarSample_C.vrm ]; then
  git clone -q --depth 1 --filter=blob:none --sparse https://github.com/madjin/vrm-samples .cache/vrm-samples
  git -C .cache/vrm-samples sparse-checkout set --no-cone 'vroid/stable/*.vrm'
  cp .cache/vrm-samples/vroid/stable/AvatarSample_A.vrm .cache/vrm-samples/vroid/stable/AvatarSample_C.vrm web/models/
fi
# Characters, built from scratch in Blender (bpy as a Python module):
# MakeHuman base mesh and targets through MPFB2 (GPL code, CC0 assets), MakeHuman eyes (CC0),
# VRM export through VRM-Addon-for-Blender (MIT). Clothes, hair and skin are procedural (characters/).
if [ ! -f web/models/kai.vrm ]; then
  [ -d .cache/bpyenv ] || { uv venv -q -p 3.13 .cache/bpyenv && uv pip install -q -p .cache/bpyenv bpy==5.1.2 numpy pillow; }
  [ -d .cache/mpfb2 ] || git clone -q --depth 1 https://github.com/makehumancommunity/mpfb2 .cache/mpfb2
  [ -d .cache/vrmaddon ] || git clone -q --depth 1 https://github.com/saturday06/VRM-Addon-for-Blender .cache/vrmaddon
  if [ ! -d .cache/makehuman ]; then
    git clone -q --depth 1 --filter=blob:none --sparse https://github.com/makehumancommunity/makehuman .cache/makehuman
    git -C .cache/makehuman sparse-checkout set --no-cone 'makehuman/data/eyes/*'
  fi
  EXT=~/.config/blender/5.1/extensions/user_default; mkdir -p $EXT
  ln -sfn "$PWD/.cache/mpfb2/src/mpfb" $EXT/mpfb; ln -sfn "$PWD/.cache/vrmaddon/src/io_scene_vrm" $EXT/vrm
  (cd characters && for c in kai anne; do ../.cache/bpyenv/bin/python build.py $c.json "$PWD/../web/models/$c.vrm"; done)
fi
cd web && npm install --silent && npx esbuild src/main.js --bundle --outfile=bundle.js --format=iife --log-level=warning
