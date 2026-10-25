#!/bin/bash
# Download the open models and JS dependencies the podcast pipeline needs (all usable commercially).
set -e
cd "$(dirname "$0")"
mkdir -p .cache web/models
pip install -q sherpa-onnx soundfile numpy
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
cd web && npm install --silent && npx esbuild src/main.js --bundle --outfile=bundle.js --format=iife --log-level=warning
