#!/usr/bin/env bash
# One-time setup: streamlink, plus whisper.cpp + a model if you want captions.
#   ./setup.sh            # streamlink only
#   ./setup.sh captions   # also build whisper-cli and download ggml-medium.en.bin
set -euo pipefail
command -v ffmpeg >/dev/null || { echo "Install ffmpeg first (brew/apt/winget install ffmpeg)"; exit 1; }
python3 -m pip install -r requirements.txt

if [[ "${1:-}" == "captions" ]]; then
  [[ -d whisper.cpp ]] || git clone --depth 1 https://github.com/ggml-org/whisper.cpp
  cmake -S whisper.cpp -B whisper.cpp/build -DCMAKE_BUILD_TYPE=Release
  cmake --build whisper.cpp/build -j --target whisper-cli
  mkdir -p models
  [[ -f models/ggml-medium.en.bin ]] || \
    curl -L -o models/ggml-medium.en.bin \
      https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-medium.en.bin
  echo
  echo "Add whisper-cli to PATH:  export PATH=\"$PWD/whisper.cpp/build/bin:\$PATH\""
fi
