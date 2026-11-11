# 아파트 실거래 지도 · 신규 거래 알림

서울 **마포구, 서대문구, 강서구 염창동, 영등포구 양평동, 동작구**의 **300세대 이상** 아파트 단지를 대상으로,
**전용 58~86㎡(59·70·84타입)** 실거래(매매·전월세)를 모아 카카오맵 위에 보여주고 새 거래가 생기면 브라우저 웹 푸시로 알려 줍니다.

- 서버 없음: GitHub Actions 가 하루 2회(08:17, 20:17 KST) 수집하고 GitHub Pages 로 배포합니다.
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

PC 없이 **휴대폰만으로** 끝낼 수 있습니다. 로컬에서 실행해야 하는 명령은 없습니다.

- Secret 등록: 휴대폰 **브라우저**로 github.com 저장소 → Settings → Secrets and variables → Actions → New repository secret. (GitHub 모바일 앱에는 이 메뉴가 없습니다. 메뉴가 안 보이면 브라우저의 "데스크톱 사이트" 보기를 켭니다.)
- 파일 수정: github.com 에서 파일을 열고 연필 아이콘으로 고친 뒤 Commit changes.
- 워크플로 실행: Actions 탭 → 워크플로 선택 → Run workflow.

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

> 4개 API 의 요청 주소는 `collector/config.py` 에 있습니다. K-apt 두 서비스는 2026년 8월 개편으로 목록 4판(`AptListService4`), 기본정보 V5(`AptBasisInfoServiceV5`)가 됐습니다. 버전이 또 오르면 로그에 "해당 오픈API 서비스가 없거나 폐기됨"이 나오는데, 그때 주소 끝의 숫자를 활용신청 페이지의 요청 주소에 맞게 올리면 됩니다.
>
> Secret 은 반드시 **Settings → Secrets and variables → Actions → Secrets 탭 → Repository secrets** 에 등록합니다. 계정 설정이나 Codespaces·Dependabot 메뉴에 넣으면 워크플로가 읽지 못합니다. 실행 결과 화면의 "설정 확인" 표에서 등록 여부를 볼 수 있습니다.

### 3. 카카오 개발자 앱
콘솔 메뉴가 2026년에 바뀌었습니다. 도메인 등록은 앱 단위가 아니라 **키 단위**로 하고, 카카오맵은 심사 없이 사용 설정만 켜면 됩니다.

