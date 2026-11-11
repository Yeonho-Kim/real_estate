import pytest

from collector import config


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    """테스트마다 data/ 경로를 임시 폴더로 바꾼다."""
    data = tmp_path / "data"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "TRADES_DIR", data / "trades")
    monkeypatch.setattr(config, "CHANGES_DIR", data / "changes")
    monkeypatch.setattr(config, "COMPLEXES_FILE", data / "complexes.json")
    monkeypatch.setattr(config, "COMPLEXES_SKIPPED_FILE", data / "complexes_skipped.json")
    monkeypatch.setattr(config, "SUMMARY_FILE", data / "summary.json")
    monkeypatch.setattr(config, "STATE_FILE", data / "state.json")
    monkeypatch.setattr(config, "UNMATCHED_FILE", data / "unmatched.json")
    monkeypatch.setattr(config, "LATEST_CHANGES_FILE", data / "changes" / "latest.json")
    monkeypatch.setattr(config, "OVERRIDES_FILE", tmp_path / "overrides.json")
    monkeypatch.setattr(config, "WATCHLIST_FILE", tmp_path / "watchlist.json")
    monkeypatch.setattr(config, "REQUEST_SLEEP", 0)
    return data


SALE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
 <header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
 <body>
  <items>
   <item>
    <aptDong></aptDong><aptNm>마포래미안푸르지오</aptNm><aptSeq>11440-3214</aptSeq>
    <buildYear>2014</buildYear><buyerGbn>개인</buyerGbn><cdealDay> </cdealDay><cdealType> </cdealType>
    <dealAmount>    185,000</dealAmount><dealDay>12</dealDay><dealMonth>10</dealMonth><dealYear>2026</dealYear>
    <dealingGbn>중개거래</dealingGbn><estateAgentSggNm>서울 마포구</estateAgentSggNm>
    <excluUseAr>84.89</excluUseAr><floor>15</floor><jibun>777</jibun><rgstDate> </rgstDate>
    <roadNm>마포대로</roadNm><roadNmBonbun>00195</roadNmBonbun><roadNmBubun>00000</roadNmBubun><sggCd>11440</sggCd><umdNm>아현동</umdNm>
   </item>
   <item>
    <aptDong>101</aptDong><aptNm>마포래미안푸르지오</aptNm><aptSeq>11440-3214</aptSeq>
    <buildYear>2014</buildYear><cdealDay>26.10.20</cdealDay><cdealType>O</cdealType>
    <dealAmount>130,000</dealAmount><dealDay>3</dealDay><dealMonth>10</dealMonth><dealYear>2026</dealYear>
    <dealingGbn>직거래</dealingGbn><excluUseAr>59.96</excluUseAr><floor>7</floor><jibun>777</jibun>
    <rgstDate>26.10.15</rgstDate><sggCd>11440</sggCd><umdNm>아현동</umdNm>
   </item>
   <item>
    <aptNm>큰평수아파트</aptNm><aptSeq>11440-9999</aptSeq><dealAmount>300,000</dealAmount>
    <dealDay>1</dealDay><dealMonth>10</dealMonth><dealYear>2026</dealYear>
    <excluUseAr>114.5</excluUseAr><floor>3</floor><jibun>1</jibun><sggCd>11440</sggCd><umdNm>공덕동</umdNm>
   </item>
  </items>
  <numOfRows>1000</numOfRows><pageNo>1</pageNo><totalCount>3</totalCount>
 </body>
</response>"""

RENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
 <header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
 <body>
  <items>
   <item>
    <aptNm>마포래미안푸르지오</aptNm><buildYear>2014</buildYear><contractTerm>26.11~28.11</contractTerm>
    <contractType>신규</contractType><dealDay>20</dealDay><dealMonth>10</dealMonth><dealYear>2026</dealYear>
    <deposit>95,000</deposit><excluUseAr>84.89</excluUseAr><floor>10</floor><jibun>777</jibun>
    <monthlyRent>0</monthlyRent><sggCd>11440</sggCd><umdNm>아현동</umdNm><useRRRight></useRRRight>
   </item>
   <item>
    <aptNm>마포래미안푸르지오</aptNm><contractType>갱신</contractType><dealDay>21</dealDay><dealMonth>10</dealMonth>
    <dealYear>2026</dealYear><deposit>10,000</deposit><excluUseAr>59.96</excluUseAr><floor>4</floor><jibun>777</jibun>
    <monthlyRent>250</monthlyRent><sggCd>11440</sggCd><umdNm>아현동</umdNm>
   </item>
  </items>
  <numOfRows>1000</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount>
 </body>
</response>"""

KAPT_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
 <item><as1>서울특별시</as1><as2>마포구</as2><as3>아현동</as3><as4></as4><bjdCode>1144012000</bjdCode><kaptCode>A13376001</kaptCode><kaptName>마포래미안푸르지오</kaptName></item>
 <item><as1>서울특별시</as1><as2>마포구</as2><as3>공덕동</as3><bjdCode>1144010100</bjdCode><kaptCode>A13300001</kaptCode><kaptName>작은단지</kaptName></item>
</items><numOfRows>100</numOfRows><pageNo>1</pageNo><totalCount>2</totalCount></body></response>"""

KAPT_BASIC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><item>
 <bjdCode>1144012000</bjdCode><codeSaleNm>분양</codeSaleNm><doroJuso>서울특별시 마포구 마포대로 195</doroJuso>
 <kaptAddr>서울특별시 마포구 아현동 777 마포래미안푸르지오</kaptAddr><kaptCode>A13376001</kaptCode>
 <kaptDongCnt>44</kaptDongCnt><kaptMparea135>400</kaptMparea135><kaptMparea60>1200</kaptMparea60><kaptMparea85>2000</kaptMparea85>
 <kaptName>마포래미안푸르지오</kaptName><kaptUsedate>20140930</kaptUsedate><kaptdaCnt>3885</kaptdaCnt>
</item></body></response>"""

ERROR_XML = """<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>
<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"""

COMPLEX = {
    "kapt_code": "A13376001", "name": "마포래미안푸르지오", "address": "서울특별시 마포구 아현동 777 마포래미안푸르지오",
    "road_address": "서울특별시 마포구 마포대로 195", "bjd_code": "1144012000", "households": 3885, "dong_count": 44,
    "approved": "2014-09-30", "area_60": 1200, "area_85": 2000, "area_135": 400, "sale_type": "분양",
    "umd": "아현동", "jibun": "777", "sgg_code": "11440", "sgg_name": "마포구", "lat": 37.55, "lng": 126.95, "apt_seqs": [],
}
