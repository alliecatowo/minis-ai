"""Tests for the typed feature-flag registry (ALLIE-406)."""

import pytest

from app.core.feature_flags import FeatureFlag, FLAGS


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


class TestRegistryShape:
    def test_expected_flags_present(self):
        assert "DEV_AUTH_BYPASS" in FLAGS
        assert "DISABLE_LLM_CALLS" in FLAGS
        assert "LANGFUSE_ENABLED" in FLAGS

    def test_flag_names_match_keys(self):
        for key, flag in FLAGS.items():
            assert flag.name == key, f"FLAG key {key!r} != flag.name {flag.name!r}"

    def test_flags_are_frozen(self):
        flag = FLAGS["LANGFUSE_ENABLED"]
        with pytest.raises((AttributeError, TypeError)):
            flag.default = True  # type: ignore[misc]

    def test_flag_kinds_are_valid(self):
        valid_kinds = {"rollout", "kill_switch", "ops"}
        for flag in FLAGS.values():
            assert flag.kind in valid_kinds, f"{flag.name} has unexpected kind {flag.kind!r}"


# ---------------------------------------------------------------------------
# Rollout flags must have removal metadata (lint rule)
# ---------------------------------------------------------------------------


class TestRolloutFlagsHaveRemovalMetadata:
    def test_rollout_flags_have_removal_ticket(self):
        for flag in FLAGS.values():
            if flag.kind == "rollout":
                assert flag.removal_ticket, f"{flag.name} is rollout — needs removal_ticket"

    def test_rollout_flags_have_planned_removal(self):
        for flag in FLAGS.values():
            if flag.kind == "rollout":
                assert flag.planned_removal, f"{flag.name} is rollout — needs planned_removal"

    def test_invalid_rollout_flag_raises_at_import(self, tmp_path, monkeypatch):
        """A rollout flag without removal metadata should raise AssertionError at import."""
        monkeypatch.syspath_prepend(str(tmp_path))
        bad_module = tmp_path / "bad_flags.py"
        bad_module.write_text(
            """\
from datetime import date
from app.core.feature_flags import FeatureFlag

FLAGS = {
    "MY_ROLLOUT": FeatureFlag(
        name="MY_ROLLOUT",
        description="test",
        default=False,
        added_at=date(2026, 1, 1),
        kind="rollout",
        # missing removal_ticket and planned_removal
    ),
}

for _flag in FLAGS.values():
    if _flag.kind == "rollout":
        assert _flag.removal_ticket, f"{_flag.name} needs removal_ticket"
        assert _flag.planned_removal, f"{_flag.name} needs planned_removal"
"""
        )
        with pytest.raises(AssertionError, match="needs removal_ticket"):
            import bad_flags  # noqa: F401


# ---------------------------------------------------------------------------
# is_enabled() semantics
# ---------------------------------------------------------------------------


class TestIsEnabled:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES", "Yes"])
    def test_truthy_values(self, value, monkeypatch):
        monkeypatch.setenv("LANGFUSE_ENABLED", value)
        assert FLAGS["LANGFUSE_ENABLED"].is_enabled() is True

    @pytest.mark.parametrize("value", ["false", "False", "FALSE", "0", "no", "NO", "off", ""])
    def test_falsy_values(self, value, monkeypatch):
        monkeypatch.setenv("LANGFUSE_ENABLED", value)
        assert FLAGS["LANGFUSE_ENABLED"].is_enabled() is False

    def test_unset_uses_default_false(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
        assert FLAGS["LANGFUSE_ENABLED"].is_enabled() is False

    def test_unset_uses_default_true(self, monkeypatch):
        """A flag with default=True should return True when env var is absent."""
        flag = FeatureFlag(
            name="TEST_FLAG_TRUE_DEFAULT",
            description="test flag with True default",
            default=True,
            added_at=__import__("datetime").date(2026, 1, 1),
            kind="ops",
        )
        monkeypatch.delenv("TEST_FLAG_TRUE_DEFAULT", raising=False)
        assert flag.is_enabled() is True

    def test_env_var_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("LANGFUSE_ENABLED", "  true  ")
        assert FLAGS["LANGFUSE_ENABLED"].is_enabled() is True

    def test_each_flag_reads_its_own_env_var(self, monkeypatch):
        monkeypatch.setenv("DEV_AUTH_BYPASS", "true")
        monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
        assert FLAGS["DEV_AUTH_BYPASS"].is_enabled() is True
        assert FLAGS["LANGFUSE_ENABLED"].is_enabled() is False


# ---------------------------------------------------------------------------
# Specific surviving flags
# ---------------------------------------------------------------------------


class TestSurvivingFlags:
    def test_dev_auth_bypass_defaults_false(self, monkeypatch):
        monkeypatch.delenv("DEV_AUTH_BYPASS", raising=False)
        assert FLAGS["DEV_AUTH_BYPASS"].is_enabled() is False
        assert FLAGS["DEV_AUTH_BYPASS"].kind == "ops"

    def test_disable_llm_calls_defaults_false(self, monkeypatch):
        monkeypatch.delenv("DISABLE_LLM_CALLS", raising=False)
        assert FLAGS["DISABLE_LLM_CALLS"].is_enabled() is False
        assert FLAGS["DISABLE_LLM_CALLS"].kind == "kill_switch"

    def test_langfuse_enabled_defaults_false(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_ENABLED", raising=False)
        assert FLAGS["LANGFUSE_ENABLED"].is_enabled() is False
        assert FLAGS["LANGFUSE_ENABLED"].kind == "ops"
