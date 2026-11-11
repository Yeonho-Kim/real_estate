"""재시도·대기가 포함된 간단한 HTTP 호출 도우미."""
from __future__ import annotations

import logging
import re
import time

import requests

from . import config

log = logging.getLogger(__name__)

_KEY_RE = re.compile(r"(?i)((?:service)?key=)[^&\s'\")]+")
_AUTH_RE = re.compile(r"(?i)(KakaoAK\s+)\S+")


class ApiError(RuntimeError):
    pass


def redact(text: object) -> str:
    """오류 문구에 섞인 인증키를 가린다. (공개 저장소의 Actions 로그는 누구나 볼 수 있다)"""
    return _AUTH_RE.sub(r"\1***", _KEY_RE.sub(r"\1***", str(text)))


def get(url: str, params: dict, headers: dict | None = None) -> requests.Response:
    last_error = ""
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code >= 500 or resp.status_code == 429:
                raise ApiError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_PER_SECOND" in resp.text[:600]:
                raise ApiError("초당 요청 한도 초과")
            time.sleep(config.REQUEST_SLEEP)
            return resp
        except (requests.RequestException, ApiError) as exc:  # noqa: PERF203
            last_error = redact(exc)
            wait = 2 ** attempt
            log.warning("요청 실패 (%s/%s) %s -> %s초 뒤 재시도", attempt, config.REQUEST_RETRIES, last_error, wait)
            time.sleep(wait)
    raise ApiError(f"재시도 후에도 실패: {url} {last_error}")
