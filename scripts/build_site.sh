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

# GitHub Pages 는 파일을 10분간 브라우저에 캐시하게 한다. 배포마다 버전을 붙여
# 스크립트·스타일 주소를 바꾸고(예전 파일을 다시 쓰지 않게), 페이지가 새 버전을 알아챌 수 있게 version.json 을 둔다.
VERSION="$(date -u +%Y%m%d%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo local)"
sed -i -E "s#(href|src)=\"\./(style\.css|config\.js|push\.js|app\.js)\"#\1=\"./\2?v=${VERSION}\"#g" _site/index.html
sed -i "s#<meta charset=\"utf-8\">#<meta charset=\"utf-8\">\n  <meta name=\"app-version\" content=\"${VERSION}\">#" _site/index.html
printf '{"v":"%s"}\n' "$VERSION" > _site/version.json
grep -q "app-version" _site/index.html && grep -q "app.js?v=${VERSION}" _site/index.html || { echo "버전 표시를 넣지 못했습니다"; exit 1; }

echo "_site ready: $(find _site -type f | wc -l) files, version ${VERSION}"
