import copy
import json

import pytest

from collector import config, diff, summary
from collector.collect_trades import collect, merge_records
from collector.matching import MATCH_VERSION, ComplexIndex, normalize_name
from collector.notify_push import build_messages, filter_events
from collector.store import write_json

from .conftest import COMPLEX, RENT_XML, SALE_XML


def _cx(code, name, umd, jibun, road, approved, households=500):
    return {"kapt_code": code, "name": name, "umd": umd, "jibun": jibun, "households": households,
            "road_address": f"서울특별시 어느구 {road}", "approved": f"{approved}-06-30", "apt_seqs": [], "alt_lots": []}


def test_name_helpers():
    from collector.matching import name_ratio, ordinals_compatible, parse_road, split_name

    assert normalize_name("마포 래미안-푸르지오 아파트(1단지)") == "마포래미안푸르지오"
    assert split_name("마포래미안푸르지오4단지") == ("마포래미안푸르지오", "", "4")
    assert split_name("상도2차 두산위브트레지움 아파트") == ("상도두산위브트레지움", "2", "")
    assert normalize_name("홍제센트럴IPARK") == normalize_name("홍제센트럴아이파크")
    assert name_ratio("영등포중흥에스클래스", "영등포 중흥S-클래스") == 1.0
    assert name_ratio("마포자이더센트리지(102동~112동)", "마포자이 더 센트리지 아파트") == 1.0
    assert parse_road("서울특별시 영등포구 양평동1가 선유서로24길 6") == ("선유서로24길", "6")
    assert parse_road("서울특별시 마포구 마포대로 195") == ("마포대로", "195")
    assert parse_road("") == ("", "")
    # 단지 번호: K-apt 가 단지 전체로 등록한 경우만 허용
    assert ordinals_compatible("마포래미안푸르지오4단지", "마포래미안푸르지오")
    assert not ordinals_compatible("월드컵아이파크", "월드컵아이파크1단지")
    assert not ordinals_compatible("상암월드컵파크2단지", "상암월드컵파크3단지")
    # 차수는 양쪽이 같아야 한다
    assert not ordinals_compatible("북한산두산위브2차", "북한산 두산 위브")
    assert not ordinals_compatible("도화현대", "도화현대1차아파트")
    assert ordinals_compatible("두산위브트레지움2차", "상도2차 두산위브트레지움 아파트")


