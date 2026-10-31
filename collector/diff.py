"""이전 실행과 비교해 새 거래·해제를 찾아낸다."""
from __future__ import annotations

from . import config
from .store import now_iso, read_json, write_json


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


def save_changes(events: list[dict], first_run: bool) -> None:
    write_json(config.LATEST_CHANGES_FILE, {
        "generated_at": now_iso(),
        "first_run": first_run,
        "count": len(events),
        "events": events,
    }, compact=True)
