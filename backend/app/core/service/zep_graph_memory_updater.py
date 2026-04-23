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

Generic Zep episode updater.

Writes arbitrary text episodes to a Zep graph in background batches.
"""

import threading
import time
from queue import Empty, Queue
from typing import Any

from zep_cloud.client import Zep

from app.core.config import Config
from app.core.utils.logger import get_logger
from app.core.utils.retry import call_with_retry

logger = get_logger("z_graph.zep_episode_updater")


class ZepEpisodeUpdater:
    BATCH_SIZE = 5
    SEND_INTERVAL = 0.5
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self, graph_id: str, api_key: str | None = None):
        self.graph_id = graph_id
        self.api_key = api_key or Config.ZEP_API_KEY
        if not self.api_key:
            raise ValueError("ZEP_API_KEY is not configured")

        self.client = Zep(api_key=self.api_key)
        self._episode_queue: Queue[str] = Queue()
        self._buffer: list[str] = []
        self._buffer_lock = threading.Lock()

        self._running = False
        self._worker_thread: threading.Thread | None = None

        self._total_enqueued = 0
        self._total_batches_sent = 0
        self._total_items_sent = 0
        self._failed_count = 0

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"ZepEpisodeUpdater-{self.graph_id[:8]}",
        )
        self._worker_thread.start()

    def stop(self) -> None:
        self._running = False
        self._flush_remaining()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=10)

    def add_episode_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._episode_queue.put(text)
        self._total_enqueued += 1

    def add_episode_texts(self, texts: list[str]) -> None:
        for text in texts:
            self.add_episode_text(text)

    def _worker_loop(self) -> None:
        while self._running or not self._episode_queue.empty():
            try:
                try:
                    episode_text = self._episode_queue.get(timeout=1)
                    with self._buffer_lock:
                        self._buffer.append(episode_text)
                        if len(self._buffer) >= self.BATCH_SIZE:
                            batch = self._buffer[: self.BATCH_SIZE]
                            self._buffer = self._buffer[self.BATCH_SIZE :]
                            self._send_batch(batch)
                            time.sleep(self.SEND_INTERVAL)
                except Empty:
                    pass
            except Exception as exc:
                logger.error(f"Episode worker error: {exc}")
                time.sleep(1)

    def _send_batch(self, episode_texts: list[str]) -> None:
        if not episode_texts:
            return

        combined_text = "\n".join(episode_texts)
        try:
            call_with_retry(
                func=lambda: self.client.graph.add(
                    graph_id=self.graph_id,
                    type="text",
                    data=combined_text,
                ),
                operation_name=f"Zep episode batch send (graph={self.graph_id})",
                logger=logger,
                max_retries=self.MAX_RETRIES,
                initial_delay=self.RETRY_DELAY,
            )
            self._total_batches_sent += 1
            self._total_items_sent += len(episode_texts)
        except Exception as exc:
            self._failed_count += 1
            logger.error(
                f"Failed sending episode batch after {self.MAX_RETRIES} attempts: {exc}"
            )

    def _flush_remaining(self) -> None:
        while not self._episode_queue.empty():
            try:
                self._buffer.append(self._episode_queue.get_nowait())
            except Empty:
                break
        if self._buffer:
            self._send_batch(self._buffer)
            self._buffer = []

    def get_stats(self) -> dict[str, Any]:
        with self._buffer_lock:
            buffered = len(self._buffer)
        return {
            "graph_id": self.graph_id,
            "batch_size": self.BATCH_SIZE,
            "total_enqueued": self._total_enqueued,
            "batches_sent": self._total_batches_sent,
            "items_sent": self._total_items_sent,
            "failed_count": self._failed_count,
            "queue_size": self._episode_queue.qsize(),
            "buffered": buffered,
            "running": self._running,
        }


class ZepEpisodeManager:
    _updaters: dict[str, ZepEpisodeUpdater] = {}
    _lock = threading.Lock()
    _stop_all_done = False

    @classmethod
    def create_updater(cls, updater_id: str, graph_id: str) -> ZepEpisodeUpdater:
        with cls._lock:
            if updater_id in cls._updaters:
                cls._updaters[updater_id].stop()
            updater = ZepEpisodeUpdater(graph_id=graph_id)
            updater.start()
            cls._updaters[updater_id] = updater
            return updater

    @classmethod
    def get_updater(cls, updater_id: str) -> ZepEpisodeUpdater | None:
        return cls._updaters.get(updater_id)

    @classmethod
    def stop_updater(cls, updater_id: str) -> None:
        with cls._lock:
            if updater_id in cls._updaters:
                cls._updaters[updater_id].stop()
                del cls._updaters[updater_id]

    @classmethod
    def stop_all(cls) -> None:
        if cls._stop_all_done:
            return
        cls._stop_all_done = True
        with cls._lock:
            for updater in cls._updaters.values():
                try:
                    updater.stop()
                except Exception as exc:
                    logger.error(f"Failed stopping updater: {exc}")
            cls._updaters.clear()

    @classmethod
    def get_all_stats(cls) -> dict[str, dict[str, Any]]:
        return {updater_id: updater.get_stats() for updater_id, updater in cls._updaters.items()}
