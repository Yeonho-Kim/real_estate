#!/usr/bin/env bash
# docs/ 와 data/ 를 합쳐 GitHub Pages 배포용 _site/ 폴더를 만든다.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf _site
mkdir -p _site/data
cp -r docs/. _site/
cp -r data/. _site/data/
# state.json 은 변화 감지 내부용이라 배포하지 않는다.
rm -f _site/data/state.json
echo "_site ready: $(find _site -type f | wc -l) files"
