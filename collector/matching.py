"""실거래 레코드를 K-apt 단지에 연결한다.

우선순위: 수동 오버라이드 → 이미 학습된 aptSeq → (법정동, 지번) 일치 → 같은 법정동 안에서 단지명 유사도.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict

_NAME_NOISE = re.compile(r"\(.*?\)|아파트|APT|apt|\s+|[-·,.]")


def normalize_name(name: str) -> str:
    name = _NAME_NOISE.sub("", name or "")
    name = name.replace("단지", "")
    return name.lower()


def bonbun(jibun: str) -> str:
    return (jibun or "").split("-")[0].strip()


class ComplexIndex:
    def __init__(self, complexes: list[dict], overrides: dict[str, str] | None = None):
        self.by_code: dict[str, dict] = {c["kapt_code"]: c for c in complexes}
        self.by_lot: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.by_bonbun: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.by_umd: dict[str, list[dict]] = defaultdict(list)
        self.by_apt_seq: dict[str, str] = {}
        self.overrides = overrides or {}
        for c in complexes:
            umd, jibun = c.get("umd", ""), c.get("jibun", "")
            if umd:
                self.by_umd[umd].append(c)
                if jibun:
                    self.by_lot[(umd, jibun)].append(c)
                    self.by_bonbun[(umd, bonbun(jibun))].append(c)
            for seq in c.get("apt_seqs") or []:
                self.by_apt_seq[seq] = c["kapt_code"]

    def _pick(self, candidates: list[dict], name: str) -> dict | None:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        target = normalize_name(name)
        best = max(candidates, key=lambda c: difflib.SequenceMatcher(None, target, normalize_name(c["name"])).ratio())
        return best

    def _by_name(self, umd: str, name: str, threshold: float = 0.6) -> dict | None:
        target = normalize_name(name)
        if not target:
            return None
        best, best_score = None, 0.0
        for c in self.by_umd.get(umd, []):
            cand = normalize_name(c["name"])
            if not cand:
                continue
            if target == cand or target in cand or cand in target:
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, target, cand).ratio()
            if score > best_score:
                best, best_score = c, score
        return best if best_score >= threshold else None

    def match(self, umd: str, jibun: str, name: str, apt_seq: str = "") -> dict | None:
        if apt_seq and apt_seq in self.overrides:
            return self.by_code.get(self.overrides[apt_seq])
        if apt_seq and apt_seq in self.by_apt_seq:
            return self.by_code.get(self.by_apt_seq[apt_seq])
        found = self._pick(self.by_lot.get((umd, jibun), []), name)
        if not found:
            found = self._pick(self.by_bonbun.get((umd, bonbun(jibun)), []), name)
        if not found:
            found = self._by_name(umd, name)
        if found and apt_seq:
            self.by_apt_seq[apt_seq] = found["kapt_code"]
            seqs = found.setdefault("apt_seqs", [])
            if apt_seq not in seqs:
                seqs.append(apt_seq)
        return found
