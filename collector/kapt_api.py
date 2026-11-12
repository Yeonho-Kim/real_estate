"""K-apt(공동주택관리정보시스템) 단지 목록·기본정보 API."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass

from . import config
from .http import ApiError, QuotaExceeded, get
from .molit_api import _int, _text, describe_error, parse_envelope

log = logging.getLogger(__name__)


@dataclass
class KaptBasic:
    kapt_code: str
    name: str
    address: str        # 법정동 주소 (kaptAddr)
    road_address: str   # 도로명 주소 (doroJuso)
    bjd_code: str
    households: int          # kaptdaCnt, 비어 있으면 hoCnt 로 대신함
    ho_count: int | None     # hoCnt (호수) 원본값
    dong_count: int | None
    approved: str       # 사용승인일 YYYY-MM-DD
    area_60: int | None   # 전용 60㎡ 이하 세대수
    area_85: int | None   # 전용 60~85㎡ 세대수
    area_135: int | None  # 전용 85~135㎡ 세대수
    sale_type: str      # 분양/임대/혼합 (codeSaleNm)
    apt_type: str       # 단지 분류: 아파트/주상복합/연립주택 등 (codeAptNm)
    umd: str            # 주소에서 뽑은 법정동명
    jibun: str          # 주소에서 뽑은 지번 (본번-부번)

    def to_dict(self) -> dict:
        return asdict(self)


_ADDR_RE = re.compile(r"(\S+(?:동|가|읍|면|리))\s+(?:산\s*)?(\d+(?:-\d+)?)")


def parse_lot_address(address: str) -> tuple[str, str]:
    """'서울특별시 마포구 아현동 777 마포래미안푸르지오' → ('아현동', '777').

    지번이 없으면 ('아현동', '') 처럼 동만 돌려준다.
    """
    address = (address or "").strip()
    m = _ADDR_RE.search(address)
    if m:
        return m.group(1), m.group(2)
    tokens = address.split()
    for tok in tokens:
        if re.search(r"(동|가|읍|면|리)$", tok) and not tok.endswith(("특별시", "광역시")):
            return tok, ""
    return "", ""


def _approved(value: str) -> str:
    value = (value or "").strip().replace("-", "").replace(".", "")
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def parse_list(text: str) -> tuple[list[dict], int]:
    items, total = parse_envelope(text)
    out = []
    for item in items:
        code = _text(item, "kaptCode")
        if not code:
            continue
        out.append({
            "kapt_code": code,
            "name": _text(item, "kaptName"),
            "bjd_code": _text(item, "bjdCode"),
            "as1": _text(item, "as1"),
            "as2": _text(item, "as2"),
            "as3": _text(item, "as3"),
            "as4": _text(item, "as4"),
        })
    return out, total


def parse_basic(text: str) -> KaptBasic | None:
    items, _ = parse_envelope(text)
    if not items:
        return None
    item = items[0]
    address = _text(item, "kaptAddr")
    umd, jibun = parse_lot_address(address)
    ho_count = _int(_text(item, "hoCnt"))
    return KaptBasic(
        kapt_code=_text(item, "kaptCode"),
        name=_text(item, "kaptName"),
        address=address,
        road_address=_text(item, "doroJuso"),
        bjd_code=_text(item, "bjdCode"),
        households=_int(_text(item, "kaptdaCnt", "kaptDaCnt")) or ho_count or 0,
        ho_count=ho_count,
        dong_count=_int(_text(item, "kaptDongCnt")),
        approved=_approved(_text(item, "kaptUsedate")),
        area_60=_int(_text(item, "kaptMparea60")),
        area_85=_int(_text(item, "kaptMparea85")),
        area_135=_int(_text(item, "kaptMparea135")),
        sale_type=_text(item, "codeSaleNm"),
        apt_type=_text(item, "codeAptNm"),
        umd=umd,
        jibun=jibun,
    )


MAX_LIST_PAGES = 30


def fetch_list(service_key: str, sigungu_code: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    for page in range(1, MAX_LIST_PAGES + 1):
        params = {"serviceKey": service_key, "sigunguCode": sigungu_code, "pageNo": page, "numOfRows": config.PAGE_SIZE}
        resp = get(config.KAPT_LIST_URL, params)
        if resp.status_code != 200:
            raise ApiError(f"HTTP {resp.status_code} from kapt list: {describe_error(resp.text)}")
        parsed, total = parse_list(resp.text)
        fresh = [p for p in parsed if p["kapt_code"] not in seen]
        seen.update(p["kapt_code"] for p in fresh)
        results.extend(fresh)
        # 서버가 numOfRows 를 더 작게 자를 수 있어 받은 건수로 판단한다.
        if not fresh or len(results) >= total:
            break
    log.info("kapt list %s -> %d단지", sigungu_code, len(results))
    return results


BASIC_RETRY_WAITS = (5, 15)  # 일시 오류일 때 다시 시도하기 전 대기(초)


def fetch_basic(service_key: str, kapt_code: str) -> KaptBasic | None:
    """단지 기본정보. 일시 오류는 잠시 쉬었다 다시 시도하고, 일일 한도 초과(QuotaExceeded)는 바로 올린다."""
    waits = list(BASIC_RETRY_WAITS)
    while True:
        try:
            resp = get(config.KAPT_BASIS_URL, {"serviceKey": service_key, "kaptCode": kapt_code})
            if resp.status_code != 200:
                parse_envelope(resp.text)  # 본문이 포털 오류면 여기서 알맞은 오류가 난다
                raise ApiError(f"HTTP {resp.status_code} from kapt basic: {describe_error(resp.text)}")
            return parse_basic(resp.text)
        except QuotaExceeded:
            raise
        except ApiError as exc:
            if not waits:
                raise
            wait = waits.pop(0)
            log.warning("기본정보 %s 실패 (%s) -> %s초 뒤 재시도", kapt_code, exc, wait)
            time.sleep(wait)
