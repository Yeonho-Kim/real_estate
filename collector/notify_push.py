"""변화 이벤트를 watchlist 규칙으로 걸러 웹 푸시로 보낸다.

필요 환경변수:
  VAPID_PRIVATE_KEY   gen_vapid.py 가 출력한 비밀키 (base64url 한 줄)
  PUSH_SUBSCRIPTIONS  브라우저가 만든 구독 JSON. 객체 하나 또는 배열.
  PUSH_CONTACT        (선택) mailto:주소. 푸시 서버가 연락용으로 요구함.
  SITE_URL            (선택) 알림 클릭 시 열 주소
"""
from __future__ import annotations

import json
import logging

from . import config
from .store import read_json

log = logging.getLogger(__name__)

MAX_INDIVIDUAL = 5  # 이 수를 넘으면 묶음 알림 하나로 보냄


def _fmt_price(man: int) -> str:
    """만원 → '15억 2,000만원'."""
    if man is None:
        return "-"
    eok, rest = divmod(int(man), 10000)
    if eok and rest:
        return f"{eok}억 {rest:,}만원"
    if eok:
        return f"{eok}억"
    return f"{rest:,}만원"


def load_watchlist() -> dict:
    return read_json(config.WATCHLIST_FILE, {})


def _rule_allows(rule: dict, record: dict, kind: str) -> bool:
    types = rule.get("types")
    if types and config.type_bucket(record["area"]) not in types:
        return False
    max_price = rule.get("max_price")
    if max_price and kind == "sale" and record.get("price", 0) > max_price:
        return False
    return True


def filter_events(events: list[dict], watchlist: dict) -> list[dict]:
    rules = [r for r in watchlist.get("complexes", []) if r.get("kapt_code")]
    by_code = {r["kapt_code"]: r for r in rules}
    out = []
    for e in events:
        rec = e["record"]
        if rules:
            rule = by_code.get(e["kapt_code"])
            if rule is None:
                continue
            if e["type"] == "new_rent" and not rule.get("rents", False):
                continue
            if e["type"] == "new_sale" and not _rule_allows(rule, rec, "sale"):
                continue
            if e["type"] == "new_rent" and not _rule_allows(rule, rec, "rent"):
                continue
        else:
            if e["type"] == "new_sale" and not watchlist.get("notify_new_sales", True):
                continue
            if e["type"] == "new_rent" and not watchlist.get("notify_new_rents", False):
                continue
            if e["type"] == "cancelled" and not watchlist.get("notify_cancelled", True):
                continue
            if not _rule_allows(watchlist, rec, "sale" if e["type"] != "new_rent" else "rent"):
                continue
        out.append(e)
    return out


def event_text(e: dict) -> tuple[str, str]:
    rec = e["record"]
    area = f"{rec['area']:.0f}㎡"
    floor = f"{rec['floor']}층" if rec.get("floor") else ""
    if e["type"] == "new_sale":
        title = f"{e['name']} {area} 신규 매매"
        body = f"{_fmt_price(rec['price'])} · {floor} · {rec['date']} 계약 · {rec.get('dealing', '')}".strip(" ·")
    elif e["type"] == "cancelled":
        title = f"{e['name']} {area} 거래 해제"
        body = f"{_fmt_price(rec['price'])} · {floor} · {rec['date']} 계약건 해제"
    else:
        kind = "전세" if rec["monthly"] == 0 else "월세"
        price = _fmt_price(rec["deposit"]) + (f" / 월 {rec['monthly']:,}만원" if rec["monthly"] else "")
        title = f"{e['name']} {area} 신규 {kind}"
        body = f"{price} · {floor} · {rec['date']} · {rec.get('contract_type', '')}".strip(" ·")
    return title, body


def build_messages(events: list[dict], site_url: str) -> list[dict]:
    if not events:
        return []
    if len(events) <= MAX_INDIVIDUAL:
        msgs = []
        for e in events:
            title, body = event_text(e)
            msgs.append({"title": title, "body": body, "url": f"{site_url}#{e['kapt_code']}", "tag": e["record"]["key"]})
        return msgs
    sales = sum(1 for e in events if e["type"] == "new_sale")
    rents = sum(1 for e in events if e["type"] == "new_rent")
    cancelled = sum(1 for e in events if e["type"] == "cancelled")
    parts = []
    if sales:
        parts.append(f"매매 {sales}건")
    if rents:
        parts.append(f"전월세 {rents}건")
    if cancelled:
        parts.append(f"해제 {cancelled}건")
    lines = [event_text(e)[0] for e in events[:3]]
    return [{
        "title": f"신규 실거래 {len(events)}건 ({', '.join(parts)})",
        "body": "\n".join(lines) + (f"\n외 {len(events) - 3}건" if len(events) > 3 else ""),
        "url": site_url,
        "tag": "digest",
    }]


def load_subscriptions() -> list[dict]:
    raw = config.env("PUSH_SUBSCRIPTIONS")
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    return [d for d in data if isinstance(d, dict) and d.get("endpoint")]


def send(messages: list[dict], subscriptions: list[dict], private_key: str, contact: str) -> dict:
    from pywebpush import WebPushException, webpush

    result = {"sent": 0, "failed": 0, "expired": []}
    for sub in subscriptions:
        for msg in messages:
            try:
                webpush(
                    subscription_info=sub,
                    data=json.dumps(msg, ensure_ascii=False),
                    vapid_private_key=private_key,
                    vapid_claims={"sub": contact},
                    ttl=86400,
                )
                result["sent"] += 1
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                result["failed"] += 1
                if status in (404, 410):
                    result["expired"].append(sub["endpoint"][:60])
                    log.warning("구독이 만료되었습니다(%s). PUSH_SUBSCRIPTIONS 를 갱신하세요: %s...", status, sub["endpoint"][:60])
                    break
                log.error("푸시 실패 %s: %s", status, exc)
    return result


def send_for_changes(events: list[dict], dry_run: bool = False) -> dict:
    watchlist = load_watchlist()
    selected = filter_events(events, watchlist)
    site_url = config.env("SITE_URL", "") or ""
    messages = build_messages(selected, site_url)
    log.info("이벤트 %d건 중 알림 대상 %d건 → 메시지 %d개", len(events), len(selected), len(messages))
    for m in messages:
        log.info("  [%s] %s", m["title"], m["body"].replace("\n", " / "))
    if dry_run or not messages:
        return {"sent": 0, "failed": 0, "expired": [], "dry_run": dry_run}
    private_key = config.env("VAPID_PRIVATE_KEY")
    subs = load_subscriptions()
    if not private_key or not subs:
        log.warning("VAPID_PRIVATE_KEY 또는 PUSH_SUBSCRIPTIONS 가 없어 알림을 보내지 않습니다.")
        return {"sent": 0, "failed": 0, "expired": [], "skipped": True}
    contact = config.env("PUSH_CONTACT", "mailto:admin@example.com") or "mailto:admin@example.com"
    result = send(messages, subs, private_key, contact)
    log.info("푸시 결과: %s", result)
    return result
