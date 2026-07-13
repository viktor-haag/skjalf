"""Background version check via GitHub Releases API."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal

GITHUB_RELEASES_URL = "https://api.github.com/repos/viktor-haag/skjalf/releases/latest"


@dataclass
class VersionCheckResult:
    """Result of a version check."""

    available: bool
    current_version: str
    latest_version: str


class _VersionCheckWorker(QThread):
    """Background thread that queries GitHub Releases API."""

    finished = Signal(object)  # Emits VersionCheckResult

    def __init__(self, current_version: str):
        super().__init__()
        self._current_version = current_version

    def run(self):
        try:
            req = urllib.request.Request(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github.v3+json"},
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())

            # Extract the latest tag name (e.g., "v1.0.2") and strip the "v" prefix
            latest_tag = data.get("tag_name", "")
            if latest_tag.startswith("v"):
                latest_version = latest_tag[1:]
            else:
                latest_version = latest_tag

            # Compare versions: available if latest is strictly greater
            available = (
                self._compare_versions(self._current_version, latest_version) < 0
            )

            self.finished.emit(
                VersionCheckResult(
                    available=available,
                    current_version=self._current_version,
                    latest_version=latest_version,
                )
            )
        except Exception as e:
            # On any error (network timeout, HTTP error, parse error),
            # silently fall back — treat as "no update available"
            self.finished.emit(
                VersionCheckResult(
                    available=False,
                    current_version=self._current_version,
                    latest_version="?",
                )
            )

    @staticmethod
    def _compare_versions(v1: str, v2: str) -> int:
        """Compare two version strings (e.g., '1.0.1' vs '1.0.2').

        Returns -1 if v1 < v2, 0 if equal, 1 if v1 > v2.
        """
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        # Pad shorter version with zeros
        max_len = max(len(parts1), len(parts2))
        parts1.extend([0] * (max_len - len(parts1)))
        parts2.extend([0] * (max_len - len(parts2)))

        for a, b in zip(parts1, parts2):
            if a < b:
                return -1
            if a > b:
                return 1
        return 0


def check_for_updates(
    current_version: str, callback=None
) -> _VersionCheckWorker:
    """Start a background version check. Returns the fully wired-up worker."""
    worker = _VersionCheckWorker(current_version)
    if callback is not None:
        worker.finished.connect(callback)
    worker.start()
    return worker
