"""국토교통부 아파트 실거래가(매매·전월세) API 호출과 파싱."""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

from . import config
from .http import ApiError, QuotaExceeded, get

log = logging.getLogger(__name__)

OK_CODES = {"00", "000"}
NO_DATA_CODES = {"03", "200"}


@dataclass
class Sale:
    key: str
    apt_seq: str
    apt_name: str
    umd: str          # 법정동명
    jibun: str
    road_name: str
    area: float       # 전용면적 ㎡
    floor: int | None
    dong: str         # 등기 완료 건에만 제공
    price: int        # 만원
    date: str         # YYYY-MM-DD 계약일
    build_year: int | None
    dealing: str      # 중개거래 / 직거래
    cancelled: bool
    cancel_date: str
    registered: str   # 등기일자 (YYYY-MM-DD) 또는 ""
    sgg_code: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Rent:
    key: str
    apt_name: str
    umd: str
    jibun: str
    area: float
    floor: int | None
    deposit: int        # 만원
    monthly: int        # 만원, 0 이면 전세
    date: str
    build_year: int | None
    contract_type: str  # 신규 / 갱신 / ""
    term: str           # 계약기간 예: 24.10~26.10
    renewal_right: str  # 갱신요구권 사용
    sgg_code: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- 공통 유틸 ----------

def _text(item: ET.Element, *names: str) -> str:
    for name in names:
        node = item.find(name)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def _int(value: str) -> int | None:
    value = (value or "").replace(",", "").strip()
    if not value:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None


def _money(value: str) -> int:
    return _int(value) or 0


def _float(value: str) -> float | None:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


def _date(year: str, month: str, day: str) -> str:
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return ""


def _short_date(value: str) -> str:
    """'24.08.01' 또는 '2024.08.01' 또는 '20240801' → 'YYYY-MM-DD'."""
    value = (value or "").strip()
    if not value:
        return ""
    m = re.match(r"^(\d{2}|\d{4})[.\-/]?(\d{2})[.\-/]?(\d{2})$", value)
    if not m:
        return value
    year = m.group(1)
    if len(year) == 2:
        year = "20" + year
    return f"{year}-{m.group(2)}-{m.group(3)}"


def _is_quota(code: str, msg: str) -> bool:
    """코드 22 = LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR (일일 한도). 초당 한도(PER_SECOND)는 제외."""
    upper = (msg or "").upper()
    if "PER_SECOND" in upper:
        return False
    return code.strip() == "22" or "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS" in upper


def _portal_error(code: str, msg: str) -> ApiError:
    text = f"portal error {code.strip()}: {msg.strip()}"
    return QuotaExceeded(text) if _is_quota(code, msg) else ApiError(text)


def _api_error(code: str, msg: str) -> ApiError:
    text = f"api error {code.strip()}: {msg.strip()}"
    return QuotaExceeded(text) if _is_quota(code, msg) else ApiError(text)


def _json_items(data) -> tuple[list[ET.Element], int]:
    """JSON 응답을 XML 과 같은 모양(item 요소 목록)으로 바꾼다.

    공공데이터포털 JSON 모양: {"response": {"header": {...}, "body": {"items": [...] | {"item": ...}, "item": {...}}}}
    """
    if isinstance(data, dict) and isinstance(data.get("OpenAPI_ServiceResponse"), dict):
        # 포털 공통 오류가 JSON 으로 올 때: {"OpenAPI_ServiceResponse": {"cmmMsgHeader": {...}}}
        head = data["OpenAPI_ServiceResponse"].get("cmmMsgHeader") or data["OpenAPI_ServiceResponse"]
        head = head if isinstance(head, dict) else {}
        raise _portal_error(str(head.get("returnReasonCode", "") or ""),
                            str(head.get("returnAuthMsg", "") or head.get("errMsg", "") or ""))
    root = data.get("response", data) if isinstance(data, dict) else {}
    if not isinstance(root, dict):
        raise ApiError("JSON 응답 모양을 알 수 없음")
    header = root.get("header") if isinstance(root.get("header"), dict) else root
    code = str(header.get("resultCode", "") or "").strip()
    msg = str(header.get("resultMsg", "") or "")
    if code and code not in OK_CODES and code not in NO_DATA_CODES:
        raise _api_error(code, msg)
    body = root.get("body")
    if not isinstance(body, dict):
        if code in OK_CODES or code in NO_DATA_CODES:
            return [], 0
        raise ApiError(f"JSON 응답에 body 가 없음 (키: {sorted(root)[:8]})")

    raw = body.get("items")
    if isinstance(raw, dict):          # 구버전: {"items": {"item": [...]}}
        raw = raw.get("item")
    if raw in (None, ""):
        raw = body.get("item")         # 단건: {"body": {"item": {...}}}
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []

    items: list[ET.Element] = []
    for record in raw:
        if not isinstance(record, dict):
            continue
        el = ET.Element("item")
        for key, value in record.items():
            if isinstance(value, (dict, list)):
                continue
            ET.SubElement(el, str(key)).text = "" if value is None else str(value)
        items.append(el)
    total = _int(str(body.get("totalCount", "") or "")) or len(items)
    return items, total


