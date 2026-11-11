import pytest

from collector import config
from collector.http import ApiError
from collector.kapt_api import parse_basic, parse_list, parse_lot_address
from collector.molit_api import parse_rents, parse_sales

from .conftest import ERROR_XML, KAPT_BASIC_XML, KAPT_LIST_XML, RENT_XML, SALE_XML


def test_parse_sales():
    sales, total = parse_sales(SALE_XML)
    assert total == 3
    assert len(sales) == 3
    s = sales[0]
    assert s.price == 185000 and s.area == 84.89 and s.floor == 15
    assert s.date == "2026-10-12" and s.apt_seq == "11440-3214" and s.dealing == "중개거래"
    assert s.cancelled is False and s.registered == ""
    s2 = sales[1]
    assert s2.cancelled is True and s2.cancel_date == "2026-10-20" and s2.registered == "2026-10-15"
    assert s2.dong == "101" and s2.dealing == "직거래"
    assert s.key != s2.key


def test_parse_rents():
    rents, total = parse_rents(RENT_XML)
    assert total == 2
    assert rents[0].deposit == 95000 and rents[0].monthly == 0 and rents[0].contract_type == "신규"
    assert rents[1].monthly == 250 and rents[1].contract_type == "갱신"


def test_error_envelope():
    with pytest.raises(ApiError):
        parse_sales(ERROR_XML)


def test_kapt_list_and_basic():
    items, total = parse_list(KAPT_LIST_XML)
    assert total == 2 and items[0]["kapt_code"] == "A13376001" and items[0]["as3"] == "아현동"
    basic = parse_basic(KAPT_BASIC_XML)
    assert basic.households == 3885 and basic.umd == "아현동" and basic.jibun == "777"
    assert basic.approved == "2014-09-30" and basic.area_85 == 2000


@pytest.mark.parametrize("addr,expected", [
    ("서울특별시 마포구 아현동 777 마포래미안푸르지오", ("아현동", "777")),
    ("서울특별시 영등포구 양평동5가 10-1 한신", ("양평동5가", "10-1")),
    ("서울특별시 강서구 염창동 산 12 아파트", ("염창동", "12")),
    ("서울특별시 동작구 사당동", ("사당동", "")),
])
def test_parse_lot_address(addr, expected):
    assert parse_lot_address(addr) == expected


def test_area_filter_and_bucket():
    assert config.in_area_range(59.96) and config.in_area_range(84.99)
    assert not config.in_area_range(114.5) and not config.in_area_range(49.9)
    assert config.type_bucket(59.96) == "59" and config.type_bucket(74.5) == "70" and config.type_bucket(84.9) == "84"


def test_region_umd_filter():
    gangseo = next(r for r in config.REGIONS if r.code == "11500")
    ydp = next(r for r in config.REGIONS if r.code == "11560")
    mapo = next(r for r in config.REGIONS if r.code == "11440")
    assert gangseo.accepts_umd("염창동") and not gangseo.accepts_umd("화곡동")
    assert ydp.accepts_umd("양평동5가") and ydp.accepts_umd("양평동") and not ydp.accepts_umd("여의도동")
    assert mapo.accepts_umd("아무동")


# ---------- 2026-08 개편 이후 K-apt JSON 응답 ----------

KAPT_LIST_JSON = """{"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
 "body": {"items": [
   {"as1": "서울특별시", "as2": "마포구", "as3": "아현동", "as4": null, "bjdCode": "1144012000", "kaptCode": "A13376001", "kaptName": "마포래미안푸르지오"},
   {"as1": "서울특별시", "as2": "마포구", "as3": "공덕동", "as4": null, "bjdCode": "1144010100", "kaptCode": "A13300001", "kaptName": "작은단지"}
 ], "numOfRows": 1000, "pageNo": 1, "totalCount": 2}}}"""

