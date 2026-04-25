from __future__ import annotations

import pytest

from scripts.live_sandbox_e2e import (
    ConfigError,
    _has_mini_signature,
    _is_expected_bot,
    load_config,
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_APP_SANDBOX_TOKEN", "token")
    monkeypatch.setenv("GH_APP_SANDBOX_REPO", "alliecatowo/minis-ai-sandbox")
    monkeypatch.setenv("GH_APP_SANDBOX_ALLOWED_REPO", "alliecatowo/minis-ai-sandbox")
    monkeypatch.setenv("GH_APP_SANDBOX_REVIEWER", "alliecatowo")
    monkeypatch.setenv("GH_APP_SANDBOX_MINI_USERNAME", "alliecatowo")


def test_load_config_requires_exact_allowlisted_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GH_APP_SANDBOX_ALLOWED_REPO", "alliecatowo/other-repo")

    with pytest.raises(ConfigError, match="non-allowlisted"):
        load_config()


def test_load_config_accepts_sandbox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("GH_APP_BOT_LOGIN", "minis-ai[bot]")
    monkeypatch.setenv("LIVE_GH_APP_E2E_TIMEOUT_SECONDS", "45")

    cfg = load_config()

    assert cfg.owner == "alliecatowo"
    assert cfg.repo_name == "minis-ai-sandbox"
    assert cfg.bot_login == "minis-ai[bot]"
    assert cfg.timeout_seconds == 45


def test_expected_bot_match_supports_exact_login_and_generic_bot() -> None:
    review = {"user": {"login": "minis-ai[bot]", "type": "Bot"}}

    assert _is_expected_bot(review, "minis-ai[bot]")
    assert not _is_expected_bot(review, "other[bot]")
    assert _is_expected_bot(review, None)


def test_mini_signature_requires_identity_and_product_footer() -> None:
    body = (
        "### Review by @alliecatowo's mini\n\n"
        "Reviewer mode: structured prediction.\n\n"
        "using the Minis backend review-prediction API"
    )

    assert _has_mini_signature(body, "alliecatowo")
    assert not _has_mini_signature(body, "jlongster")
    assert not _has_mini_signature("### Review by @alliecatowo's mini", "alliecatowo")