def parse_envelope(text: str) -> tuple[list[ET.Element], int]:
    """응답(XML 또는 JSON)에서 item 목록과 totalCount를 꺼낸다. 오류 코드면 ApiError."""
    stripped = (text or "").lstrip("\ufeff \t\r\n")
    if stripped[:1] in ("{", "["):
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            raise ApiError(f"JSON parse error: {exc}; body={stripped[:300]}") from exc
        return _json_items(data)

    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise ApiError(f"XML parse error: {exc}; body={stripped[:300]}") from exc

    # 공공데이터포털 공통 오류 형식 (OpenAPI_ServiceResponse)
    if root.tag == "OpenAPI_ServiceResponse":
        code = (root.findtext(".//returnReasonCode") or "").strip()
        msg = (root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "").strip()
        raise _portal_error(code, msg)

    code = (root.findtext(".//header/resultCode") or root.findtext(".//resultCode") or "").strip()
    msg = root.findtext(".//header/resultMsg") or root.findtext(".//resultMsg") or ""
    if code and code not in OK_CODES and code not in NO_DATA_CODES:
        raise _api_error(code, msg)

    items = root.findall(".//items/item") or root.findall(".//body/item")
    total = _int(root.findtext(".//body/totalCount") or root.findtext(".//totalCount") or "0") or len(items)
    return items, total


def describe_error(text: str) -> str:
    """오류 응답 본문을 한 줄 설명으로 줄인다."""
    try:
        parse_envelope(text)
    except ApiError as exc:
        return str(exc)
    return " ".join((text or "").split())[:200]


# ---------- 매매 ----------

def parse_sale_item(item: ET.Element) -> Sale | None:
    area = _float(_text(item, "excluUseAr", "전용면적"))
    if area is None:
        return None
    umd = _text(item, "umdNm", "법정동")
    jibun = _text(item, "jibun", "지번")
    apt_name = _text(item, "aptNm", "아파트")
    apt_seq = _text(item, "aptSeq", "일련번호")
    date = _date(_text(item, "dealYear", "년"), _text(item, "dealMonth", "월"), _text(item, "dealDay", "일"))
    floor = _int(_text(item, "floor", "층"))
    price = _money(_text(item, "dealAmount", "거래금액"))
    dong = _text(item, "aptDong", "동")
    key = "|".join([apt_seq or f"{umd}:{jibun}", date, f"{area:.2f}", str(floor or ""), str(price), dong])
    return Sale(
        key=key,
        apt_seq=apt_seq,
        apt_name=apt_name,
        umd=umd,
        jibun=jibun,
        road_name=_text(item, "roadNm", "도로명"),
        area=area,
        floor=floor,
        dong=dong,
        price=price,
        date=date,
        build_year=_int(_text(item, "buildYear", "건축년도")),
        dealing=_text(item, "dealingGbn", "거래유형"),
        cancelled=_text(item, "cdealType", "해제여부").upper() == "O",
        cancel_date=_short_date(_text(item, "cdealDay", "해제사유발생일")),
        registered=_short_date(_text(item, "rgstDate", "등기일자")),
        sgg_code=_text(item, "sggCd", "지역코드"),
    )


def parse_sales(xml_text: str) -> tuple[list[Sale], int]:
    items, total = parse_envelope(xml_text)
    sales = [s for s in (parse_sale_item(i) for i in items) if s]
    return sales, total


# ---------- 전월세 ----------

def parse_rent_item(item: ET.Element) -> Rent | None:
    area = _float(_text(item, "excluUseAr", "전용면적"))
    if area is None:
        return None
    umd = _text(item, "umdNm", "법정동")
    jibun = _text(item, "jibun", "지번")
    date = _date(_text(item, "dealYear", "년"), _text(item, "dealMonth", "월"), _text(item, "dealDay", "일"))
    floor = _int(_text(item, "floor", "층"))
    deposit = _money(_text(item, "deposit", "보증금액"))
    monthly = _money(_text(item, "monthlyRent", "월세금액"))
    key = "|".join([umd, jibun, date, f"{area:.2f}", str(floor or ""), str(deposit), str(monthly)])
    return Rent(
        key=key,
        apt_name=_text(item, "aptNm", "아파트"),
        umd=umd,
        jibun=jibun,
        area=area,
        floor=floor,
        deposit=deposit,
        monthly=monthly,
        date=date,
        build_year=_int(_text(item, "buildYear", "건축년도")),
        contract_type=_text(item, "contractType", "계약구분"),
        term=_text(item, "contractTerm", "계약기간"),
        renewal_right=_text(item, "useRRRight", "갱신요구권사용"),
        sgg_code=_text(item, "sggCd", "지역코드"),
    )


def parse_rents(xml_text: str) -> tuple[list[Rent], int]:
    items, total = parse_envelope(xml_text)
    rents = [r for r in (parse_rent_item(i) for i in items) if r]
    return rents, total


# ---------- 호출 ----------

def _fetch_all(url: str, service_key: str, lawd_cd: str, deal_ymd: str, parser) -> list:
    results: list = []
    page = 1
    while True:
        params = {
            "serviceKey": service_key,
            "LAWD_CD": lawd_cd,
            "DEAL_YMD": deal_ymd,
            "pageNo": page,
            "numOfRows": config.PAGE_SIZE,
        }
        resp = get(url, params)
        if resp.status_code != 200:
            raise ApiError(f"HTTP {resp.status_code} from {url.rsplit('/', 1)[-1]}: {describe_error(resp.text)}")
        parsed, total = parser(resp.text)
        results.extend(parsed)
        if len(parsed) == 0 or len(results) >= total or page * config.PAGE_SIZE >= total:
            break
        page += 1
    log.info("%s %s %s -> %d건", url.rsplit("/", 1)[-1], lawd_cd, deal_ymd, len(results))
    return results


def fetch_sales(service_key: str, lawd_cd: str, deal_ymd: str) -> list[Sale]:
    return _fetch_all(config.MOLIT_SALE_URL, service_key, lawd_cd, deal_ymd, parse_sales)


def fetch_rents(service_key: str, lawd_cd: str, deal_ymd: str) -> list[Rent]:
    return _fetch_all(config.MOLIT_RENT_URL, service_key, lawd_cd, deal_ymd, parse_rents)