KAPT_BASIC_JSON = """{"response": {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
 "body": {"item": {"kaptCode": "A13376001", "kaptName": "마포래미안푸르지오",
   "kaptAddr": "서울특별시 마포구 아현동 777 마포래미안푸르지오", "doroJuso": "서울특별시 마포구 마포대로 195",
   "bjdCode": "1144012000", "codeSaleNm": "분양", "kaptdaCnt": 3885.0, "kaptDongCnt": "44",
   "kaptUsedate": "20140930", "kaptMparea60": 1200, "kaptMparea85": 2000, "kaptMparea135": 400,
   "kaptTel": null, "extra": {"nested": 1}}}}}"""


def test_kapt_json_list_and_basic():
    items, total = parse_list(KAPT_LIST_JSON)
    assert total == 2 and [i["kapt_code"] for i in items] == ["A13376001", "A13300001"]
    assert items[0]["as3"] == "아현동" and items[0]["as4"] == ""
    basic = parse_basic(KAPT_BASIC_JSON)
    assert basic.households == 3885 and basic.dong_count == 44 and basic.approved == "2014-09-30"
    assert basic.umd == "아현동" and basic.jibun == "777" and basic.area_85 == 2000
    assert basic.road_address == "서울특별시 마포구 마포대로 195"


def test_json_variants_and_errors():
    from collector.molit_api import describe_error, parse_envelope

    # 구버전 모양: items 안에 item
    items, total = parse_envelope('{"response":{"header":{"resultCode":"00"},"body":{"items":{"item":[{"kaptCode":"A1"}]},"totalCount":1}}}')
    assert total == 1 and items[0].findtext("kaptCode") == "A1"
    # 결과 없음: items 가 빈 문자열
    items, total = parse_envelope('{"response":{"header":{"resultCode":"00"},"body":{"items":"","totalCount":0}}}')
    assert items == [] and total == 0
    assert parse_basic('{"response":{"header":{"resultCode":"00"},"body":{}}}') is None
    # 오류 코드
    with pytest.raises(ApiError, match="api error 30"):
        parse_envelope('{"response":{"header":{"resultCode":"30","resultMsg":"SERVICE KEY IS NOT REGISTERED ERROR."}}}')
    # 오류 본문 설명
    assert "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in describe_error(ERROR_XML)
    assert describe_error("<html>  Bad\n Gateway </html>").startswith("XML parse error") or "Bad Gateway" in describe_error("<html>  Bad\n Gateway </html>")


def test_clean_service_key_and_redact():
    from collector.http import redact

    assert config.clean_service_key("  abc+def/ghi==\n") == "abc+def/ghi=="
    assert config.clean_service_key("abc%2Bdef%2Fghi%3D%3D") == "abc+def/ghi=="
    msg = "HTTPSConnectionPool(host='apis.data.go.kr'): Max retries exceeded with url: /1613000/X/getX?serviceKey=SECRET%2Bkey%3D%3D&LAWD_CD=11440 (Caused by ...)"
    out = redact(msg)
    assert "SECRET" not in out and "serviceKey=***" in out and "LAWD_CD=11440" in out
    assert "abcdef" not in redact("Authorization: KakaoAK abcdef123")


def test_json_portal_error_and_quota():
    from collector.http import QuotaExceeded
    from collector.molit_api import parse_envelope

    quota = '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"SERVICE ERROR","returnAuthMsg":"LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR","returnReasonCode":"22"}}}'
    with pytest.raises(QuotaExceeded, match="portal error 22"):
        parse_envelope(quota)
    other = '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"errMsg":"SERVICE ERROR","returnAuthMsg":"HTTP ROUTING ERROR","returnReasonCode":"04"}}}'
    with pytest.raises(ApiError, match="HTTP ROUTING ERROR") as info:
        parse_envelope(other)
    assert not isinstance(info.value, QuotaExceeded)
    # 초당 한도는 일일 한도가 아니다
    per_sec = '{"OpenAPI_ServiceResponse":{"cmmMsgHeader":{"returnAuthMsg":"LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND_EXCEEDS_ERROR","returnReasonCode":"23"}}}'
    with pytest.raises(ApiError) as info:
        parse_envelope(per_sec)
    assert not isinstance(info.value, QuotaExceeded)
    with pytest.raises(QuotaExceeded):
        parse_envelope('{"response":{"header":{"resultCode":"22","resultMsg":"LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."}}}')
