# 아파트 실거래 지도 · 신규 거래 알림

서울 **마포구, 서대문구, 강서구 염창동, 영등포구 양평동, 동작구**의 **300세대 이상** 아파트 단지를 대상으로,
**전용 58~86㎡(59·70·84타입)** 실거래(매매·전월세)를 모아 카카오맵 위에 보여주고 새 거래가 생기면 브라우저 웹 푸시로 알려 줍니다.

- 서버 없음: GitHub Actions 가 하루 2회(08:00, 20:00 KST) 수집하고 GitHub Pages 로 배포합니다.
- 데이터: 국토교통부 실거래가 API, K-apt 단지 정보 API (공공데이터포털, 무료)
- 좌표: 카카오 로컬 API (단지당 1회), 지도: 카카오맵 JavaScript SDK
- 호가(매물) 정보는 공개 API 가 없어 다루지 않습니다. "신규 거래"는 **새로 신고된 실거래**를 뜻합니다.

## 폴더

| 경로 | 역할 |
|---|---|
| `collector/` | Python 수집기 (`python -m collector.main ...`) |
| `collector/config.py` | 지역·세대수·면적 기준, API 주소 |
| `collector/overrides.json` | 실거래 aptSeq → K-apt 단지코드 수동 매핑 |
| `watchlist.json` | 알림 규칙 |
| `data/` | 수집 결과 (Actions 가 커밋) |
| `docs/` | 지도 페이지 (GitHub Pages) |
| `.github/workflows/collect.yml` | 수집 + 알림 + 배포 |
| `.github/workflows/pages.yml` | `docs/` 변경 시 배포 |

## 처음 설정 (한 번만)

### 1. 저장소
1. 저장소를 **Public** 으로 전환합니다 (무료 요금제에서 Pages 를 쓰기 위해).
2. Settings → Pages → **Build and deployment → Source** 를 **GitHub Actions** 로 바꿉니다.

