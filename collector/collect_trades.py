"""실거래(매매·전월세) 수집 → 필터 → 단지 매칭 → data/trades/{kaptCode}.json 저장."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict

from . import config
from .matching import ComplexIndex
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


def collect(service_key: str, months: list[str] | None = None) -> dict:
    """반환: {"months": [...], "fetched": {"sales": [...], "rents": [...]} , "by_complex": {...}}"""
    complexes = load_complexes()
    if not complexes:
        raise RuntimeError("data/complexes.json 이 없습니다. 먼저 `python -m collector.main complexes` 를 실행하세요.")
    overrides = read_json(config.OVERRIDES_FILE, {})
    index = ComplexIndex(complexes, overrides)

    if months is None:
        first_run = not config.STATE_FILE.exists()
        months = month_list(config.BACKFILL_MONTHS if first_run else config.REFRESH_MONTHS)
    month_set = set(months)

    sales_by: dict[str, list[dict]] = defaultdict(list)
    rents_by: dict[str, list[dict]] = defaultdict(list)
    unmatched: Counter = Counter()
    stats = Counter()

    for region in config.REGIONS:
        for ym in months:
            for sale in fetch_sales(service_key, region.code, ym):
                stats["sales_raw"] += 1
                if not region.accepts_umd(sale.umd) or not config.in_area_range(sale.area):
                    continue
                stats["sales_filtered"] += 1
                c = index.match(sale.umd, sale.jibun, sale.apt_name, sale.apt_seq)
                if c is None:
                    unmatched[f"{region.name}|{sale.umd}|{sale.jibun}|{sale.apt_name}"] += 1
                    continue
                sales_by[c["kapt_code"]].append(sale.to_dict())
            for rent in fetch_rents(service_key, region.code, ym):
                stats["rents_raw"] += 1
                if not region.accepts_umd(rent.umd) or not config.in_area_range(rent.area):
                    continue
                stats["rents_filtered"] += 1
                c = index.match(rent.umd, rent.jibun, rent.apt_name)
                if c is None:
                    unmatched[f"{region.name}|{rent.umd}|{rent.jibun}|{rent.apt_name}"] += 1
                    continue
                rents_by[c["kapt_code"]].append(rent.to_dict())

    # 저장 (매칭 과정에서 학습된 aptSeq 도 함께 저장)
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
    write_json(config.COMPLEXES_FILE, master)

    write_json(config.UNMATCHED_FILE, {
        "updated_at": now_iso(),
        "note": "세대수 300 미만 단지는 매칭되지 않는 것이 정상. 300 이상인데 여기 있으면 collector/overrides.json 에 aptSeq→kaptCode 를 추가.",
        "items": [{"where": k, "count": v} for k, v in unmatched.most_common()],
    })
    log.info("수집 통계: %s, 미매칭 %d종", dict(stats), len(unmatched))
    return {"months": months, "sales_by": dict(sales_by), "rents_by": dict(rents_by), "stats": dict(stats)}
