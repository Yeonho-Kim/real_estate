"""카카오 로컬 API: 주소 → 좌표 변환, 단지의 카카오맵 장소 찾기."""
from __future__ import annotations

import difflib
import logging
import re

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


# ---------- 카카오맵 장소 (단지 패널의 카카오맵 링크가 장소 페이지로 바로 가도록) ----------

PLACE_RADIUS = 500          # 단지 좌표에서 이 거리(m) 안의 장소만 본다
PLACE_NEAR = 150            # 주소가 달라도 이 거리 안이고 이름이 비슷하면 같은 단지로 본다
_ROAD_TAIL = re.compile(r"(\S+(?:로|길))\s+(\d+(?:-\d+)?)\s*$")
_NAME_NOISE = re.compile(r"\(.*?\)|아파트|관리사무소|\s")


def _road_key(address: str) -> str:
    """'서울 마포구 마포대로4라길 30' → '마포대로4라길 30'"""
    m = _ROAD_TAIL.search((address or "").strip())
    return f"{m.group(1)} {m.group(2)}" if m else ""


def _plain(name: str) -> str:
    return _NAME_NOISE.sub("", name or "").lower()


def is_apartment_place(doc: dict) -> bool:
    """카카오 장소 분류가 아파트 단지인지. (관리사무소·상가·경로당 등은 제외)"""
    category = doc.get("category_name") or ""
    return category.rstrip().endswith("아파트") and "주거시설" in category


def pick_place(docs: list[dict], name: str, road_address: str) -> dict | None:
    """검색 결과에서 이 단지에 해당하는 장소를 고른다. 확실하지 않으면 None.

    1순위: 도로명 주소가 같은 아파트. 2순위: 150m 안에 있고 이름이 비슷한 아파트.
    """
    want_road = _road_key(road_address)
    target = _plain(name)
    best, best_score = None, (0, 0.0)
    for doc in docs:
        if not is_apartment_place(doc) or not doc.get("id"):
            continue
        ratio = difflib.SequenceMatcher(None, target, _plain(doc.get("place_name", ""))).ratio() if target else 0.0
        try:
            distance = float(doc.get("distance") or 1e9)
        except ValueError:
            distance = 1e9
        same_road = bool(want_road) and _road_key(doc.get("road_address_name", "")) == want_road
        if same_road:
            score = (2, ratio)
        elif distance <= PLACE_NEAR and ratio >= 0.6:
            score = (1, ratio)
        else:
            continue
        if score > best_score:
            best, best_score = doc, score
    return best


def find_kakao_place(rest_key: str, name: str, road_address: str, lat: float, lng: float) -> dict | None:
    """단지의 카카오맵 장소. 반환: {"id": 장소번호, "name": 장소명} 또는 None.

    단지명으로 먼저 찾고, 없으면 주변의 '아파트' 를 훑어 도로명 주소가 같은 곳을 찾는다
    (K-apt 이름과 카카오 장소명이 다른 경우. 예: 흑석자이 / 흑석리버파크자이).
    """
    if lat is None or lng is None:
        return None
    clean = re.sub(r"\(.*?\)|관리사무소", "", name or "").strip()
    for query, sort in ((clean, "accuracy"), ("아파트", "distance")):
        if not query:
            continue
        params = {"query": query, "x": lng, "y": lat, "radius": PLACE_RADIUS, "sort": sort, "size": 15}
        resp = get(config.KAKAO_KEYWORD_URL, params, headers=_headers(rest_key))
        if resp.status_code != 200:
            log.warning("kakao place %s -> HTTP %s %s", query, resp.status_code, resp.text[:120])
            continue
        found = pick_place(resp.json().get("documents") or [], name, road_address)
        if found:
            return {"id": str(found["id"]), "name": found.get("place_name", "")}
    return None
