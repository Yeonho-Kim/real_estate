"""수집 대상·필터·경로 설정.

환경변수로 덮어쓸 수 있는 값은 os.environ 에서 읽습니다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TRADES_DIR = DATA_DIR / "trades"
CHANGES_DIR = DATA_DIR / "changes"
COMPLEXES_FILE = DATA_DIR / "complexes.json"
SUMMARY_FILE = DATA_DIR / "summary.json"
STATE_FILE = DATA_DIR / "state.json"
UNMATCHED_FILE = DATA_DIR / "unmatched.json"
LATEST_CHANGES_FILE = CHANGES_DIR / "latest.json"
WATCHLIST_FILE = ROOT / "watchlist.json"
OVERRIDES_FILE = ROOT / "collector" / "overrides.json"


@dataclass(frozen=True)
class Region:
    """시군구 단위 수집 대상. umd_filter 가 비어 있으면 구 전체."""

    code: str  # 법정동코드 앞 5자리 (LAWD_CD / sigunguCode)
    name: str
    # 법정동명 접두어 목록. 예: ("염창동",) 또는 ("양평동",) → 양평동1가~6가 포함
    umd_filter: tuple[str, ...] = field(default_factory=tuple)

    def accepts_umd(self, umd_name: str) -> bool:
        if not self.umd_filter:
            return True
        name = (umd_name or "").strip()
        return any(name.startswith(prefix) for prefix in self.umd_filter)


REGIONS: tuple[Region, ...] = (
    Region("11440", "마포구"),
    Region("11410", "서대문구"),
    Region("11500", "강서구", ("염창동",)),
    Region("11560", "영등포구", ("양평동",)),
    Region("11590", "동작구"),
)

# 세대수 기준 (이상)
MIN_HOUSEHOLDS = int(os.environ.get("MIN_HOUSEHOLDS", "300"))

# 전용면적 범위(㎡). 59타입(59.9x) ~ 84타입(84.9x) 을 포함하도록 여유를 둠.
AREA_MIN = float(os.environ.get("AREA_MIN", "58"))
AREA_MAX = float(os.environ.get("AREA_MAX", "86"))  # 미만

# 평형 묶음: (라벨, 하한 포함, 상한 미만)
TYPE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("59", 0.0, 65.0),
    ("70", 65.0, 80.0),
    ("84", 80.0, 1000.0),
)

# 최초 수집 시 과거 몇 개월까지 받을지, 매 실행마다 다시 받을 최근 개월 수
BACKFILL_MONTHS = int(os.environ.get("BACKFILL_MONTHS", "24"))
REFRESH_MONTHS = int(os.environ.get("REFRESH_MONTHS", "6"))

# 요약 통계 기준 개월
SUMMARY_WINDOW_MONTHS = 3

# ---- API 주소 (공공데이터포털 명세가 바뀌면 여기만 수정) ----
# K-apt 두 서비스는 2026-08 개편으로 목록 4판, 기본정보 V5 가 되었고 응답이 JSON 이다.
# 버전이 또 오르면 "해당 오픈API 서비스가 없거나 폐기됨" 오류가 난다. 그때 아래 두 주소의 숫자를 올린다.
MOLIT_SALE_URL = os.environ.get(
    "MOLIT_SALE_URL",
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev",
)
MOLIT_RENT_URL = os.environ.get(
    "MOLIT_RENT_URL",
    "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent",
)
KAPT_LIST_URL = os.environ.get(
    "KAPT_LIST_URL",
    "https://apis.data.go.kr/1613000/AptListService4/getSigunguAptList4",
)
KAPT_BASIS_URL = os.environ.get(
    "KAPT_BASIS_URL",
    "https://apis.data.go.kr/1613000/AptBasisInfoServiceV5/getAphusBassInfoV5",
)
KAKAO_ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

PAGE_SIZE = 1000
REQUEST_TIMEOUT = 40
REQUEST_RETRIES = 3
REQUEST_SLEEP = 0.2  # 호출 사이 대기(초)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value if value else default


def clean_service_key(key: str) -> str:
    """공공데이터포털 인증키 정리.

    포털은 같은 키를 Encoding(%2B, %3D 포함)과 Decoding 두 형태로 보여 준다.
    요청 라이브러리가 한 번 인코딩하므로 Decoding 형태로 맞춘다. 앞뒤 공백·줄바꿈도 없앤다.
    """
    from urllib.parse import unquote

    key = (key or "").strip()
    return unquote(key) if "%" in key else key


def type_bucket(area: float) -> str | None:
    for label, lo, hi in TYPE_BUCKETS:
        if lo <= area < hi:
            return label
    return None


def in_area_range(area: float) -> bool:
    return AREA_MIN <= area < AREA_MAX
