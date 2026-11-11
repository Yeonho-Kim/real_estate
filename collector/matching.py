"""실거래 레코드를 K-apt 단지에 연결한다.

K-apt 와 실거래 자료는 같은 단지라도 지번·이름이 자주 다르다 (예: K-apt "흑석자이 253-89" = 실거래 "흑석리버파크자이 343").
반대로 이름이 비슷한 다른 단지도 많다 (예: "북한산두산위브" 와 "북한산두산위브2차").
실제 수집 데이터로 확인한 결과, 같은 단지는 도로명이 항상 같았다. 그래서 아래 순서로, 확실할 때만 연결한다.

  1. 수동 지정 (collector/overrides.json: aptSeq → 단지코드)
  2. 이전에 확정된 aptSeq, 이전에 확정된 (법정동, 지번)
  3. (법정동, 지번) 이 K-apt 와 정확히 같음
  4. 같은 법정동에서
     A. 도로명과 건물번호가 같음
     B. 도로명이 같고 단지명이 같음
     C. 도로명이 같고 단지명이 거의 같고(0.9 이상) 건축년도가 1년 이내
     D. 도로명 정보가 없을 때(전월세): 단지명이 같고 건축년도가 1년 이내
  그 밖에는 연결하지 않는다 (data/unmatched.json 에 남는다).

"단지명이 같다"는 띄어쓰기·괄호·'아파트'를 떼고, 차수(N차)와 단지 번호(N단지)가 어긋나지 않는 것을 뜻한다.
규칙을 바꾸면 MATCH_VERSION 을 올린다. 그러면 다음 수집에서 저장된 연결을 버리고 전체 기간을 다시 맞춘다.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict

MATCH_VERSION = 2

_PAREN = re.compile(r"\(.*?\)|\[.*?\]")
_NOISE = re.compile(r"아파트|apt|[\s\-·,.~_/]")
_CHA = re.compile(r"제?(\d+)차")
_DANJI = re.compile(r"제?(\d+)단지")
_ROAD = re.compile(r"(\S+(?:로|길))\s+(\d+(?:-\d+)?)")
_ALIASES = (("ipark", "아이파크"), ("이편한세상", "e편한세상"), ("에스클래스", "s클래스"), ("sk", "에스케이"))


def normalize_name(name: str) -> str:
    """비교용 단지명: 소문자, 괄호 내용·'아파트'·공백·구두점 제거, 흔한 표기 차이 통일."""
    out = _PAREN.sub("", (name or "").lower())
    out = _NOISE.sub("", out)
    for a, b in _ALIASES:
        out = out.replace(a, b)
    return out


def split_name(name: str) -> tuple[str, str, str]:
    """(차수·단지번호를 뗀 이름, 차수, 단지번호). 예: '마포래미안푸르지오4단지' → ('마포래미안푸르지오', '', '4')"""
    norm = normalize_name(name)
    cha = _CHA.search(norm)
    danji = _DANJI.search(norm)
    base = _DANJI.sub("", _CHA.sub("", norm)).replace("단지", "")
    return base, (cha.group(1) if cha else ""), (danji.group(1) if danji else "")


def ordinals_compatible(trade_name: str, kapt_name: str) -> bool:
    """차수는 양쪽이 같아야 한다. 단지 번호는 K-apt 쪽에 없으면(단지 전체로 등록) 허용한다."""
    _, t_cha, t_danji = split_name(trade_name)
    _, k_cha, k_danji = split_name(kapt_name)
    if t_cha != k_cha:
        return False
    if k_danji and t_danji != k_danji:
        return False
    return True


def name_ratio(trade_name: str, kapt_name: str) -> float:
    a, b = split_name(trade_name)[0], split_name(kapt_name)[0]
    if not a or not b:
        return 0.0
    return 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()


def loose_ratio(trade_name: str, kapt_name: str) -> float:
    """숫자를 살린 느슨한 비교. 실거래 자료는 '4단지'를 '신동아4', '2단지'를 '우성2' 처럼 줄여 쓴다."""
    a = re.sub(r"단지|차|제", "", normalize_name(trade_name))
    b = re.sub(r"단지|차|제", "", normalize_name(kapt_name))
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def parse_road(address: str) -> tuple[str, str]:
    """'서울특별시 마포구 마포대로 195' → ('마포대로', '195'). 못 찾으면 ('', '')."""
    found = _ROAD.findall(address or "")
    return found[-1] if found else ("", "")


def bonbun(jibun: str) -> str:
    return (jibun or "").split("-")[0].strip()


def _year(value) -> int | None:
    text = str(value or "")[:4]
    return int(text) if text.isdigit() else None


class ComplexIndex:
    def __init__(self, complexes: list[dict], overrides: dict[str, str] | None = None):
        self.by_code: dict[str, dict] = {c["kapt_code"]: c for c in complexes}
        self.by_lot: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.by_umd: dict[str, list[dict]] = defaultdict(list)
        self.by_apt_seq: dict[str, str] = {}
        self.by_alt_lot: dict[tuple[str, str], str] = {}
        self.road: dict[str, tuple[str, str]] = {}
        self.overrides = {k: v for k, v in (overrides or {}).items() if not k.startswith("_")}
        for c in complexes:
            umd, jibun = c.get("umd", ""), c.get("jibun", "")
            self.road[c["kapt_code"]] = parse_road(c.get("road_address", ""))
            if umd:
                self.by_umd[umd].append(c)
                if jibun:
                    self.by_lot[(umd, jibun)].append(c)
            for seq in c.get("apt_seqs") or []:
                self.by_apt_seq[seq] = c["kapt_code"]
            for lot in c.get("alt_lots") or []:
                lot_umd, _, lot_jibun = lot.partition("|")
                self.by_alt_lot[(lot_umd, lot_jibun)] = c["kapt_code"]

    # ---- 학습 (확정된 연결을 단지에 기록해 다음에도 같은 결과가 나오게 한다) ----
    def _learn(self, c: dict, umd: str, jibun: str, apt_seq: str) -> dict:
        if apt_seq:
            self.by_apt_seq[apt_seq] = c["kapt_code"]
            seqs = c.setdefault("apt_seqs", [])
            if apt_seq not in seqs:
                seqs.append(apt_seq)
        if umd and jibun and jibun != c.get("jibun") and (umd, jibun) not in self.by_lot:
            self.by_alt_lot[(umd, jibun)] = c["kapt_code"]
            lots = c.setdefault("alt_lots", [])
            key = f"{umd}|{jibun}"
            if key not in lots:
                lots.append(key)
        return c

    def _best_by_name(self, candidates: list[dict], name: str) -> dict:
        """한 지번에 단지가 여럿일 때(예: 사당동 105 의 극동·신동아4단지·우성2단지) 이름이 가장 가까운 것."""
        if len(candidates) == 1:
            return candidates[0]
        return max(candidates, key=lambda c: loose_ratio(name, c["name"]))

    def _score(self, c: dict, name: str, build_year, road_name: str, road_no: str) -> tuple[int, float]:
        """(규칙 등급, 이름 유사도). 등급 0 은 연결하지 않음."""
        ratio = name_ratio(name, c["name"])
        k_road, k_no = self.road.get(c["kapt_code"], ("", ""))
        approved, built = _year(c.get("approved")), _year(build_year)
        year_ok = approved is not None and built is not None and abs(approved - built) <= 1
        compatible = ordinals_compatible(name, c["name"])
        if road_name:
            if road_name != k_road:
                return 0, ratio
            if road_no and road_no == k_no:
                return 4, ratio                     # A
            if compatible and ratio == 1.0:
                return 3, ratio                     # B
            if compatible and ratio >= 0.9 and year_ok:
                return 2, ratio                     # C
            return 0, ratio
        if compatible and ratio == 1.0 and year_ok:
            return 1, ratio                         # D
        return 0, ratio

    def match(self, umd: str, jibun: str, name: str, apt_seq: str = "", build_year=None,
              road_name: str = "", road_no: str = "") -> dict | None:
        if apt_seq and apt_seq in self.overrides:
            found = self.by_code.get(self.overrides[apt_seq])
            return self._learn(found, umd, jibun, apt_seq) if found else None
        if apt_seq and apt_seq in self.by_apt_seq:
            found = self.by_code.get(self.by_apt_seq[apt_seq])
            if found:
                return self._learn(found, umd, jibun, apt_seq)
        exact = self.by_lot.get((umd, jibun))
        if exact:
            return self._learn(self._best_by_name(exact, name), umd, jibun, apt_seq)
        if (umd, jibun) in self.by_alt_lot:
            found = self.by_code.get(self.by_alt_lot[(umd, jibun)])
            if found:
                return self._learn(found, umd, jibun, apt_seq)

        best, best_score = None, (0, 0.0)
        for c in self.by_umd.get(umd, []):
            score = self._score(c, name, build_year, road_name, road_no)
            if score > best_score:
                best, best_score = c, score
        if best is None or best_score[0] == 0:
            return None
        return self._learn(best, umd, jibun, apt_seq)

    def reset_learned(self) -> None:
        """저장된 연결(aptSeq, 지번 별칭)을 모두 버린다. 규칙이 바뀌었을 때 쓴다."""
        self.by_apt_seq.clear()
        self.by_alt_lot.clear()
        for c in self.by_code.values():
            c["apt_seqs"] = []
            c["alt_lots"] = []