### 2. 공공데이터포털 인증키
[data.go.kr](https://www.data.go.kr) 가입 후 아래 4개 API 를 **활용신청** 합니다 (즉시 승인, 개발계정 하루 1만 건).

| API | 용도 |
|---|---|
| 국토교통부_아파트 매매 실거래가 상세 자료 | 매매 |
| 국토교통부_아파트 전월세 실거래가 자료 | 전월세 |
| 국토교통부_공동주택 단지 목록제공 서비스 | 단지 목록 |
| 국토교통부_공동주택 기본정보 제공 서비스 | 세대수·주소 |

마이페이지의 **일반 인증키(Decoding)** 값을 Secret `DATA_GO_KR_KEY` 로 등록합니다.

> 4개 API 의 요청 주소는 `collector/config.py` 에 있습니다. 포털 명세가 바뀌어 첫 실행 로그에 `HTTP 404` 나 `api error` 가 보이면 활용신청 페이지의 요청 주소로 그 값을 고치면 됩니다.

### 3. 카카오 개발자 앱
[developers.kakao.com](https://developers.kakao.com) → 내 애플리케이션 → 추가.
- **앱 키 → REST API 키** → Secret `KAKAO_REST_KEY` (주소→좌표 변환용)
- **앱 키 → JavaScript 키** → `docs/config.js` 의 `KAKAO_JS_KEY`
- **플랫폼 → Web → 사이트 도메인** 에 `https://<계정>.github.io` 추가 (로컬 확인용으로 `http://localhost:8765` 도 추가)
- 제품 설정에서 **카카오맵** 을 활성화합니다.

### 4. 웹 푸시 키
```bash
pip install -r requirements.txt
python -m collector.gen_vapid
```
- 출력된 `VAPID_PRIVATE_KEY` → Secret `VAPID_PRIVATE_KEY`
- 출력된 `VAPID_PUBLIC_KEY` → `docs/config.js` 의 `VAPID_PUBLIC_KEY`
- Secret `PUSH_CONTACT` 에 `mailto:본인메일` (푸시 서버가 요구하는 연락처)

### 5. 첫 수집
Actions 탭 → **실거래 수집·알림·배포** → Run workflow.
첫 실행은 단지 마스터 생성(좌표 변환 포함)과 24개월 백필을 하므로 10분 안팎 걸립니다. 끝나면 `https://<계정>.github.io/real_estate/` 에서 지도를 볼 수 있습니다.

첫 실행에서는 알림을 보내지 않고 기준 상태만 저장합니다. 두 번째 실행부터 새 거래가 알림 대상이 됩니다.

### 6. 알림 구독 등록 (기기마다)
1. 배포된 페이지에서 **🔔 알림 받기** 를 누르고 권한을 허용합니다.
2. 표시된 구독 JSON 을 복사해 Secret `PUSH_SUBSCRIPTIONS` 에 넣습니다. 기기가 여럿이면 `[ {...}, {...} ]` 배열로 넣습니다.
3. iPhone 은 Safari 에서 홈 화면에 추가한 뒤 그 아이콘으로 열어야 알림 구독이 됩니다.

Secret 목록 정리:

| Secret | 값 |
|---|---|
| `DATA_GO_KR_KEY` | 공공데이터포털 인증키(Decoding) |
| `KAKAO_REST_KEY` | 카카오 REST API 키 |
| `VAPID_PRIVATE_KEY` | gen_vapid 출력 비밀키 |
| `PUSH_CONTACT` | `mailto:...` |
| `PUSH_SUBSCRIPTIONS` | 브라우저 구독 JSON |

## 알림 규칙 (`watchlist.json`)

```json
{
  "notify_new_sales": true,      // 새 매매 거래
  "notify_new_rents": false,     // 새 전월세 거래
  "notify_cancelled": true,      // 기존 거래의 해제
  "types": ["59", "70", "84"],   // 평형 묶음: 59(<65㎡) 70(65~80) 84(80㎡~)
  "max_price": null,             // 만원. 예: 150000 → 15억 이하만
  "complexes": []                // 비우면 수집 대상 전체
}
```
특정 단지만 받으려면 `complexes` 에 `{"kapt_code": "A1xxxxxxx", "types": ["84"], "max_price": 160000, "rents": true}` 처럼 적습니다. 단지코드는 `data/complexes.json` 에 있습니다.
한 번에 알림이 5건을 넘으면 묶음 알림 한 개로 보냅니다.

## 데이터 파일

| 파일 | 내용 |
|---|---|
| `data/complexes.json` | 단지 마스터 (세대수, 주소, 좌표, 학습된 aptSeq) |
| `data/trades/<단지코드>.json` | 단지별 매매·전월세 이력 |
| `data/summary.json` | 지도 마커용 요약 (평형별 3개월 평균, 등락, 전세가율) |
| `data/changes/latest.json` | 마지막 실행에서 발견한 새 거래·해제 |
| `data/unmatched.json` | 단지에 연결하지 못한 거래. 300세대 미만 단지면 정상. 300세대 이상인데 여기 있으면 `collector/overrides.json` 에 매핑 추가 |
| `data/state.json` | 변화 감지용 거래 키 목록 (배포 제외) |

## 동작 방식

1. **단지 마스터**: K-apt 단지 목록(시군구) → 기본정보(세대수·주소) → 300세대 미만과 대상 외 법정동 제외 → 카카오로 좌표 변환. 좌표는 한 번만 구하고 재사용합니다.
2. **수집**: 구별·월별 실거래 API 호출 → 법정동·전용면적 필터 → (법정동, 지번) 또는 단지명 유사도로 단지 연결. 첫 실행은 24개월, 이후엔 최근 6개월만 다시 받아 해제·등기 반영을 따라갑니다.
3. **변화 감지**: 이전 실행의 거래 키와 비교해 새 매매·전월세·해제를 찾습니다.
4. **알림·배포**: 규칙에 맞는 변화를 웹 푸시로 보내고, `data/` 를 커밋한 뒤 `docs/`+`data/` 를 Pages 로 배포합니다.

실거래 신고 기한이 30일이라 계약 후 최대 한 달 뒤에 나타날 수 있습니다.

## 로컬에서 확인

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest collector/tests -q          # 단위 테스트

export DATA_GO_KR_KEY=... KAKAO_REST_KEY=...
python -m collector.main complexes           # 단지 마스터
python -m collector.main collect --months 202609,202610
python -m collector.main notify --dry-run    # 보낼 알림만 출력

scripts/build_site.sh && python -m http.server -d _site 8765   # http://localhost:8765
```

## 기준 바꾸기

- 지역·동 필터: `collector/config.py` 의 `REGIONS`
- 세대수·면적: 같은 파일의 `MIN_HOUSEHOLDS`, `AREA_MIN`, `AREA_MAX` (Actions 의 env 로도 덮어쓸 수 있음)
- 수집 시각: `.github/workflows/collect.yml` 의 cron (UTC 기준)
