from __future__ import annotations

import pytest

from scripts.live_sandbox_e2e import (
    ConfigError,
    _poll_until,
    _has_mini_signature,
    _is_expected_bot,
    load_config,
    post_mention_comment,
)


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_APP_SANDBOX_TOKEN", "token")
    monkeypatch.setenv("GH_APP_SANDBOX_REVIEWER_TOKEN", "reviewer-token")
    monkeypatch.setenv("GH_APP_SANDBOX_REPO", "alliecatowo/minis-ai-sandbox")
    monkeypatch.setenv("GH_APP_SANDBOX_ALLOWED_REPO", "alliecatowo/minis-ai-sandbox")
    monkeypatch.setenv("GH_APP_SANDBOX_REVIEWER", "alliecatowo")
    monkeypatch.setenv("GH_APP_SANDBOX_MINI_USERNAME", "alliecatowo")
    monkeypatch.setenv("GH_APP_SANDBOX_MINIS_API_URL", "https://api.minis.test/")
    monkeypatch.setenv("GH_APP_SANDBOX_TRUSTED_SERVICE_SECRET", "trusted-secret")


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
    assert cfg.reviewer_token == "reviewer-token"
    assert cfg.minis_api_url == "https://api.minis.test"
    assert cfg.trusted_service_secret == "trusted-secret"
    assert cfg.bot_login == "minis-ai[bot]"
    assert cfg.timeout_seconds == 45


def test_load_config_requires_reviewer_token_for_outcome_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("GH_APP_SANDBOX_REVIEWER_TOKEN")

    with pytest.raises(ConfigError, match="GH_APP_SANDBOX_REVIEWER_TOKEN"):
        load_config()


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


@pytest.mark.asyncio
async def test_mention_smoke_uses_non_reviewer_mode_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    cfg = load_config()
    calls: list[dict] = []

    class ClientStub:
        async def request(self, method: str, path: str, **kwargs):
            calls.append({"method": method, "path": path, **kwargs})
            return {"id": 123}

    await post_mention_comment(ClientStub(), cfg, 99)

    body = calls[0]["json"]["body"]
    assert "@alliecatowo-mini" in body
    assert "what do you think" in body
    assert "please review" not in body.lower()


@pytest.mark.asyncio
async def test_poll_timeout_includes_last_observation() -> None:
    async def probe():
        return None, 2, {"candidate_ids": [1, 2]}

    with pytest.raises(TimeoutError, match="candidate_ids"):
        await _poll_until(
            timeout_seconds=0.01,
            interval_seconds=1,
            probe=probe,
            description="sandbox diagnostic target",
        )
