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
# Kai and Anne: VRoid Studio CC0 models (pixiv, via OpenGameArt). Anne borrows Kai's trousers and shoes at load time.
OGA=https://opengameart.org/sites/default/files
get_vroid() {
  [ -f web/models/$3 ] && return
  [ -f .cache/$1.zip ] || curl -sL -o .cache/$1.zip $OGA/$1.zip
  unzip -q -o -j .cache/$1.zip "$2" -d .cache/vroid && cp ".cache/vroid/$2" web/models/$3
}
get_vroid sakurada_fumiriya 'Sakurada Fumiriya.vrm' kai.vrm
get_vroid sendagaya_shino 'Sendagaya Shino.vrm' anne.vrm
cd web && npm install --silent && npx esbuild src/main.js --bundle --outfile=bundle.js --format=iife --log-level=warning
