"""JSON 파일 읽기/쓰기."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def now_kst() -> datetime:
    return datetime.now(KST)


def now_iso() -> str:
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S+09:00")


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        if compact:
            json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def month_list(months_back: int, end: datetime | None = None) -> list[str]:
    """이번 달부터 거슬러 months_back 개월의 YYYYMM 목록 (오래된 순)."""
    end = end or now_kst()
    year, month = end.year, end.month
    out = []
    for _ in range(months_back):
        out.append(f"{year:04d}{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(out))
