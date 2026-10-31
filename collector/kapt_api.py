"""K-apt(공동주택관리정보시스템) 단지 목록·기본정보 API."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from . import config
from .http import ApiError, get
from .molit_api import _int, _text, parse_envelope

log = logging.getLogger(__name__)


@dataclass
class KaptBasic:
    kapt_code: str
    name: str
    address: str        # 법정동 주소 (kaptAddr)
    road_address: str   # 도로명 주소 (doroJuso)
    bjd_code: str
    households: int
    dong_count: int | None
    approved: str       # 사용승인일 YYYY-MM-DD
    area_60: int | None   # 전용 60㎡ 이하 세대수
    area_85: int | None   # 전용 60~85㎡ 세대수
    area_135: int | None  # 전용 85~135㎡ 세대수
    sale_type: str      # 분양/임대 (codeSaleNm)
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


def parse_list(xml_text: str) -> tuple[list[dict], int]:
    items, total = parse_envelope(xml_text)
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


def parse_basic(xml_text: str) -> KaptBasic | None:
    items, _ = parse_envelope(xml_text)
    if not items:
        # 단건 응답은 items/item 없이 body/item 또는 body 바로 아래에 올 수도 있다.
        root = ET.fromstring(xml_text)
        items = root.findall(".//body/item")
    if not items:
        body = ET.fromstring(xml_text).find(".//body")
        if body is None or body.find("kaptCode") is None:
            return None
        items = [body]
    item = items[0]
    address = _text(item, "kaptAddr")
    umd, jibun = parse_lot_address(address)
    return KaptBasic(
        kapt_code=_text(item, "kaptCode"),
        name=_text(item, "kaptName"),
        address=address,
        road_address=_text(item, "doroJuso"),
        bjd_code=_text(item, "bjdCode"),
        households=_int(_text(item, "kaptdaCnt")) or 0,
        dong_count=_int(_text(item, "kaptDongCnt")),
        approved=_approved(_text(item, "kaptUsedate")),
        area_60=_int(_text(item, "kaptMparea60")),
        area_85=_int(_text(item, "kaptMparea85")),
        area_135=_int(_text(item, "kaptMparea135")),
        sale_type=_text(item, "codeSaleNm"),
        umd=umd,
        jibun=jibun,
    )


def fetch_list(service_key: str, sigungu_code: str) -> list[dict]:
    results: list[dict] = []
    page = 1
    while True:
        params = {"serviceKey": service_key, "sigunguCode": sigungu_code, "pageNo": page, "numOfRows": 100}
        resp = get(config.KAPT_LIST_URL, params)
        if resp.status_code != 200:
            raise ApiError(f"HTTP {resp.status_code} from kapt list: {resp.text[:200]}")
        parsed, total = parse_list(resp.text)
        results.extend(parsed)
        if not parsed or len(results) >= total:
            break
        page += 1
    log.info("kapt list %s -> %d단지", sigungu_code, len(results))
    return results


def fetch_basic(service_key: str, kapt_code: str) -> KaptBasic | None:
    resp = get(config.KAPT_BASIS_URL, {"serviceKey": service_key, "kaptCode": kapt_code})
    if resp.status_code != 200:
        raise ApiError(f"HTTP {resp.status_code} from kapt basic: {resp.text[:200]}")
    return parse_basic(resp.text)