def test_matching_real_world_cases():
    """첫 실수집에서 확인한 사례. 같은 단지는 붙고, 이름만 비슷한 다른 단지는 붙지 않아야 한다."""
    idx = ComplexIndex([
        _cx("MRP", "마포래미안푸르지오", "아현동", "767", "마포대로 195", 2014, 3885),
        _cx("MJ", "마포자이", "염리동", "521", "독막로42길 2", 2003, 534),
        _cx("MJC", "마포자이 더 센트리지 아파트", "염리동", "45", "숭문길 98", 2018, 927),
        _cx("BDW", "북한산 두산 위브", "홍은동", "467", "홍은중앙로3길 9", 2020, 497),
        _cx("HSF", "힐스테이트  서대문포레스트 아파트", "홍은동", "338-5", "가좌로4길 21", 2023, 623),
        _cx("SLS", "사당롯데캐슬샤인", "사당동", "1132", "사당로27길 190", 2003, 444),
        _cx("DH1", "도화현대1차아파트", "도화동", "357", "새창로 52", 1996, 1021),
        _cx("DCV", "돈의문센트레빌", "냉천동", "261", "독립문로14길 33", 2011, 561),
        _cx("SW1", "신대방우성1차", "신대방동", "565", "여의대방로 22", 1988, 1335),
        _cx("HJ", "흑석자이", "흑석동", "253-89", "서달로 90", 2023, 1772),
        _cx("YJS", "영등포 중흥S-클래스", "양평동1가", "247", "선유서로24길 6", 2021, 308),
    ])
    m = lambda *a, **k: (idx.match(*a, **k) or {}).get("kapt_code")

    # --- 붙어야 하는 경우 ---
    assert m("아현동", "777", "마포래미안푸르지오4단지", "S1", 2014, "마포대로", "195") == "MRP"   # A: 도로명+번호
    assert m("아현동", "777", "마포래미안푸르지오2단지", "S2", 2014, "마포대로", "") == "MRP"      # B: 도로명+이름
    assert m("염리동", "533", "마포자이더센트리지(102동~112동)", "S3", 2022, "숭문길", "") == "MJC"  # B: 건축년도가 달라도 됨
    assert m("양평동1가", "271", "영등포중흥에스클래스", "S4", 2021, "선유서로24길", "") == "YJS"
    assert m("홍은동", "470", "힐스테이트홍은포레스트", "S5", 2023, "가좌로4길", "21") == "HSF"     # A: 이름이 달라도 주소가 같음
    assert m("염리동", "521", "마포자이", "S6", 2003, "독막로42길", "") == "MJ"                    # 지번 일치
    # 매매로 확정된 지번은 도로명이 없는 전월세도 따라간다
    assert m("아현동", "777", "마포래미안푸르지오1단지", "", 2014) == "MRP"
    assert m("홍은동", "470", "힐스테이트홍은포레스트", "", 2023) == "HSF"
    assert idx.by_code["MRP"]["alt_lots"] == ["아현동|777"] and "S1" in idx.by_code["MRP"]["apt_seqs"]

    # --- 붙으면 안 되는 경우 (모두 실제로 잘못 붙었던 사례) ---
    assert m("홍은동", "468", "북한산두산위브2차", "X1", 2021, "홍은중앙로1길", "") is None    # 도로명 다름
    assert m("홍은동", "456", "두산", "X2", 1997, "모래내로", "") is None
    assert m("사당동", "1149", "사당롯데캐슬2차", "X3", 2004, "사당로27길", "") is None        # 도로명 같지만 차수 다름
    assert m("도화동", "547", "도화현대", "X4", 1998, "새창로", "") is None                   # 도로명 같지만 차수·연도 다름
    assert m("냉천동", "260", "동부센트레빌", "X5", 2002, "독립문로14길", "") is None          # 도로명 같지만 이름 다름
    assert m("신대방동", "565-21", "우성2차", "X6", 1995, "여의대방로", "") is None            # 본번만 같음
    assert m("흑석동", "343", "흑석리버파크자이", "X7", 2025, "서달로", "") is None            # 번호 없이는 확신 못 함 → 수동 지정 대상
    assert m("홍은동", "999", "북한산두산위브2차", "", 2021) is None                          # 전월세: 이름·차수 불일치
    assert m("없는동", "1", "마포자이", "X8", 2003, "독막로42길", "2") is None


def test_same_lot_with_several_complexes():
    """한 지번을 여러 단지가 같이 쓰는 경우. 실거래 자료의 줄임 이름으로 골라야 한다."""
    idx = ComplexIndex([
        _cx("GD", "사당극동", "사당동", "105", "사당로 1", 1993),
        _cx("SD4", "사당신동아4단지", "사당동", "105", "사당로 2", 1993),
        _cx("WS43", "사당우성(4-3)아파트", "사당동", "105", "사당로 3", 1993),
        _cx("WS2", "사당우성2단지", "사당동", "105", "사당로 4", 1993),
        _cx("JG1", "대방주공1단지", "대방동", "503", "등용로 1", 1993),
        _cx("JG2", "대방주공2단지", "대방동", "503", "등용로 2", 1993),
    ])
    m = lambda name, umd="사당동", jibun="105": idx.match(umd, jibun, name)["kapt_code"]
    assert m("극동") == "GD" and m("신동아4") == "SD4" and m("사당우성2") == "WS2" and m("우성3") == "WS43"
    assert m("주공2", "대방동", "503") == "JG2" and m("주공1", "대방동", "503") == "JG1"