1. [developers.kakao.com](https://developers.kakao.com) 에 로그인해 앱을 만듭니다. 앱 이름·회사명·카테고리가 필수이고, 앱 이름에 "카카오"는 넣을 수 없습니다.
2. **[카카오맵] > [사용 설정]** 의 상태를 **ON** 으로 바꿉니다. 켜지 않으면 지도와 주소 검색이 모두 거부됩니다.
3. **[앱] > [플랫폼 키] > [JavaScript 키]** 의 값을 `docs/config.js` 의 `KAKAO_JS_KEY` 에 넣습니다.
4. 같은 화면의 **[JavaScript SDK 도메인]** 에 `https://<계정>.github.io` 를 등록합니다. 경로 없이 도메인까지만 적습니다.
5. **[앱] > [플랫폼 키] > [REST API 키]** 의 값을 Secret `KAKAO_REST_KEY` 로 등록합니다 (주소→좌표 변환용).
6. REST API 키의 **호출 허용 IP 주소는 비워 둡니다.** GitHub Actions 는 실행마다 IP 가 달라서, 등록하면 `ip mismatched` 오류가 납니다.

참고:
- 무료 쿼터는 계정에서 **처음 카카오맵을 켠 앱 하나**에만 적용됩니다. 다른 앱에서 이미 켠 적이 있으면 그 앱의 키를 쓰는 편이 간단합니다.
- JavaScript 키는 페이지 소스에 보이는 것이 정상이며 등록한 도메인에서만 동작합니다. REST API 키는 Secret 에만 둡니다.
- 하루 무료 한도는 웹 지도 30만 건, 주소 검색 10만 건으로 이 프로젝트 사용량보다 훨씬 큽니다.

### 4. 웹 푸시 키
웹 푸시는 공개키·비밀키 한 쌍(VAPID 키)이 필요합니다.

- **공개키**: `docs/config.js` 의 `VAPID_PUBLIC_KEY` 에 이미 들어 있습니다. 손댈 것이 없습니다.
- **비밀키**: 공개키와 짝이 되는 값을 Secret `VAPID_PRIVATE_KEY` 로 등록합니다. 저장소에는 올리지 않습니다.
- Secret `PUSH_CONTACT` 에 `mailto:본인메일` 을 등록합니다 (푸시 서버가 요구하는 연락처).

키 쌍을 새로 만들어야 할 때(비밀키를 잃어버렸거나 노출됐을 때)는 둘을 **함께** 바꿉니다. 한쪽만 바꾸면 알림이 가지 않습니다. 바꾼 뒤에는 6번의 구독 등록도 다시 해야 합니다. PC 가 있으면 아래 명령으로 만들 수 있고, 없으면 Claude Code 세션에 "VAPID 키를 새로 만들어 줘"라고 요청하면 됩니다.

```bash
pip install -r requirements.txt
python -m collector.gen_vapid
```

### 5. 첫 수집
Actions 탭 → **실거래 수집·알림·배포** → Run workflow.
첫 실행은 단지 마스터 생성(좌표 변환 포함)과 24개월 백필을 하므로 30분쯤 걸립니다. K-apt 기본정보 API 가 건당 1~2초로 느리기 때문입니다. 이후 실행은 5분 안팎입니다. 끝나면 `https://<계정>.github.io/real_estate/` 에서 지도를 볼 수 있습니다.

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
| `VAPID_PRIVATE_KEY` | 웹 푸시 비밀키 (`docs/config.js` 공개키의 짝) |
| `PUSH_CONTACT` | `mailto:...` |
| `PUSH_SUBSCRIPTIONS` | 브라우저 구독 JSON |

## 다른 서비스로 가는 링크

단지를 누르면 패널 위쪽에 네이버 지도, 카카오맵, 네이버 부동산, 호갱노노, KB부동산 링크가 나옵니다. 목록과 주소 형식은 `docs/config.js` 의 `LINKS` 에 있습니다.

| 서비스 | 여는 방식 |
|---|---|
| 네이버 지도 | "동 이름 + 단지명" 검색 |
| 카카오맵 | 단지 좌표에 핀 표시 (공식 링크 형식) |
| 네이버 부동산 | "동 이름 + 단지명" 검색 |
| 호갱노노 | "동 이름 + 단지명" 검색 |
| KB부동산 | 단지 좌표로 지도 이동 |

네이버 부동산·호갱노노·KB부동산의 단지 페이지 주소에는 각 서비스의 내부 번호가 들어가는데, 이 번호를 얻을 공개 API 가 없어 검색이나 좌표로 엽니다. 서비스 쪽 주소 형식이 바뀌어 링크가 안 열리면 `LINKS` 의 해당 줄만 고치면 됩니다.

검색에 쓰는 단지명은 K-apt 이름과 실거래 자료의 이름 가운데 더 구체적인 쪽입니다 (예: K-apt "흑석자이" 대신 "흑석리버파크자이").

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
| `data/complexes.json` | 단지 마스터 (세대수, 주소, 좌표, 확정된 연결 정보 `apt_seqs`·`alt_lots`) |
| `data/complexes_skipped.json` | 마스터에서 제외한 단지와 이유 (세대수 미달, 대상 동 아님 등) |
| `data/trades/<단지코드>.json` | 단지별 매매·전월세 이력 |
| `data/summary.json` | 지도 마커용 요약 (평형별 3개월 평균, 등락, 전세가율) |
| `data/changes/latest.json` | 마지막 실행에서 발견한 새 거래·해제 |
| `data/unmatched.json` | 단지에 연결하지 못한 거래 (아래 "거래를 단지에 연결하는 규칙" 참고) |
| `data/state.json` | 변화 감지용 거래 키 목록 (배포 제외) |

## 동작 방식

1. **단지 마스터**: K-apt 단지 목록(시군구) → 기본정보(세대수·주소) → 300세대 미만, 임대 단지, 대상 외 법정동 제외 → 카카오로 좌표 변환. 임대 단지는 매매·전월세 실거래가 없어 뺍니다 (분양과 임대가 섞인 "혼합" 단지는 남깁니다). 세대수 값이 비어 있는 단지는 호수 값으로 대신합니다. 한 번 확인한 단지는 다시 조회하지 않습니다.
2. **수집**: 구별·월별 실거래 API 호출 → 법정동·전용면적 필터 → 단지 연결. 첫 실행은 24개월, 이후엔 최근 6개월만 다시 받아 해제·등기 반영을 따라갑니다.
3. **변화 감지**: 이전 실행의 거래 키와 비교해 새 매매·전월세·해제를 찾습니다.
4. **알림·배포**: 규칙에 맞는 변화를 웹 푸시로 보내고, `data/` 를 커밋한 뒤 `docs/`+`data/` 를 Pages 로 배포합니다.

실거래 신고 기한이 30일이라 계약 후 최대 한 달 뒤에 나타날 수 있습니다.

### 거래를 단지에 연결하는 규칙

K-apt 와 실거래 자료는 같은 단지라도 지번과 이름이 자주 다릅니다 (예: K-apt "마포래미안푸르지오 767" = 실거래 "마포래미안푸르지오4단지 777").
반대로 이름만 비슷한 다른 단지도 많습니다 (예: "북한산두산위브" 와 "북한산두산위브2차"). 실제 데이터에서 같은 단지는 도로명 주소가 항상 같았으므로, 아래 순서로 확실할 때만 연결합니다.

1. 수동 지정 (`collector/overrides.json`)
2. 법정동과 지번이 K-apt 와 같음
3. 같은 법정동에서 도로명과 건물번호가 같음
4. 같은 법정동에서 도로명이 같고 단지명이 같음 (차수 "N차" 와 단지 번호가 어긋나면 다른 단지로 봄)

매매를 먼저 연결하고, 거기서 확정된 지번을 전월세가 따라갑니다. 연결 규칙을 바꾸면(`collector/matching.py` 의 `MATCH_VERSION`) 다음 수집에서 알림 없이 전체 기간을 다시 맞춥니다.

**빠진 단지가 있을 때**

- `data/complexes_skipped.json` 에 있으면 300세대 미만(`households`), 임대 단지(`rental`), 대상 동이 아닌 단지(`umd`)입니다.
- `data/unmatched.json` 에 있고 300세대 이상이면 이름·지번·도로명이 모두 달라 자동으로 못 붙인 경우입니다. 그 항목의 `apt_seq` 값과 `data/complexes.json` 의 단지코드를 `collector/overrides.json` 에 `"apt_seq 값": "단지코드"` 로 추가합니다.
- 단지 구성을 다시 확인하려면 Actions 의 Run workflow 에서 "단지 마스터 다시 만들기"를 켜고 실행합니다.

## 로컬에서 확인 (선택)

PC 가 있을 때만 필요합니다. 평소 운영에는 쓰지 않습니다. 로컬에서 지도를 보려면 카카오 **[JavaScript SDK 도메인]** 에 `http://localhost:8765` 도 등록합니다.

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
- 임대 단지 제외: 같은 파일의 `EXCLUDE_SALE_TYPES` (기본값 `임대`). 바꾼 뒤 "단지 마스터 다시 만들기"로 실행
- 단지 패널의 외부 링크: `docs/config.js` 의 `LINKS`
- 수집 시각: `.github/workflows/collect.yml` 의 cron (UTC 기준)
