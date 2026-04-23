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

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from zep_cloud import InternalServerError

from app.core.backend_client_factory.schema import ZepClientAdapter
from app.core.utils.logger import get_logger

logger = get_logger("z_graph.retrieval")

_DEFAULT_PAGE_SIZE = 100
_MAX_NODES = 2000
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_DELAY = 2.0  # seconds, doubles each retry



def _fetch_page_with_retry(
    api_call: Callable[..., list[Any]],
    *args: Any,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
    page_description: str = "page",
    **kwargs: Any,
) -> list[Any]:
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    last_exception: Exception | None = None
    delay = retry_delay

    for attempt in range(max_retries):
        try:
            return api_call(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError, InternalServerError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                logger.warning(
                    f"Zep {page_description} attempt {attempt + 1} failed: {str(e)[:100]}, retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(
                    f"Zep {page_description} failed after {max_retries} attempts: {str(e)}"
                )

    assert last_exception is not None
    raise last_exception


def fetch_all_nodes(
    client: ZepClientAdapter,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,  # Kept for compatibility.
    max_items: int | None = _MAX_NODES,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    del page_size
    nodes = _fetch_page_with_retry(
        client.get_all_nodes,
        graph_id,
        max_retries=max_retries,
        retry_delay=retry_delay,
        page_description=f"fetch all nodes (graph={graph_id})",
    )
    if max_items is not None and len(nodes) > max_items:
        logger.warning(
            f"Node count reached limit ({max_items}), truncating adapter result for graph {graph_id}"
        )
        return nodes[:max_items]
    return nodes


def fetch_all_edges(
    client: ZepClientAdapter,
    graph_id: str,
    page_size: int = _DEFAULT_PAGE_SIZE,  # Kept for compatibility.
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> list[Any]:
    del page_size
    return _fetch_page_with_retry(
        client.get_all_edges,
        graph_id,
        max_retries=max_retries,
        retry_delay=retry_delay,
        page_description=f"fetch all edges (graph={graph_id})",
    )
