"""카카오 로컬 API로 주소 → 좌표 변환."""
from __future__ import annotations

import logging

from . import config
from .http import get

log = logging.getLogger(__name__)


def _headers(rest_key: str) -> dict:
    return {"Authorization": f"KakaoAK {rest_key}"}


def geocode_address(rest_key: str, address: str) -> tuple[float, float] | None:
    """주소 검색. 성공 시 (lat, lng)."""
    if not address:
        return None
    resp = get(config.KAKAO_ADDRESS_URL, {"query": address, "size": 1}, headers=_headers(rest_key))
    if resp.status_code != 200:
        log.warning("kakao address %s -> HTTP %s %s", address, resp.status_code, resp.text[:120])
        return None
    docs = resp.json().get("documents") or []
    if not docs:
        return None
    return float(docs[0]["y"]), float(docs[0]["x"])


def geocode_keyword(rest_key: str, keyword: str) -> tuple[float, float] | None:
    """장소명(단지명) 검색. 성공 시 (lat, lng)."""
    if not keyword:
        return None
    resp = get(config.KAKAO_KEYWORD_URL, {"query": keyword, "size": 1}, headers=_headers(rest_key))
    if resp.status_code != 200:
        log.warning("kakao keyword %s -> HTTP %s", keyword, resp.status_code)
        return None
    docs = resp.json().get("documents") or []
    if not docs:
        return None
    return float(docs[0]["y"]), float(docs[0]["x"])


def geocode_complex(rest_key: str, road_address: str, lot_address: str, name: str, sgg_name: str) -> tuple[float, float] | None:
    """도로명 → 지번 → 단지명 순서로 시도."""
    for query in (road_address, lot_address):
        coords = geocode_address(rest_key, _strip_building(query))
        if coords:
            return coords
    return geocode_keyword(rest_key, f"서울 {sgg_name} {name}")


def _strip_building(address: str) -> str:
    """'서울특별시 마포구 아현동 777 마포래미안푸르지오' 처럼 뒤에 붙은 건물명을 떼어 낸다.

    카카오 주소 검색은 지번/도로명 번호까지만 있을 때 더 잘 맞는다.
    """
    tokens = (address or "").split()
    out = []
    seen_number = False
    for tok in tokens:
        out.append(tok)
        if any(ch.isdigit() for ch in tok) and not tok.endswith(("로", "길", "구", "동", "시")):
            seen_number = True
            break
    return " ".join(out) if seen_number else (address or "")
