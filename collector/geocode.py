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


GEO_VERSION = 2  # 좌표 구하는 방식이 바뀌면 올린다. 다음 "단지 마스터 다시 만들기"에서 전부 다시 구한다.

_ROAD = re.compile(r"(\S+(?:로|길))\s+(\d+(?:-\d+)?)")


def split_road(address: str) -> tuple[str, str]:
    """'서울특별시 영등포구 양평동1가 선유서로24길 6' → ('선유서로24길', '6'). 못 찾으면 ('', '').

    K-apt 도로명 주소에는 동 이름(양평동1가, 충정로3가)이 끼어 있기도 해서, 도로명과 건물번호만 뽑아 쓴다.
    """
    found = _ROAD.findall(address or "")
    return found[-1] if found else ("", "")


def _number(main, sub) -> str:
    main, sub = str(main or "").strip(), str(sub or "").strip()
    return f"{main}-{sub}" if main and sub and sub != "0" else main


def _search(rest_key: str, url: str, params: dict) -> list[dict]:
    resp = get(url, params, headers=_headers(rest_key))
    if resp.status_code != 200:
        log.warning("kakao %s %s -> HTTP %s %s", url.rsplit("/", 1)[-1], params.get("query"), resp.status_code, resp.text[:120])
        return []
    return resp.json().get("documents") or []


def geocode_road(rest_key: str, sgg_name: str, road: str, number: str) -> tuple[float, float] | None:
    """도로명 주소 → 좌표. 돌아온 결과의 구·도로명·건물번호가 같을 때만 인정한다."""
    if not road or not number:
        return None
    for doc in _search(rest_key, config.KAKAO_ADDRESS_URL, {"query": f"서울 {sgg_name} {road} {number}", "size": 5}):
        ra = doc.get("road_address") or {}
        if (ra.get("region_2depth_name") == sgg_name and ra.get("road_name") == road
                and _number(ra.get("main_building_no"), ra.get("sub_building_no")) == number):
            return float(ra.get("y") or doc["y"]), float(ra.get("x") or doc["x"])
    return None


def geocode_lot(rest_key: str, sgg_name: str, umd: str, jibun: str) -> tuple[float, float] | None:
    """지번 주소 → 좌표. 돌아온 결과의 구·동·지번이 같을 때만 인정한다."""
    if not umd or not jibun:
        return None
    for doc in _search(rest_key, config.KAKAO_ADDRESS_URL, {"query": f"서울 {sgg_name} {umd} {jibun}", "size": 5}):
        ad = doc.get("address") or {}
        dong = ad.get("region_3depth_name") or ad.get("region_3depth_h_name") or ""
        if (ad.get("region_2depth_name") == sgg_name and dong == umd
                and _number(ad.get("main_address_no"), ad.get("sub_address_no")) == jibun):
            return float(ad.get("y") or doc["y"]), float(ad.get("x") or doc["x"])
    return None


def geocode_keyword(rest_key: str, sgg_name: str, name: str) -> tuple[float, float] | None:
    """마지막 수단: 단지명 검색. 구가 맞는 아파트 장소만 인정한다."""
    for doc in _search(rest_key, config.KAKAO_KEYWORD_URL, {"query": f"서울 {sgg_name} {name}", "size": 5}):
        if is_apartment_place(doc) and f" {sgg_name} " in f" {doc.get('address_name', '')} ":
            return float(doc["y"]), float(doc["x"])
    return None


def geocode_complex(rest_key: str, record: dict) -> tuple[float, float, str] | None:
    """단지의 주소 좌표. 반환: (위도, 경도, 출처) — 출처는 road / lot / keyword."""
    road, number = split_road(record.get("road_address", ""))
    sgg = record.get("sgg_name", "")
    coords = geocode_road(rest_key, sgg, road, number)
    if coords:
        return (*coords, "road")
    coords = geocode_lot(rest_key, sgg, record.get("umd", ""), record.get("jibun", ""))
    if coords:
        return (*coords, "lot")
    coords = geocode_keyword(rest_key, sgg, record.get("name", ""))
    if coords:
        return (*coords, "keyword")
    return None


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> int:
    """두 좌표 사이 거리(m). 수 km 이내에서 충분히 정확한 근사."""
    import math

    mean = math.radians((lat1 + lat2) / 2)
    dx = math.radians(lng2 - lng1) * math.cos(mean)
    dy = math.radians(lat2 - lat1)
    return round(6371000 * math.hypot(dx, dy))


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
    """단지의 카카오맵 장소. 반환: {"id", "name", "lat", "lng", "same_road"} 또는 None.

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
            return {
                "id": str(found["id"]), "name": found.get("place_name", ""),
                "lat": float(found["y"]), "lng": float(found["x"]),
                "same_road": bool(_road_key(road_address)) and _road_key(found.get("road_address_name", "")) == _road_key(road_address),
            }
    return None
