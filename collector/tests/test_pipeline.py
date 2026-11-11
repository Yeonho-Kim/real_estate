import copy
import json

import pytest

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


def test_build_complexes_end_to_end_with_json_api(monkeypatch, tmp_data_dir):
    """HTTP 만 가짜로 바꿔 단지 마스터 생성 전체를 돌린다 (목록 페이징, 세대수·동 필터, 좌표)."""
    from collector import build_complexes, http

    from .test_parsing import KAPT_BASIC_JSON

    calls = []

    class Resp:
        def __init__(self, text, status=200, payload=None):
            self.text, self.status_code, self._payload = text, status, payload

        def json(self):
            return self._payload

    def listing(rows, total):
        return json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"items": rows, "totalCount": total}}})

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url.rsplit("/", 1)[-1], dict(params)))
        if "getSigunguAptList4" in url:
            assert params["serviceKey"] == "KEY"
            if params["sigunguCode"] == "11440":
                # 서버가 한 번에 1건만 주는 경우의 페이징
                rows = [{"kaptCode": "A13376001", "kaptName": "마포래미안푸르지오", "as3": "아현동"},
                        {"kaptCode": "A13300001", "kaptName": "작은단지", "as3": "공덕동"}]
                page = params["pageNo"]
                return Resp(listing(rows[page - 1:page], 2))
            if params["sigunguCode"] == "11500":
                return Resp(listing([{"kaptCode": "G1", "kaptName": "화곡단지", "as3": "화곡동"}], 1))
            return Resp(listing([], 0))
        if "getAphusBassInfoV5" in url:
            if params["kaptCode"] == "A13300001":
                small = json.loads(KAPT_BASIC_JSON)
                small["response"]["body"]["item"].update(kaptCode="A13300001", kaptName="작은단지", kaptdaCnt=120)
                return Resp(json.dumps(small))
            return Resp(KAPT_BASIC_JSON)
        if "address.json" in url:
            assert headers["Authorization"] == "KakaoAK REST"
            return Resp("", payload={"documents": [{"x": "126.9561", "y": "37.5541"}]})
        raise AssertionError(url)

    monkeypatch.setattr(http.requests, "get", fake_get)
    result = build_complexes.build("KEY", "REST")

    assert [c["kapt_code"] for c in result] == ["A13376001"]      # 120세대 단지 제외
    assert result[0]["lat"] == 37.5541 and result[0]["lng"] == 126.9561 and result[0]["sgg_name"] == "마포구"
    saved = json.loads(config.COMPLEXES_FILE.read_text())
    assert saved["count"] == 1 and saved["skipped"]["households"] == 1 and saved["skipped"]["umd"] == 1
    assert saved["listed"]["마포구"] == 2 and saved["listed"]["강서구"] == 1
    skipped = json.loads(config.COMPLEXES_SKIPPED_FILE.read_text())["items"]
    assert {(i["name"], i["reason"], i["households"]) for i in skipped} == {("작은단지", "households", 120), ("화곡단지", "umd", None)}
    # 화곡동 단지는 기본정보를 부르지 않고 목록 단계에서 걸러진다
    assert not any(name == "getAphusBassInfoV5" and p.get("kaptCode") == "G1" for name, p in calls)
    assert sum(1 for name, p in calls if name == "getSigunguAptList4" and p["sigunguCode"] == "11440") == 2


def test_households_falls_back_to_ho_count():
    from collector.kapt_api import parse_basic

    def body(**fields):
        return json.dumps({"response": {"header": {"resultCode": "00"}, "body": {"item": dict(
            kaptCode="A1", kaptName="새단지", kaptAddr="서울특별시 동작구 흑석동 343 새단지", **fields)}}})

    assert parse_basic(body(kaptdaCnt=None, hoCnt=1772)).households == 1772       # 세대수 비어 있음
    assert parse_basic(body(kaptdaCnt="0", hoCnt="959")).households == 959        # 세대수 0
    assert parse_basic(body(kaptdaCnt=500, hoCnt=520)).households == 500          # 있으면 세대수 우선
    assert parse_basic(body()).households == 0


