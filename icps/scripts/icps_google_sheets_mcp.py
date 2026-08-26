# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "mcp<2",
#   "mcp-google-sheets==0.6.3",
# ]
# ///
"""Codex launcher for mcp-google-sheets with stale-connection recovery."""

from __future__ import annotations

import errno
import ssl
import time
from collections.abc import Callable
from typing import Any


_RETRYABLE_ERRNOS = {
    errno.ECONNABORTED,
    errno.ECONNREFUSED,
    errno.ECONNRESET,
    errno.EPIPE,
    errno.ETIMEDOUT,
}
_MAX_ATTEMPTS = 3


def _is_retryable_transport_error(error: BaseException) -> bool:
    if isinstance(error, (ConnectionError, TimeoutError, ssl.SSLError)):
        return True
    return isinstance(error, OSError) and error.errno in _RETRYABLE_ERRNOS


def _close_transport(http: Any) -> None:
    try:
        http.close()
    except Exception:
        # Preserve the request failure; the next request still rebuilds lazily.
        pass


def _execute_with_recovery(
    original_execute: Callable[..., Any],
    request: Any,
    *,
    http: Any = None,
    num_retries: int = 0,
) -> Any:
    transport = http if http is not None else request.http

    for attempt in range(_MAX_ATTEMPTS):
        try:
            return original_execute(request, http=transport, num_retries=num_retries)
        except Exception as error:
            if not _is_retryable_transport_error(error):
                raise
            _close_transport(transport)
            if attempt == _MAX_ATTEMPTS - 1:
                raise
            time.sleep(0.25 * (2**attempt))

    raise AssertionError("unreachable")


def _install_transport_recovery() -> None:
    from googleapiclient.http import HttpRequest

    original_execute = HttpRequest.execute

    def execute(self: Any, http: Any = None, num_retries: int = 0) -> Any:
        return _execute_with_recovery(
            original_execute,
            self,
            http=http,
            num_retries=num_retries,
        )

    HttpRequest.execute = execute


def main() -> None:
    _install_transport_recovery()
    from mcp_google_sheets.server import main as upstream_main

    upstream_main()


if __name__ == "__main__":
    main()
