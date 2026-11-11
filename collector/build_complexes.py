"""단지 마스터(data/complexes.json) 생성.

1) K-apt 단지 목록(시군구별) → 2) 기본정보(세대수·주소) → 3) 세대수·법정동 필터 → 4) 좌표 변환.
이미 있는 단지의 좌표는 다시 조회하지 않는다.
제외한 단지와 그 이유는 data/complexes_skipped.json 에 남긴다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from . import config
from .geocode import geocode_complex
from .kapt_api import fetch_basic, fetch_list
from .store import now_iso, read_json, write_json

log = logging.getLogger(__name__)


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


def build(service_key: str, kakao_rest_key: str | None, geocode: bool = True) -> list[dict]:
    existing = {c["kapt_code"]: c for c in read_json(config.COMPLEXES_FILE, {}).get("complexes", [])}
    result: list[dict] = []
    skipped_items: list[dict] = []
    listed: dict[str, int] = {}

    # 1) 목록 + 법정동(as3) 1차 필터 (예: 강서구는 염창동만)
    todo: list[tuple] = []
    for region in config.REGIONS:
        entries = fetch_list(service_key, region.code)
        listed[region.name] = len(entries)
        for entry in entries:
            if entry.get("as3") and not region.accepts_umd(entry["as3"]):
                skipped_items.append(_skip(entry, region, "umd"))
            else:
                todo.append((region, entry))

    # 2) 기본정보는 느려서(건당 1~2초) 몇 개씩 동시에 받는다.
    def load(pair):
        return fetch_basic(service_key, pair[1]["kapt_code"])

    with ThreadPoolExecutor(max_workers=max(1, config.BASIC_WORKERS)) as pool:
        basics = list(pool.map(load, todo))

    # 3) 세대수·법정동 필터
    for (region, entry), basic in zip(todo, basics):
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
        prev = existing.get(entry["kapt_code"])
        if prev:
            record["lat"], record["lng"] = prev.get("lat"), prev.get("lng")
            record["apt_seqs"] = prev.get("apt_seqs", [])
        result.append(record)

    # 4) 좌표
    if geocode and kakao_rest_key:
        for record in result:
            if record["lat"] is not None:
                continue
            coords = geocode_complex(kakao_rest_key, record["road_address"], record["address"], record["name"], record["sgg_name"])
            if coords:
                record["lat"], record["lng"] = coords
            else:
                log.warning("좌표 변환 실패: %s %s", record["name"], record["address"])

    skipped = {"households": 0, "umd": 0, "no_basic": 0}
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
        "note": "단지 마스터에서 제외한 단지. reason: households=세대수 미달, umd=대상 동이 아님, no_basic=기본정보 없음",
        "min_households": config.MIN_HOUSEHOLDS,
        "items": skipped_items,
    })
    log.info("단지 목록 %s → 마스터 %d개 저장 (제외: %s)", listed, len(result), skipped)
    return result
