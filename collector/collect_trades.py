"""실거래(매매·전월세) 수집 → 필터 → 단지 매칭 → data/trades/{kaptCode}.json 저장."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict

from . import config
from .matching import MATCH_VERSION, ComplexIndex
from .molit_api import fetch_rents, fetch_sales
from .store import month_list, now_iso, read_json, write_json

log = logging.getLogger(__name__)


def load_complexes() -> list[dict]:
    return read_json(config.COMPLEXES_FILE, {}).get("complexes", [])


def load_trades(kapt_code: str) -> dict:
    return read_json(config.TRADES_DIR / f"{kapt_code}.json", {"kapt_code": kapt_code, "sales": [], "rents": []})


def _month_of(date: str) -> str:
    return date.replace("-", "")[:6]


def merge_records(existing: list[dict], fresh: list[dict], refreshed_months: set[str]) -> list[dict]:
    """다시 받은 달의 기존 레코드는 버리고 새 데이터로 바꾼다. 나머지 달은 유지."""
    kept = [r for r in existing if _month_of(r["date"]) not in refreshed_months]
    seen = {r["key"] for r in kept}
    for r in fresh:
        if r["key"] in seen:
            continue
        seen.add(r["key"])
        kept.append(r)
    kept.sort(key=lambda r: (r["date"], r.get("floor") or 0), reverse=True)
    return kept


def needs_rematch() -> bool:
    """연결 규칙이 바뀌어 저장된 연결을 버려야 하는지."""
    master = read_json(config.COMPLEXES_FILE, {})
    return bool(master.get("complexes")) and master.get("match_version") != MATCH_VERSION


def collect(service_key: str, months: list[str] | None = None, rematch: bool = False) -> dict:
    """실거래를 받아 단지에 연결하고 저장한다.

    rematch=True 면 저장된 연결을 버리고 전체 기간을 다시 받는다.
    반환: {"months": [...], "sales_by": {...}, "rents_by": {...}, "stats": {...}}
    """
    complexes = load_complexes()
    if not complexes:
        raise RuntimeError("data/complexes.json 이 없습니다. 먼저 `python -m collector.main complexes` 를 실행하세요.")
    overrides = read_json(config.OVERRIDES_FILE, {})
    index = ComplexIndex(complexes, overrides)
    if rematch:
        index.reset_learned()

    if months is None:
        full = rematch or not config.STATE_FILE.exists()
        months = month_list(config.BACKFILL_MONTHS if full else config.REFRESH_MONTHS)
    month_set = set(months)

    # 1) 먼저 전부 받는다.
    sales, rents = [], []
    for region in config.REGIONS:
        for ym in months:
            sales += [(region, s) for s in fetch_sales(service_key, region.code, ym)]
            rents += [(region, r) for r in fetch_rents(service_key, region.code, ym)]

    sales_by: dict[str, list[dict]] = defaultdict(list)
    rents_by: dict[str, list[dict]] = defaultdict(list)
    unmatched: dict[str, dict] = {}
    stats = Counter(sales_raw=len(sales), rents_raw=len(rents))

    def note_unmatched(region, rec, kind: str) -> None:
        """연결 못 한 거래를 단지별로 모은다. 수동 지정(overrides.json)에 필요한 값도 함께 남긴다."""
        key = f"{region.name}|{rec.umd}|{rec.jibun}|{rec.apt_name}"
        item = unmatched.setdefault(key, {
            "where": key, "count": 0, "sales": 0, "rents": 0, "apt_seq": "",
            "road": "", "build_year": rec.build_year,
        })
        item["count"] += 1
        item[kind] += 1
        if getattr(rec, "apt_seq", "") and not item["apt_seq"]:
            item["apt_seq"] = rec.apt_seq
        if rec.road_name and not item["road"]:
            item["road"] = f"{rec.road_name} {rec.road_no}".strip()

    # 2) 매매를 먼저 연결한다. 매매에는 일련번호·도로명이 있어 확실하고, 여기서 확정된 지번을 전월세가 따라간다.
    for region, sale in sales:
        if not region.accepts_umd(sale.umd) or not config.in_area_range(sale.area):
            continue
        stats["sales_filtered"] += 1
        c = index.match(sale.umd, sale.jibun, sale.apt_name, sale.apt_seq, sale.build_year, sale.road_name, sale.road_no)
        if c is None:
            note_unmatched(region, sale, "sales")
            continue
        sales_by[c["kapt_code"]].append(sale.to_dict())
    for region, rent in rents:
        if not region.accepts_umd(rent.umd) or not config.in_area_range(rent.area):
            continue
        stats["rents_filtered"] += 1
        c = index.match(rent.umd, rent.jibun, rent.apt_name, "", rent.build_year, rent.road_name, rent.road_no)
        if c is None:
            note_unmatched(region, rent, "rents")
            continue
        rents_by[c["kapt_code"]].append(rent.to_dict())
    stats["sales_matched"] = sum(len(v) for v in sales_by.values())
    stats["rents_matched"] = sum(len(v) for v in rents_by.values())

    # 3) 저장 (연결 과정에서 확정된 aptSeq·지번도 함께 저장)
    for c in complexes:
        code = c["kapt_code"]
        if code not in sales_by and code not in rents_by and not (config.TRADES_DIR / f"{code}.json").exists():
            continue
        existing = load_trades(code)
        data = {
            "kapt_code": code,
            "name": c["name"],
            "updated_at": now_iso(),
            "sales": merge_records(existing.get("sales", []), sales_by.get(code, []), month_set),
            "rents": merge_records(existing.get("rents", []), rents_by.get(code, []), month_set),
        }
        write_json(config.TRADES_DIR / f"{code}.json", data, compact=True)

    master = read_json(config.COMPLEXES_FILE, {})
    master["complexes"] = complexes
    master["match_version"] = MATCH_VERSION
    write_json(config.COMPLEXES_FILE, master)

    write_json(config.UNMATCHED_FILE, {
        "updated_at": now_iso(),
        "note": "단지에 연결하지 못한 거래. 300세대 미만 단지면 정상(data/complexes_skipped.json 에서 확인). "
                "300세대 이상인데 여기 있으면 collector/overrides.json 에 \"apt_seq 값\": \"단지코드\" 를 추가한다 "
                "(단지코드는 data/complexes.json). road 는 거래 자료의 도로명 주소.",
        "items": sorted(unmatched.values(), key=lambda i: -i["count"]),
    })
    log.info("수집 통계: %s, 미매칭 %d종", dict(stats), len(unmatched))
    return {"months": months, "sales_by": dict(sales_by), "rents_by": dict(rents_by), "stats": dict(stats)}