def test_override_and_learned_seq():
    cx = [_cx("HJ", "흑석자이", "흑석동", "253-89", "서달로 90", 2023, 1772)]
    idx = ComplexIndex(cx, {"11590-5152": "HJ", "_11590-5152": "설명 줄은 무시"})
    assert idx.match("흑석동", "343", "흑석리버파크자이", "11590-5152", 2025, "서달로", "")["kapt_code"] == "HJ"
    assert idx.match("흑석동", "343", "흑석리버파크자이", "", 2025)["kapt_code"] == "HJ"     # 전월세는 지번 별칭으로
    # 저장된 연결은 다음 실행에서도 그대로 쓰인다
    again = ComplexIndex(copy.deepcopy(cx))
    assert again.match("흑석동", "343", "이름이바뀌어도", "11590-5152")["kapt_code"] == "HJ"
    assert again.match("흑석동", "343", "흑석리버파크자이")["kapt_code"] == "HJ"
    # 규칙이 바뀌면 저장된 연결을 버린다
    again.reset_learned()
    assert again.match("흑석동", "343", "흑석리버파크자이", "11590-5152", 2025, "서달로", "") is None
    assert again.by_code["HJ"]["apt_seqs"] == [] and again.by_code["HJ"]["alt_lots"] == []


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
    assert master["complexes"][0]["apt_seqs"] == ["11440-3214"] and master["match_version"] == MATCH_VERSION
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


def test_rematch_when_rules_change(monkeypatch, tmp_data_dir):
    """연결 규칙 버전이 다르면 저장된 연결을 버리고, 알림 없이 전체 기간을 다시 받는다."""
    from collector import collect_trades, main

    _fake_fetch(monkeypatch)
    stale = copy.deepcopy(COMPLEX)
    stale["apt_seqs"] = ["WRONG-1"]
    write_json(config.COMPLEXES_FILE, {"match_version": 1, "complexes": [stale]})
    write_json(config.STATE_FILE, {"sale_keys": ["old"], "rent_keys": [], "cancelled_keys": []})
    write_json(config.TRADES_DIR / "A13376001.json", {"sales": [{"key": "bad", "date": "2025-12-01", "floor": 1}], "rents": []})
    assert collect_trades.needs_rematch()
    asked = []
    real = collect_trades.fetch_sales
    monkeypatch.setattr(collect_trades, "fetch_sales", lambda k, lawd, ym: (asked.append(ym), real(k, lawd, ym))[1])
    monkeypatch.setenv("DATA_GO_KR_KEY", "KEY")
    main.main(["collect"])

    assert len(set(asked)) == config.BACKFILL_MONTHS                       # 전체 기간
    master = json.loads(config.COMPLEXES_FILE.read_text())
    assert master["match_version"] == MATCH_VERSION and master["complexes"][0]["apt_seqs"] == ["11440-3214"]
    trades = json.loads((config.TRADES_DIR / "A13376001.json").read_text())
    assert "bad" not in {r["key"] for r in trades["sales"]}                # 예전 연결 결과는 사라짐
    changes = json.loads(config.LATEST_CHANGES_FILE.read_text())
    assert changes["first_run"] is True and changes["count"] == 0          # 알림 없음
    assert not collect_trades.needs_rematch()


def test_unmatched_report_has_override_hints(monkeypatch, tmp_data_dir):
    """연결 못 한 거래에는 수동 지정에 필요한 aptSeq·도로명이 함께 남는다."""
    _fake_fetch(monkeypatch)
    other = copy.deepcopy(COMPLEX)
    other.update(kapt_code="ELSE", name="전혀다른단지", jibun="1", road_address="서울특별시 마포구 다른길 9")
    write_json(config.COMPLEXES_FILE, {"match_version": MATCH_VERSION, "complexes": [other]})
    collect("KEY", ["202610"])
    items = json.loads(config.UNMATCHED_FILE.read_text())["items"]
    assert len(items) == 1
    assert items[0] == {"where": "마포구|아현동|777|마포래미안푸르지오", "count": 4, "sales": 2, "rents": 2,
                        "apt_seq": "11440-3214", "road": "마포대로 195", "build_year": 2014}
