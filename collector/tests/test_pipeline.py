import copy
import json

from collector import config, diff, summary
from collector.collect_trades import collect, merge_records
from collector.matching import ComplexIndex, normalize_name
from collector.notify_push import build_messages, filter_events
from collector.store import write_json

from .conftest import COMPLEX, RENT_XML, SALE_XML


def test_matching_by_lot_then_name():
    other = dict(COMPLEX, kapt_code="B1", name="아현 자이 2단지", jibun="900")
    idx = ComplexIndex([COMPLEX, other])
    assert idx.match("아현동", "777", "마포래미안푸르지오", "11440-3214")["kapt_code"] == "A13376001"
    # 학습된 aptSeq 로 재매칭
    assert idx.by_apt_seq["11440-3214"] == "A13376001"
    # 지번이 달라도 같은 동에서 이름으로
    assert idx.match("아현동", "123-4", "마포 래미안 푸르지오(아파트)")["kapt_code"] == "A13376001"
    assert idx.match("아현동", "901", "아현자이2단지")["kapt_code"] == "B1"
    assert idx.match("공덕동", "1", "전혀다른곳") is None
    assert normalize_name("마포 래미안-푸르지오 아파트(1단지)") == "마포래미안푸르지오"


def test_override_wins():
    idx = ComplexIndex([COMPLEX], {"11440-1": "A13376001"})
    assert idx.match("다른동", "1", "엉뚱", "11440-1")["kapt_code"] == "A13376001"


def test_merge_records_replaces_refreshed_months():
    old = [{"key": "a", "date": "2026-10-01", "floor": 1}, {"key": "b", "date": "2026-08-01", "floor": 1}]
    fresh = [{"key": "c", "date": "2026-10-05", "floor": 2}]
    merged = merge_records(old, fresh, {"202610"})
    assert [r["key"] for r in merged] == ["c", "b"]


def _fake_fetch(monkeypatch):
    from collector import collect_trades, molit_api

    def fake_sales(key, lawd, ym):
        return molit_api.parse_sales(SALE_XML)[0] if lawd == "11440" else []

    def fake_rents(key, lawd, ym):
        return molit_api.parse_rents(RENT_XML)[0] if lawd == "11440" else []

    monkeypatch.setattr(collect_trades, "fetch_sales", fake_sales)
    monkeypatch.setattr(collect_trades, "fetch_rents", fake_rents)


def test_collect_diff_summary_end_to_end(monkeypatch, tmp_data_dir):
    _fake_fetch(monkeypatch)
    write_json(config.COMPLEXES_FILE, {"complexes": [copy.deepcopy(COMPLEX)]})

    # 1차 실행: 전부 신규지만 first_run 이라 알림 없음
    result = collect("KEY", ["202610"])
    assert result["stats"]["sales_filtered"] == 2  # 114㎡ 제외
    assert set(result["sales_by"]) == {"A13376001"}
    trades = json.loads((config.TRADES_DIR / "A13376001.json").read_text())
    assert len(trades["sales"]) == 2 and len(trades["rents"]) == 2
    # aptSeq 학습이 마스터에 저장됨
    master = json.loads(config.COMPLEXES_FILE.read_text())
    assert master["complexes"][0]["apt_seqs"] == ["11440-3214"]
    unmatched = json.loads(config.UNMATCHED_FILE.read_text())
    assert unmatched["items"] == []

    state = diff.load_state()
    events = diff.compute_events(state, result["sales_by"], result["rents_by"], master["complexes"])
    # 해제건은 신규 알림 대상이 아니고, 신규 매매 1 + 전월세 2
    assert sorted(e["type"] for e in events) == ["new_rent", "new_rent", "new_sale"]
    state = diff.update_state(state, result["sales_by"], result["rents_by"])
    assert len(state["sale_keys"]) == 2 and len(state["cancelled_keys"]) == 1

    # 2차 실행: 같은 데이터면 변화 없음
    events2 = diff.compute_events(state, result["sales_by"], result["rents_by"], master["complexes"])
    assert events2 == []

    s = summary.build_summary(master["complexes"], events)
    item = s["complexes"][0]
    assert item["new_events"] == 3 and item["sale_count"] == 1
    assert item["types"]["84"]["avg"] == 185000 and item["types"]["84"]["jeonse_avg"] == 95000
    assert item["types"]["84"]["jeonse_ratio"] == 51
    assert "59" not in item["types"]  # 해제건과 월세만 있어 통계 제외


def test_filter_events_and_messages():
    sale = {"key": "k1", "area": 84.9, "price": 185000, "floor": 15, "date": "2026-10-12", "dealing": "중개거래", "cancelled": False}
    rent = {"key": "k2", "area": 84.9, "deposit": 10000, "monthly": 250, "floor": 4, "date": "2026-10-21", "contract_type": "갱신"}
    events = [
        {"type": "new_sale", "kapt_code": "A", "name": "단지A", "record": sale},
        {"type": "new_rent", "kapt_code": "A", "name": "단지A", "record": rent},
        {"type": "new_sale", "kapt_code": "B", "name": "단지B", "record": dict(sale, key="k3", price=90000, area=59.9)},
    ]
    # 전체 규칙: 매매만
    out = filter_events(events, {"notify_new_sales": True, "notify_new_rents": False})
    assert [e["record"]["key"] for e in out] == ["k1", "k3"]
    # 가격 상한
    out = filter_events(events, {"notify_new_sales": True, "max_price": 100000})
    assert [e["record"]["key"] for e in out] == ["k3"]
    # 특정 단지 규칙
    out = filter_events(events, {"complexes": [{"kapt_code": "A", "types": ["84"], "rents": True}]})
    assert [e["record"]["key"] for e in out] == ["k1", "k2"]
    msgs = build_messages(out, "https://x.github.io/r/")
    assert msgs[0]["title"] == "단지A 85㎡ 신규 매매" and "18억 5,000만원" in msgs[0]["body"]
    assert msgs[1]["title"] == "단지A 85㎡ 신규 월세" and "월 250만원" in msgs[1]["body"]
    digest = build_messages(events * 3, "https://x/")
    assert len(digest) == 1 and digest[0]["title"].startswith("신규 실거래 9건")


def test_vapid_key_roundtrip():
    from py_vapid import Vapid

    from collector.gen_vapid import generate

    pub, priv = generate()
    v = Vapid.from_string(priv)
    assert v.private_key is not None
    assert len(pub) == 87