def test_state_reset_when_complex_set_changes(tmp_data_dir):
    from collector.main import reset_state_if_complexes_changed

    write_json(config.STATE_FILE, {"sale_keys": ["a"]})
    assert reset_state_if_complexes_changed({"A", "B"}, {"A", "B"}) is False and config.STATE_FILE.exists()
    assert reset_state_if_complexes_changed({"A", "B"}, {"A", "B", "C"}) is True and not config.STATE_FILE.exists()
    assert reset_state_if_complexes_changed({"A"}, {"B"}) is False   # 이미 없음


def test_build_reuses_known_complexes_and_stops_on_quota(monkeypatch, tmp_data_dir):
    """아는 단지는 다시 조회하지 않고, 한도 초과 시 받은 데까지만 저장한다."""
    from collector import build_complexes, kapt_api
    from collector.http import ApiError, QuotaExceeded
    from collector.kapt_api import parse_basic

    from .test_parsing import KAPT_BASIC_JSON

    monkeypatch.setattr(config, "REGIONS", (config.Region("11440", "마포구"),))
    write_json(config.COMPLEXES_FILE, {"complexes": [copy.deepcopy(COMPLEX)]})          # 이미 마스터에 있음
    write_json(config.COMPLEXES_SKIPPED_FILE, {"items": [
        {"kapt_code": "SMALL", "name": "작은단지", "sgg_name": "마포구", "umd": "공덕동", "households": 120, "ho_count": None, "address": "", "reason": "households"},
        {"kapt_code": "LATER", "name": "어제못받음", "sgg_name": "마포구", "umd": "공덕동", "households": None, "ho_count": None, "address": "", "reason": "not_fetched"},
    ]})
    listing = [{"kapt_code": c, "name": c, "as3": "공덕동"} for c in ("A13376001", "SMALL", "LATER", "NEW1", "NEW2", "NEW3")]
    monkeypatch.setattr(build_complexes, "fetch_list", lambda key, code: listing)
    asked = []

    def fake_basic(key, code):
        asked.append(code)
        if code == "NEW2":
            raise QuotaExceeded("portal error 22: LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR")
        data = json.loads(KAPT_BASIC_JSON)
        data["response"]["body"]["item"].update(kaptCode=code, kaptName=code, kaptdaCnt=800)
        return parse_basic(json.dumps(data))

    monkeypatch.setattr(build_complexes, "fetch_basic", fake_basic)
    result = build_complexes.build("KEY", None)

    assert asked == ["LATER", "NEW1", "NEW2"]                    # 아는 단지는 조회 안 함, 한도 뒤로는 중단
    assert sorted(c["kapt_code"] for c in result) == ["A13376001", "LATER", "NEW1"]
    assert next(c for c in result if c["kapt_code"] == "A13376001")["lat"] == 37.55   # 기존 좌표 유지
    skipped = {i["kapt_code"]: i["reason"] for i in json.loads(config.COMPLEXES_SKIPPED_FILE.read_text())["items"]}
    assert skipped == {"SMALL": "households", "NEW2": "not_fetched", "NEW3": "not_fetched"}
    assert json.loads(config.COMPLEXES_FILE.read_text())["skipped"]["not_fetched"] == 2

    # 일시 오류는 다시 시도해서 성공한다
    monkeypatch.setattr(kapt_api.time, "sleep", lambda s: None)
    attempts = []

    class Resp:
        status_code = 200

        def __init__(self, text):
            self.text = text

    def flaky_get(url, params, headers=None):
        attempts.append(1)
        if len(attempts) < 3:
            return Resp('{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"returnAuthMsg":"HTTP ROUTING ERROR","returnReasonCode":"04"}}}')
        return Resp(KAPT_BASIC_JSON)

    monkeypatch.setattr(kapt_api, "get", flaky_get)
    assert kapt_api.fetch_basic("KEY", "A13376001").households == 3885 and len(attempts) == 3
    attempts.clear()
    monkeypatch.setattr(kapt_api, "get", lambda url, params, headers=None: Resp('{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"returnAuthMsg":"HTTP ROUTING ERROR","returnReasonCode":"04"}}}'))
    with pytest.raises(ApiError, match="HTTP ROUTING ERROR"):
        kapt_api.fetch_basic("KEY", "A13376001")
