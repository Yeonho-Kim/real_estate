"""재시도·대기가 포함된 간단한 HTTP 호출 도우미."""
from __future__ import annotations

import logging
import time

import requests

from . import config

log = logging.getLogger(__name__)


class ApiError(RuntimeError):
    pass


def get(url: str, params: dict, headers: dict | None = None) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=config.REQUEST_TIMEOUT)
            if resp.status_code >= 500:
                raise ApiError(f"server error {resp.status_code}: {resp.text[:200]}")
            time.sleep(config.REQUEST_SLEEP)
            return resp
        except (requests.RequestException, ApiError) as exc:  # noqa: PERF203
            last_error = exc
            wait = 2 ** attempt
            log.warning("request failed (%s/%s) %s -> retry in %ss", attempt, config.REQUEST_RETRIES, exc, wait)
            time.sleep(wait)
    raise ApiError(f"request failed after retries: {url} {last_error}")
