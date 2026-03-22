"""
Worker thread utilities for offloading heavy work from the main UI thread.
Provides a reusable QThread-based runner that executes a callable off-thread
and delivers results via signal on the main thread.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import QThread, pyqtSignal, QObject


class _WorkerRunner(QObject):
    """Runs a callable inside a QThread and emits completed/error signals."""

    finished = pyqtSignal(object)  # result
    error = pyqtSignal(str)  # error message

    def __init__(self, fn: Callable[..., Any], args: tuple = (), kwargs: dict | None = None):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs or {}

    def run(self) -> None:  # noqa: D401
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001 – intentional broad catch
            self.error.emit(str(exc))


class WorkerThread:
    """
    Fire-and-forget helper that runs *fn* on a background QThread.

    Usage::

        def heavy_work():
            return psutil.process_iter(...)

        worker = WorkerThread(heavy_work, on_result=self._handle_result)
        worker.start()

    The instance must be kept alive (store as ``self._worker = ...``) until
    the callback fires, otherwise the QThread may be garbage-collected early.
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        args: tuple = (),
        kwargs: dict | None = None,
        on_result: Optional[Callable[[Any], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        parent: Optional[QObject] = None,  # noqa: ARG002 – kept for reference
    ):
        self._thread = QThread()
        self._runner = _WorkerRunner(fn, args, kwargs)
        self._runner.moveToThread(self._thread)

        # Wire signals
        self._thread.started.connect(self._runner.run)
        self._runner.finished.connect(self._on_finished)
        self._runner.error.connect(self._on_error)

        self._on_result_cb = on_result
        self._on_error_cb = on_error

    # ── public ────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread.isRunning()

    # ── private ───────────────────────────────────────────────────────────
    def _on_finished(self, result: Any) -> None:
        if self._on_result_cb:
            self._on_result_cb(result)
        self._cleanup()

    def _on_error(self, msg: str) -> None:
        if self._on_error_cb:
            self._on_error_cb(msg)
        else:
            print(f"[WorkerThread ERROR] {msg}")
        self._cleanup()

    def _cleanup(self) -> None:
        self._thread.quit()
        self._thread.wait(2000)
