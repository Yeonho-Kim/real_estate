"""이전 실행과 비교해 새 거래·해제를 찾아낸다."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import config
from .store import now_iso, now_kst, read_json, write_json


def load_state() -> dict:
    return read_json(config.STATE_FILE, {"last_run": None, "sale_keys": [], "rent_keys": [], "cancelled_keys": []})


def compute_events(state: dict, sales_by: dict[str, list[dict]], rents_by: dict[str, list[dict]], complexes: list[dict]) -> list[dict]:
    names = {c["kapt_code"]: c["name"] for c in complexes}
    known_sales = set(state.get("sale_keys", []))
    known_rents = set(state.get("rent_keys", []))
    known_cancelled = set(state.get("cancelled_keys", []))
    events: list[dict] = []

    for code, sales in sales_by.items():
        for s in sales:
            if s["key"] not in known_sales and not s["cancelled"]:
                events.append({"type": "new_sale", "kapt_code": code, "name": names.get(code, ""), "record": s})
            elif s["cancelled"] and s["key"] not in known_cancelled and s["key"] in known_sales:
                events.append({"type": "cancelled", "kapt_code": code, "name": names.get(code, ""), "record": s})
    for code, rents in rents_by.items():
        for r in rents:
            if r["key"] not in known_rents:
                events.append({"type": "new_rent", "kapt_code": code, "name": names.get(code, ""), "record": r})

    events.sort(key=lambda e: e["record"]["date"], reverse=True)
    return events


def update_state(state: dict, sales_by: dict, rents_by: dict) -> dict:
    sale_keys = set(state.get("sale_keys", []))
    rent_keys = set(state.get("rent_keys", []))
    cancelled = set(state.get("cancelled_keys", []))
    for sales in sales_by.values():
        for s in sales:
            sale_keys.add(s["key"])
            if s["cancelled"]:
                cancelled.add(s["key"])
    for rents in rents_by.values():
        for r in rents:
            rent_keys.add(r["key"])
    return {
        "last_run": now_iso(),
        "sale_keys": sorted(sale_keys),
        "rent_keys": sorted(rent_keys),
        "cancelled_keys": sorted(cancelled),
    }


RECENT_DAYS = 14          # "최근 변화"에 보여 줄 기간 (새로 발견한 날 기준)
SAME_TYPE_AREA = 1.5      # 전용면적 차이가 이 값(㎡) 미만이면 같은 평형으로 본다
SALE_EVENT_TYPES = ("new_sale", "cancelled")


def _sales_of(kapt_code: str) -> list[dict]:
    return read_json(config.TRADES_DIR / f"{kapt_code}.json", {}).get("sales", [])


def previous_sale(sales: list[dict], record: dict) -> dict | None:
    """같은 단지·같은 평형에서 이 거래 바로 앞의 매매 (해제된 거래 제외)."""
    earlier = [
        s for s in sales
        if not s.get("cancelled") and s["key"] != record["key"]
        and abs(s["area"] - record["area"]) < SAME_TYPE_AREA and s["date"] < record["date"]
    ]
    return max(earlier, key=lambda s: (s["date"], s["key"])) if earlier else None


def with_price_change(event: dict, sales: list[dict], detected_at: str | None) -> dict:
    """매매 이벤트에 직전 거래 대비 변동을 붙인다. 직전 거래가 없으면 prev_price 는 None."""
    out = dict(event, detected_at=detected_at)
    prev = previous_sale(sales, event["record"])
    out["prev_price"] = prev["price"] if prev else None
    out["prev_date"] = prev["date"] if prev else None
    out["change"] = event["record"]["price"] - prev["price"] if prev else None
    out["change_pct"] = round(out["change"] / prev["price"] * 100, 1) if prev and prev["price"] else None
    return out


def seed_recent_sales(complexes: list[dict], today: date) -> list[dict]:
    """처음 한 번: 발견 기록이 아직 없으니, 최근 RECENT_DAYS 일 안에 계약된 매매로 목록을 채운다."""
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    out = []
    for c in complexes:
        sales = _sales_of(c["kapt_code"])
        for s in sales:
            if not s.get("cancelled") and s["date"] >= cutoff:
                event = {"type": "new_sale", "kapt_code": c["kapt_code"], "name": c["name"], "record": s}
                out.append(with_price_change(event, sales, None))
    return out


def recent_sales(previous: list[dict] | None, events: list[dict], complexes: list[dict],
                 now: datetime | None = None) -> list[dict]:
    """최근 RECENT_DAYS 일 동안 새로 발견한 매매(신규·해제) 목록. 전월세는 넣지 않는다.

    previous: 지난 실행까지의 목록 (없으면 계약일 기준으로 처음 채운다)
    events:   이번 실행에서 발견한 이벤트 (전월세 포함, 여기서 걸러 낸다)
    """
    now = now or now_kst()
    names = {c["kapt_code"]: c["name"] for c in complexes}
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S+09:00")
    fresh = [with_price_change(e, _sales_of(e["kapt_code"]), stamp) for e in events if e["type"] in SALE_EVENT_TYPES]
    older = previous if previous is not None else seed_recent_sales(complexes, now.date())

    cutoff = (now - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%S+09:00")
    cutoff_date = (now.date() - timedelta(days=RECENT_DAYS)).isoformat()
    out, seen = [], set()
    for e in fresh + older:
        key = (e["type"], e["record"]["key"])
        if key in seen or e["kapt_code"] not in names:
            continue
        # 발견 시각이 있으면 그 기준, 처음 채운 항목은 계약일 기준으로 기간을 따진다
        if (e.get("detected_at") or "") < cutoff if e.get("detected_at") else e["record"]["date"] < cutoff_date:
            continue
        seen.add(key)
        out.append(dict(e, name=names[e["kapt_code"]]))
    out.sort(key=lambda e: (e.get("detected_at") or e["record"]["date"], e["record"]["date"]), reverse=True)
    return out


def save_changes(events: list[dict], first_run: bool, complexes: list[dict] | None = None) -> list[dict]:
    """이번 실행의 변화와 최근 매매 목록을 저장하고, 최근 매매 목록을 돌려준다."""
    previous = read_json(config.LATEST_CHANGES_FILE, {}).get("recent_sales")
    recent = recent_sales(previous, events, complexes or [])
    write_json(config.LATEST_CHANGES_FILE, {
        "generated_at": now_iso(),
        "first_run": first_run,
        "count": len(events),
        "events": events,
        "recent_days": RECENT_DAYS,
        "recent_sales": recent,
    }, compact=True)
    return recent
