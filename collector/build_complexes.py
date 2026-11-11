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
from .geocode import geocode_complex
from .http import QuotaExceeded
from .kapt_api import fetch_basic, fetch_list
from .store import now_iso, read_json, write_json

log = logging.getLogger(__name__)

REASONS = ("households", "umd", "no_basic", "not_fetched")
_QUOTA = object()


def _skip(entry: dict, region, reason: str, basic=None) -> dict:
    return {
        "kapt_code": entry["kapt_code"],
        "name": (basic.name if basic else "") or entry.get("name", ""),
        "sgg_name": region.name,
        "umd": (basic.umd if basic else "") or entry.get("as3", ""),
        "households": basic.households if basic else None,
        "ho_count": basic.ho_count if basic else None,
        "address": basic.address if basic else "",
        "reason": reason,
    }


def build(service_key: str, kakao_rest_key: str | None, geocode: bool = True, full: bool = False) -> list[dict]:
    existing = {} if full else {c["kapt_code"]: c for c in read_json(config.COMPLEXES_FILE, {}).get("complexes", [])}
    known_small = {} if full else {
        i["kapt_code"]: i
        for i in read_json(config.COMPLEXES_SKIPPED_FILE, {}).get("items", [])
        if i.get("reason") == "households" and i.get("households") is not None and i["households"] < config.MIN_HOUSEHOLDS
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
                result.append(record)
            elif code in known_small:
                skipped_items.append(dict(known_small[code]))
            else:
                todo.append((region, entry))
    log.info("단지 목록 %s | 재사용 %d, 이미 확인된 세대수 미달 %d, 새로 조회 %d",
             listed, len(result), sum(1 for i in skipped_items if i["reason"] == "households"), len(todo))

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
        if basic.households < config.MIN_HOUSEHOLDS:
            skipped_items.append(_skip(entry, region, "households", basic))
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

    # 4) 좌표
    if geocode and kakao_rest_key:
        for record in result:
            if record.get("lat") is not None:
                continue
            coords = geocode_complex(kakao_rest_key, record["road_address"], record["address"], record["name"], record["sgg_name"])
            if coords:
                record["lat"], record["lng"] = coords
            else:
                log.warning("좌표 변환 실패: %s %s", record["name"], record["address"])

    skipped = dict.fromkeys(REASONS, 0)
    for item in skipped_items:
        skipped[item["reason"]] += 1

    result.sort(key=lambda r: (r["sgg_code"], r["umd"], r["name"]))
    write_json(config.COMPLEXES_FILE, {
        "generated_at": now_iso(), "count": len(result), "listed": listed, "skipped": skipped, "complexes": result,
    })
    # 세대수 미달은 큰 것부터 보이게 정렬 (300세대 근처에서 잘못 빠진 단지를 찾기 쉽도록)
    skipped_items.sort(key=lambda i: (i["reason"], i["sgg_name"], -(i["households"] or 0), i["name"]))
    write_json(config.COMPLEXES_SKIPPED_FILE, {
        "generated_at": now_iso(),
        "note": "단지 마스터에서 제외한 단지. reason: households=세대수 미달, umd=대상 동이 아님, "
                "no_basic=기본정보 없음, not_fetched=일일 한도 초과로 아직 확인 못함(다음 실행에서 이어서 받음)",
        "min_households": config.MIN_HOUSEHOLDS,
        "items": skipped_items,
    })
    log.info("마스터 %d개 저장 (제외: %s)", len(result), skipped)
    if skipped["not_fetched"]:
        log.warning("일일 한도 때문에 %d개 단지를 확인하지 못했습니다. 내일 '단지 마스터 다시 만들기'로 다시 실행하면 이어서 받습니다.",
                    skipped["not_fetched"])
    return result
