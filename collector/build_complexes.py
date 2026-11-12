"""단지 마스터(data/complexes.json) 생성.

1) K-apt 단지 목록(시군구별) → 2) 기본정보(세대수·주소) → 3) 세대수·법정동 필터 → 4) 좌표 변환.

K-apt 기본정보 API 는 느리고(건당 1~2초) 일일 한도가 있어 호출을 아낀다.
- 이미 마스터에 있는 단지, 지난번에 세대수 미달로 확인된 단지는 다시 조회하지 않는다 (full=True 면 전부 다시 조회).
- 일일 한도를 넘으면 받은 데까지만 저장하고 나머지는 "not_fetched" 로 남긴다. 다음 실행에서 이어서 받는다.
제외한 단지와 그 이유는 data/complexes_skipped.json 에 남긴다.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from . import config
from .geocode import GEO_VERSION, distance_m, find_kakao_place, geocode_complex
from .http import QuotaExceeded
from .kapt_api import fetch_basic, fetch_list
from .store import now_iso, read_json, write_json

log = logging.getLogger(__name__)

REASONS = ("households", "rental", "umd", "no_basic", "not_fetched")
CACHED_REASONS = ("households", "rental")  # 기본정보를 이미 받아 판단이 끝난 경우
_QUOTA = object()


def _skip(entry: dict, region, reason: str, basic=None) -> dict:
    return {
        "kapt_code": entry["kapt_code"],
        "name": (basic.name if basic else "") or entry.get("name", ""),
        "sgg_name": region.name,
        "umd": (basic.umd if basic else "") or entry.get("as3", ""),
        "households": basic.households if basic else None,
        "ho_count": basic.ho_count if basic else None,
        "sale_type": basic.sale_type if basic else "",
        "address": basic.address if basic else "",
        "reason": reason,
    }


def _skip_record(record: dict, reason: str) -> dict:
    """이미 마스터에 있던 단지를 제외할 때 (예: 임대 단지 제외 규칙이 새로 생김)."""
    return {
        "kapt_code": record["kapt_code"], "name": record.get("name", ""), "sgg_name": record.get("sgg_name", ""),
        "umd": record.get("umd", ""), "households": record.get("households"), "ho_count": record.get("ho_count"),
        "sale_type": record.get("sale_type", ""), "address": record.get("address", ""), "reason": reason,
    }


def exclusion_reason(households: int | None, sale_type: str) -> str | None:
    """세대수·분양형태로 제외할지 판단. 제외하지 않으면 None."""
    if households is not None and households < config.MIN_HOUSEHOLDS:
        return "households"
    if (sale_type or "") in config.EXCLUDE_SALE_TYPES:
        return "rental"
    return None


def build(service_key: str, kakao_rest_key: str | None, geocode: bool = True, full: bool = False) -> list[dict]:
    existing = {} if full else {c["kapt_code"]: c for c in read_json(config.COMPLEXES_FILE, {}).get("complexes", [])}
    # 지난번에 기본정보를 받아 제외로 판단한 단지. 기준이 바뀌었을 수 있으니 판단은 지금 기준으로 다시 한다.
    known_skipped = {} if full else {
        i["kapt_code"]: i
        for i in read_json(config.COMPLEXES_SKIPPED_FILE, {}).get("items", [])
        if i.get("reason") in CACHED_REASONS and i.get("households") is not None
    }
    coords_cache = {c["kapt_code"]: c for c in read_json(config.COMPLEXES_FILE, {}).get("complexes", [])}

    result: list[dict] = []
    skipped_items: list[dict] = []
    listed: dict[str, int] = {}

    # 1) 목록 + 법정동(as3) 1차 필터 (예: 강서구는 염창동만). 이미 아는 단지는 조회하지 않는다.
    todo: list[tuple] = []
    for region in config.REGIONS:
        entries = fetch_list(service_key, region.code)
        listed[region.name] = len(entries)
        for entry in entries:
            code = entry["kapt_code"]
            if entry.get("as3") and not region.accepts_umd(entry["as3"]):
                skipped_items.append(_skip(entry, region, "umd"))
            elif code in existing:
                record = dict(existing[code])
                record.setdefault("ho_count", None)
                reason = exclusion_reason(record.get("households"), record.get("sale_type", ""))
                if reason:
                    skipped_items.append(_skip_record(record, reason))
                else:
                    result.append(record)
            elif code in known_skipped and exclusion_reason(known_skipped[code]["households"], known_skipped[code].get("sale_type", "")):
                item = dict(known_skipped[code])
                item.setdefault("sale_type", "")
                item["reason"] = exclusion_reason(item["households"], item["sale_type"])
                skipped_items.append(item)
            else:
                todo.append((region, entry))
    log.info("단지 목록 %s | 재사용 %d, 이미 확인된 제외 %d, 새로 조회 %d",
             listed, len(result), sum(1 for i in skipped_items if i["reason"] in CACHED_REASONS), len(todo))

    # 2) 기본정보 조회. 일일 한도를 넘으면 남은 것은 건너뛴다.
    quota_hit = threading.Event()

    def load(pair):
        if quota_hit.is_set():
            return _QUOTA
        try:
            return fetch_basic(service_key, pair[1]["kapt_code"])
        except QuotaExceeded as exc:
            if not quota_hit.is_set():
                log.warning("K-apt 기본정보 일일 한도 초과: %s", exc)
            quota_hit.set()
            return _QUOTA

    workers = max(1, config.BASIC_WORKERS)
    if workers == 1:
        basics = []
        for n, pair in enumerate(todo, 1):
            basics.append(load(pair))
            if n % 50 == 0:
                log.info("기본정보 %d/%d", n, len(todo))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            basics = list(pool.map(load, todo))

    # 3) 세대수·법정동 필터
    for (region, entry), basic in zip(todo, basics):
        if basic is _QUOTA:
            skipped_items.append(_skip(entry, region, "not_fetched"))
            continue
        if basic is None:
            log.warning("기본정보 없음: %s %s", entry["kapt_code"], entry.get("name"))
            skipped_items.append(_skip(entry, region, "no_basic"))
            continue
        reason = exclusion_reason(basic.households, basic.sale_type)
        if reason:
            skipped_items.append(_skip(entry, region, reason, basic))
            continue
        umd = basic.umd or entry.get("as3", "")
        if not region.accepts_umd(umd):
            skipped_items.append(_skip(entry, region, "umd", basic))
            continue
        record = basic.to_dict()
        record.update({
            "umd": umd,
            "sgg_code": region.code,
            "sgg_name": region.name,
            "lat": None,
            "lng": None,
            "apt_seqs": [],
        })
        prev = coords_cache.get(entry["kapt_code"])
        if prev:
            record["lat"], record["lng"] = prev.get("lat"), prev.get("lng")
            record["apt_seqs"] = prev.get("apt_seqs", [])
        result.append(record)

    # 4) 좌표와 카카오맵 장소. 방식(GEO_VERSION)이 같고 이미 구한 단지는 건너뛴다.
    if geocode and kakao_rest_key:
        todo_geo = [r for r in result if full or r.get("lat") is None or r.get("geo_v") != GEO_VERSION]
        for record in todo_geo:
            locate(kakao_rest_key, record)
        sources = {}
        for r in result:
            sources[r.get("geo_source", "?")] = sources.get(r.get("geo_source", "?"), 0) + 1
        log.info("좌표: 이번에 %d곳 다시 구함, 출처별 %s, 카카오 장소 %d/%d",
                 len(todo_geo), sources, sum(1 for r in result if r.get("kakao_place_id")), len(result))

    skipped = dict.fromkeys(REASONS, 0)
    for item in skipped_items:
        skipped[item["reason"]] += 1

    result.sort(key=lambda r: (r["sgg_code"], r["umd"], r["name"]))
    master = {"generated_at": now_iso(), "count": len(result), "listed": listed, "skipped": skipped, "complexes": result}
    # 연결 규칙 버전을 지우면 다음 수집이 "규칙이 바뀌었다"고 보고 전체 기간을 다시 받는다. 그대로 넘긴다.
    previous_version = read_json(config.COMPLEXES_FILE, {}).get("match_version")
    if previous_version is not None:
        master["match_version"] = previous_version
    write_json(config.COMPLEXES_FILE, master)
    # 세대수 미달은 큰 것부터 보이게 정렬 (300세대 근처에서 잘못 빠진 단지를 찾기 쉽도록)
    skipped_items.sort(key=lambda i: (i["reason"], i["sgg_name"], -(i["households"] or 0), i["name"]))
    write_json(config.COMPLEXES_SKIPPED_FILE, {
        "generated_at": now_iso(),
        "note": "단지 마스터에서 제외한 단지. reason: households=세대수 미달, rental=임대 단지, umd=대상 동이 아님, "
                "no_basic=기본정보 없음, not_fetched=일일 한도 초과로 아직 확인 못함(다음 실행에서 이어서 받음)",
        "min_households": config.MIN_HOUSEHOLDS,
        "exclude_sale_types": list(config.EXCLUDE_SALE_TYPES),
        "items": skipped_items,
    })
    log.info("마스터 %d개 저장 (제외: %s)", len(result), skipped)
    removed = remove_orphan_trades({r["kapt_code"] for r in result})
    if removed:
        log.info("마스터에서 빠진 단지의 거래 파일 %d개를 지웠습니다.", removed)
    if skipped["not_fetched"]:
        log.warning("일일 한도 때문에 %d개 단지를 확인하지 못했습니다. 내일 '단지 마스터 다시 만들기'로 다시 실행하면 이어서 받습니다.",
                    skipped["not_fetched"])
    return result


def remove_orphan_trades(valid_codes: set[str]) -> int:
    """마스터에 없는 단지의 거래 파일을 지운다 (단지가 제외된 뒤 남은 파일)."""
    if not valid_codes or not config.TRADES_DIR.exists():
        return 0
    removed = 0
    for path in config.TRADES_DIR.glob("*.json"):
        if path.stem not in valid_codes:
            path.unlink()
            removed += 1
    return removed


def locate(kakao_rest_key: str, record: dict) -> None:
    """단지의 핀 좌표와 카카오맵 장소를 구해 record 에 적는다.

    1) 주소로 좌표를 구한다 (도로명 → 지번 → 단지명, 돌아온 주소가 맞을 때만 인정).
    2) 그 근처에서 카카오맵 장소를 찾는다.
    3) 핀은 장소 좌표에 둔다. 주소 좌표는 주소가 붙은 건물 한 동을 가리키지만,
       장소 좌표는 지도에 단지 이름이 표시되는 자리라 지도와 더 잘 맞는다. 장소가 없으면 주소 좌표.
    두 좌표 사이 거리(place_dist)를 남겨 나중에 점검할 수 있게 한다.
    """
    addr = geocode_complex(kakao_rest_key, record)
    if addr is None:
        log.warning("좌표 변환 실패: %s %s", record["name"], record.get("road_address"))
        record.setdefault("lat", None)
        record.setdefault("lng", None)
        record["geo_source"] = "none"
        return
    addr_lat, addr_lng, source = addr
    place = find_kakao_place(kakao_rest_key, record["name"], record["road_address"], addr_lat, addr_lng)
    record["addr_lat"], record["addr_lng"], record["addr_source"] = addr_lat, addr_lng, source
    record["kakao_place_id"] = place["id"] if place else ""
    record["kakao_place_name"] = place["name"] if place else ""
    if place:
        record["lat"], record["lng"] = place["lat"], place["lng"]
        record["geo_source"] = "place" if place["same_road"] else "place_near"
        record["place_dist"] = distance_m(addr_lat, addr_lng, place["lat"], place["lng"])
    else:
        record["lat"], record["lng"] = addr_lat, addr_lng
        record["geo_source"] = source
        record["place_dist"] = None
    if source != "road":
        log.warning("도로명 주소로 좌표를 못 구해 %s 로 대신함: %s %s", source, record["name"], record.get("road_address"))
    record["geo_v"] = GEO_VERSION
