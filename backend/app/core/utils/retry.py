"""
Copyright (c) 2026 Richard G and contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
from collections.abc import Callable
from typing import TypeVar

from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

T = TypeVar("T")


def _build_before_sleep_hook(operation_name: str, logger: logging.Logger) -> Callable[[RetryCallState], None]:
    def _before_sleep(retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        attempt = retry_state.attempt_number
        sleep_s = retry_state.next_action.sleep if retry_state.next_action else 0
        logger.warning(
            f"{operation_name} retry attempt {attempt} failed: {str(exc)[:200]}. "
            f"Retrying in {sleep_s:.1f}s..."
        )

    return _before_sleep


def call_with_retry(
    func: Callable[[], T],
    operation_name: str,
    logger: logging.Logger,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    max_delay: float = 30.0,
) -> T:
    retrying = Retrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=initial_delay, min=initial_delay, max=max_delay),
        retry=retry_if_exception_type(Exception),
        before_sleep=_build_before_sleep_hook(operation_name=operation_name, logger=logger),
        reraise=True,
    )

    for attempt in retrying:
        with attempt:
            return func()

    # Unreachable due to reraise=True, kept for type checkers.
    raise RuntimeError(f"{operation_name} failed unexpectedly")
