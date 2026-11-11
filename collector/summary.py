"""지도 마커용 요약(data/summary.json) 생성."""
from __future__ import annotations

import os
import re
from collections import Counter
from datetime import date, timedelta

from . import config
from .store import now_iso, now_kst, read_json, write_json


def _avg(values: list[int]) -> int | None:
    return round(sum(values) / len(values)) if values else None


def _months_ago(months: int, today: date) -> str:
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}-01"


def bucket_stats(sales: list[dict], rents: list[dict], today: date | None = None) -> dict:
    today = today or now_kst().date()
    w = config.SUMMARY_WINDOW_MONTHS
    cur_from = _months_ago(w, today)
    prev_from = _months_ago(2 * w, today)
    out: dict[str, dict] = {}
    for label, _, _ in config.TYPE_BUCKETS:
        s_valid = [s for s in sales if config.type_bucket(s["area"]) == label and not s["cancelled"]]
        cur = [s["price"] for s in s_valid if s["date"] >= cur_from]
        prev = [s["price"] for s in s_valid if prev_from <= s["date"] < cur_from]
        jeonse = [r["deposit"] for r in rents if config.type_bucket(r["area"]) == label and r["monthly"] == 0 and r["date"] >= cur_from]
        cur_avg, prev_avg, jeonse_avg = _avg(cur), _avg(prev), _avg(jeonse)
        last = s_valid[0] if s_valid else None  # 날짜 내림차순 저장됨
        change = None
        if cur_avg and prev_avg:
            change = round((cur_avg - prev_avg) / prev_avg * 100, 1)
        if not s_valid and not jeonse:
            continue
        out[label] = {
            "avg": cur_avg,
            "count": len(cur),
            "prev_avg": prev_avg,
            "change_pct": change,
            "last_price": last["price"] if last else None,
            "last_date": last["date"] if last else None,
            "last_floor": last["floor"] if last else None,
            "jeonse_avg": jeonse_avg,
            "jeonse_count": len(jeonse),
            "jeonse_ratio": round(jeonse_avg / cur_avg * 100) if (jeonse_avg and cur_avg) else None,
        }
    return out


_PAREN = re.compile(r"\(.*?\)|\[.*?\]")


def _clean(name: str) -> str:
    out = _PAREN.sub("", name or "")
    out = re.sub(r"관리사무소|아파트", "", out)
    return " ".join(out.split()).strip()


def search_name(kapt_name: str, trade_names: list[str]) -> str:
    """지도·부동산 앱에서 검색할 때 쓸 단지명.

    K-apt 이름과 실거래 자료의 이름 가운데 더 구체적인(긴) 쪽을 쓴다.
    - K-apt "흑석자이" 보다 실거래 "흑석리버파크자이" 가 실제로 통하는 이름이다.
    - 반대로 실거래 "우성", "현대" 는 너무 짧아 K-apt "노량진우성" 이 낫다.
    실거래 이름이 단지별로 여럿이면(…1단지, …2단지) 공통 앞부분을 쓴다.
    """
    kapt = _clean(kapt_name)
    cleaned = [c for c in (_clean(n) for n in trade_names) if c]
    if not cleaned:
        return kapt
    distinct = list(dict.fromkeys(cleaned))
    if len(distinct) > 1:
        prefix = os.path.commonprefix(distinct).strip()
        trade = prefix if len(prefix) >= 4 else Counter(cleaned).most_common(1)[0][0]
    else:
        trade = distinct[0]
    return trade if len(trade.replace(" ", "")) > len(kapt.replace(" ", "")) else kapt


def short_address(road_address: str) -> str:
    """'서울특별시 마포구 마포대로 195' → '마포구 마포대로 195'"""
    return re.sub(r"^서울(특별시)?\s*", "", (road_address or "").strip())


def build_summary(complexes: list[dict], events: list[dict]) -> dict:
    new_counts: dict[str, int] = {}
    for e in events:
        if e["type"] in ("new_sale", "new_rent"):
            new_counts[e["kapt_code"]] = new_counts.get(e["kapt_code"], 0) + 1
    recent_cut = (now_kst().date() - timedelta(days=14)).isoformat()
    items = []
    for c in complexes:
        trades = read_json(config.TRADES_DIR / f"{c['kapt_code']}.json", {"sales": [], "rents": []})
        sales, rents = trades.get("sales", []), trades.get("rents", [])
        stats = bucket_stats(sales, rents)
        latest_sale = next((s for s in sales if not s["cancelled"]), None)
        items.append({
            "kapt_code": c["kapt_code"],
            "name": c["name"],
            "search_name": search_name(c["name"], [r["apt_name"] for r in (sales or rents)]),
            "addr": short_address(c.get("road_address", "")),
            "kakao_place_id": c.get("kakao_place_id") or "",
            "sgg": c["sgg_name"],
            "umd": c["umd"],
            "lat": c.get("lat"),
            "lng": c.get("lng"),
            "households": c["households"],
            "approved": c.get("approved", ""),
            "area_85": c.get("area_85"),
            "sale_count": sum(1 for s in sales if not s["cancelled"]),
            "rent_count": len(rents),
            "last_sale_date": latest_sale["date"] if latest_sale else None,
            "recent_sales_14d": sum(1 for s in sales if not s["cancelled"] and s["date"] >= recent_cut),
            "new_events": new_counts.get(c["kapt_code"], 0),
            "types": stats,
        })
    summary = {
        "generated_at": now_iso(),
        "regions": [{"code": r.code, "name": r.name, "umd_filter": list(r.umd_filter)} for r in config.REGIONS],
        "filters": {"min_households": config.MIN_HOUSEHOLDS, "area_min": config.AREA_MIN, "area_max": config.AREA_MAX},
        "complexes": items,
    }
    write_json(config.SUMMARY_FILE, summary, compact=True)
    return summary
