import logging
from typing import Callable, TypeVar

from tenacity import Retrying, RetryCallState, retry_if_exception_type, stop_after_attempt, wait_exponential

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
