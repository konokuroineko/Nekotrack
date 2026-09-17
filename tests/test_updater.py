"""Tests for updater.py version comparison and release scanning (offline)."""


from updater import _version_key, is_newer


class TestVersionKey:
    def test_plain_stable(self):
        assert _version_key("1.2.3") == (1, 2, 3, 4, 0)

    def test_leading_v_stripped(self):
        assert _version_key("v0.1.0") == (0, 1, 0, 4, 0)

    def test_beta_stage(self):
        assert _version_key("0.1.0-beta.2") == (0, 1, 0, 2, 2)

    def test_stage_rank_order(self):
        assert _version_key("0.1.0-dev.1") < _version_key("0.1.0-alpha.1") < _version_key("0.1.0-beta.1") < _version_key("0.1.0-rc.1") < _version_key("0.1.0")

    def test_invalid_returns_zeroes(self):
        assert _version_key("garbage") == (0, 0, 0, -1, 0)

    def test_pre_release_number_counts(self):
        assert _version_key("1.0.0-beta.1") < _version_key("1.0.0-beta.2")


class TestIsNewer:
    def test_same_version_not_newer(self):
        assert not is_newer("0.1.0-beta.2", "0.1.0-beta.2")

    def test_patch_bump_is_newer(self):
        assert is_newer("0.1.1", "0.1.0-beta.2")

    def test_stable_same_version_beats_beta(self):
        assert is_newer("0.1.0", "0.1.0-beta.2")

    def test_older_not_newer(self):
        assert not is_newer("0.0.9", "0.1.0")

    def test_newer_beta_is_newer(self):
        assert is_newer("0.2.0-beta.1", "0.1.0-beta.2")

    def test_invalid_remote_never_newer(self):
        assert not is_newer("not-a-version", "0.1.0")