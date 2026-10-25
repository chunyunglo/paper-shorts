#!/bin/bash
# Download the open models and JS dependencies the podcast pipeline needs (all permissively licensed).
set -e
cd "$(dirname "$0")"
mkdir -p .cache web/models
pip install -q sherpa-onnx soundfile numpy
# Kokoro v1.1 Chinese+English TTS (Apache-2.0), packaged by sherpa-onnx
if [ ! -d .cache/kokoro-multi-lang-v1_1 ]; then
  curl -sL https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-multi-lang-v1_1.tar.bz2 | tar xj -C .cache
fi
# Host avatars: VRM sample models (VRM Public License 1.0, commercial use and modification allowed)
if [ ! -f web/models/anne.vrm ]; then
  git clone -q --depth 1 --filter=blob:none --sparse https://github.com/vrm-c/vrm-specification .cache/vrm-spec
  git -C .cache/vrm-spec sparse-checkout set samples/Seed-san samples/VRM1_Constraint_Twist_Sample
  cp .cache/vrm-spec/samples/VRM1_Constraint_Twist_Sample/vrm/VRM1_Constraint_Twist_Sample.vrm web/models/anne.vrm
  cp .cache/vrm-spec/samples/Seed-san/vrm/Seed-san.vrm web/models/kai.vrm
fi
cd web && npm install --silent && npx esbuild src/main.js --bundle --outfile=bundle.js --format=iife --log-level=warning
