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
