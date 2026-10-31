"""단지 마스터(data/complexes.json) 생성.

1) K-apt 단지 목록(시군구별) → 2) 기본정보(세대수·주소) → 3) 세대수·법정동 필터 → 4) 좌표 변환.
이미 있는 단지의 좌표는 다시 조회하지 않는다.
"""
from __future__ import annotations

import logging

from . import config
from .geocode import geocode_complex
from .kapt_api import fetch_basic, fetch_list
from .store import now_iso, read_json, write_json

log = logging.getLogger(__name__)


def build(service_key: str, kakao_rest_key: str | None, geocode: bool = True) -> list[dict]:
    existing = {c["kapt_code"]: c for c in read_json(config.COMPLEXES_FILE, {}).get("complexes", [])}
    result: list[dict] = []
    skipped: dict[str, int] = {"households": 0, "umd": 0, "no_basic": 0}

    for region in config.REGIONS:
        listed = fetch_list(service_key, region.code)
        for entry in listed:
            code = entry["kapt_code"]
            # 목록 단계에서 법정동(as3)으로 1차 필터 (예: 염창동만)
            if entry.get("as3") and not region.accepts_umd(entry["as3"]):
                skipped["umd"] += 1
                continue
            basic = fetch_basic(service_key, code)
            if basic is None:
                skipped["no_basic"] += 1
                log.warning("기본정보 없음: %s %s", code, entry.get("name"))
                continue
            if basic.households < config.MIN_HOUSEHOLDS:
                skipped["households"] += 1
                continue
            umd = basic.umd or entry.get("as3", "")
            if not region.accepts_umd(umd):
                skipped["umd"] += 1
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
            prev = existing.get(code)
            if prev:
                record["lat"], record["lng"] = prev.get("lat"), prev.get("lng")
                record["apt_seqs"] = prev.get("apt_seqs", [])
            result.append(record)

    if geocode and kakao_rest_key:
        for record in result:
            if record["lat"] is not None:
                continue
            coords = geocode_complex(kakao_rest_key, record["road_address"], record["address"], record["name"], record["sgg_name"])
            if coords:
                record["lat"], record["lng"] = coords
            else:
                log.warning("좌표 변환 실패: %s %s", record["name"], record["address"])

    result.sort(key=lambda r: (r["sgg_code"], r["umd"], r["name"]))
    write_json(config.COMPLEXES_FILE, {"generated_at": now_iso(), "count": len(result), "skipped": skipped, "complexes": result})
    log.info("단지 마스터 %d개 저장 (제외: %s)", len(result), skipped)
    return result
