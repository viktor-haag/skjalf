"""Thread/process pool utilities for background work."""

from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import TypeVar

from ..config import THREAD_WORKERS, PROCESS_WORKERS

T = TypeVar("T")


class WorkerPool:
    """Manages shared executors for the Core orchestrator.

    - ``run_io`` submits lightweight I/O-bound tasks to a thread pool.
    - ``run_cpu`` submits heavy CPU-bound tasks to a process pool.
    """

    def __init__(self, thread_workers: int = THREAD_WORKERS, process_workers: int = PROCESS_WORKERS) -> None:
        self.threads = ThreadPoolExecutor(max_workers=thread_workers)
        self.processes = ProcessPoolExecutor(max_workers=process_workers)

    def run_io(self, func: Callable[..., T], *args, **kwargs):
        """Submit a lightweight I/O-bound callable to the thread pool."""
        return self.threads.submit(func, *args, **kwargs)

    def run_cpu(self, func: Callable[..., T], *args, **kwargs):
        """Submit a heavy CPU-bound callable to the process pool."""
        return self.processes.submit(func, *args, **kwargs)

    def shutdown(self) -> None:
        """Shut down both pools without waiting for pending tasks."""
        self.threads.shutdown(wait=False)
        self.processes.shutdown(wait=False)
