"""실행 진입점.

  python -m collector.main complexes   # 단지 마스터 생성/갱신
  python -m collector.main collect     # 실거래 수집 + 변화 감지 + 요약
  python -m collector.main notify      # 최근 변화를 웹 푸시로 발송
  python -m collector.main all         # collect + notify (단지 마스터 없으면 complexes 먼저)
"""
from __future__ import annotations

import argparse
import logging
import sys

from . import config
from .store import read_json, write_json

log = logging.getLogger("collector")


def _require(name: str) -> str:
    value = config.env(name)
    if not value:
        sys.exit(f"환경변수 {name} 가 필요합니다.")
    return config.clean_service_key(value) if name == "DATA_GO_KR_KEY" else value.strip()


def cmd_complexes(args) -> None:
    from .build_complexes import build

    before = {c["kapt_code"] for c in read_json(config.COMPLEXES_FILE, {}).get("complexes", [])}
    result = build(_require("DATA_GO_KR_KEY"), config.env("KAKAO_REST_KEY"), geocode=not args.no_geocode, full=args.full)
    after = {c["kapt_code"] for c in result}
    if reset_state_if_complexes_changed(before, after):
        log.info("단지 구성이 바뀌어(+%d, -%d) 기준 상태를 초기화했습니다. 다음 수집은 알림 없이 전체 기간을 다시 받습니다.",
                 len(after - before), len(before - after))


def reset_state_if_complexes_changed(before: set[str], after: set[str]) -> bool:
    """새 단지가 들어오면 state.json 을 지운다.

    새로 들어온 단지의 과거 거래가 "신규 거래"로 잡혀 알림이 쏟아지는 것을 막고,
    그 단지도 전체 기간(BACKFILL_MONTHS)을 받게 하기 위해서다.
    """
    # 단지가 빠지기만 한 경우에는 다시 받을 것도, 가짜 알림이 생길 일도 없다.
    if not (after - before) or not config.STATE_FILE.exists():
        return False
    config.STATE_FILE.unlink()
    return True


def cmd_collect(args) -> None:
    from .collect_trades import collect, load_complexes, needs_rematch
    from .diff import compute_events, load_state, save_changes, update_state
    from .summary import build_summary

    rematch = needs_rematch()
    if rematch:
        # 연결 규칙이 바뀌면 거래가 다른 단지로 옮겨 간다. 알림 없이 전체 기간을 다시 맞춘다.
        log.info("연결 규칙이 바뀌어 저장된 연결을 버리고 전체 기간을 다시 받습니다.")
        config.STATE_FILE.unlink(missing_ok=True)
    first_run = not config.STATE_FILE.exists()
    state = load_state()
    months = None if rematch else (args.months.split(",") if args.months else None)
    result = collect(_require("DATA_GO_KR_KEY"), months, rematch=rematch)
    complexes = load_complexes()
    events = [] if first_run else compute_events(state, result["sales_by"], result["rents_by"], complexes)
    save_changes(events, first_run)
    write_json(config.STATE_FILE, update_state(state, result["sales_by"], result["rents_by"]), compact=True)
    build_summary(complexes, events)
    log.info("변화 %d건 (첫 실행=%s)", len(events), first_run)


def cmd_notify(args) -> None:
    from .notify_push import send_for_changes

    changes = read_json(config.LATEST_CHANGES_FILE, {"events": [], "first_run": True})
    if changes.get("first_run"):
        log.info("첫 실행이라 알림을 보내지 않습니다.")
        return
    send_for_changes(changes.get("events", []), dry_run=args.dry_run)


def cmd_all(args) -> None:
    if not config.COMPLEXES_FILE.exists():
        cmd_complexes(args)
    cmd_collect(args)
    cmd_notify(args)


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("complexes")
    p.add_argument("--no-geocode", action="store_true")
    p.add_argument("--full", action="store_true", help="이미 아는 단지도 전부 다시 조회")
    p.set_defaults(func=cmd_complexes)

    p = sub.add_parser("collect")
    p.add_argument("--months", help="YYYYMM 를 쉼표로 (기본: 첫 실행 24개월, 이후 6개월)")
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("notify")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_notify)

    p = sub.add_parser("all")
    p.add_argument("--no-geocode", action="store_true")
    p.add_argument("--full", action="store_true")
    p.add_argument("--months")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
