"""Tests for version check (pure logic, no network)."""

from skjalf.view.version_check import VersionCheckResult, _VersionCheckWorker


class TestCompareVersions:
    def test_equal_versions(self):
        assert _VersionCheckWorker._compare_versions("1.0.0", "1.0.0") == 0

    def test_v1_less_than_v2(self):
        assert _VersionCheckWorker._compare_versions("1.0.0", "1.0.1") == -1

    def test_v1_greater_than_v2(self):
        assert _VersionCheckWorker._compare_versions("1.0.1", "1.0.0") == 1

    def test_major_version_diff(self):
        assert _VersionCheckWorker._compare_versions("1.0.0", "2.0.0") == -1

    def test_minor_version_diff(self):
        assert _VersionCheckWorker._compare_versions("1.1.0", "1.2.0") == -1

    def test_different_length_versions(self):
        assert _VersionCheckWorker._compare_versions("1.0", "1.0.1") == -1

    def test_single_part_version(self):
        assert _VersionCheckWorker._compare_versions("1", "2") == -1


class TestVersionCheckResult:
    def test_update_available(self):
        r = VersionCheckResult(
            available=True, current_version="1.0.0", latest_version="1.0.1"
        )
        assert r.available is True
        assert r.current_version == "1.0.0"
        assert r.latest_version == "1.0.1"

    def test_no_update(self):
        r = VersionCheckResult(
            available=False, current_version="2.0.0", latest_version="1.0.0"
        )
        assert r.available is False
