from __future__ import annotations

from typer.testing import CliRunner

import cli as minis_cli


runner = CliRunner()


_FRAMEWORK_HIGH = {
    "framework_id": "fw-readability",
    "trigger": "code review with poor naming",
    "action": "request rename",
    "value": "value:readability",
    "confidence": 0.85,
    "revision": 3,
}

_FRAMEWORK_MID = {
    "framework_id": "fw-tests",
    "trigger": "new public API without tests",
    "action": "block until covered",
    "value": "value:correctness",
    "confidence": 0.55,
    "revision": 1,
}

_FRAMEWORK_LOW = {
    "framework_id": "fw-style",
    "trigger": "minor style nit",
    "action": "leave comment",
    "value": "value:consistency",
    "confidence": 0.20,
    "revision": 0,
}


def _payload(frameworks: list[dict]) -> dict:
    return {
        "username": "testdev",
        "frameworks": frameworks,
        "summary": {
            "total": len(frameworks),
            "mean_confidence": (
                sum(float(fw["confidence"]) for fw in frameworks) / len(frameworks)
                if frameworks
                else 0.0
            ),
            "max_revision": max((int(fw["revision"]) for fw in frameworks), default=0),
        },
    }


def _invoke(args: list[str], monkeypatch, payload: dict):
    captured: dict[str, str] = {}

    def fake_get_json(path: str, **kwargs):
        captured["path"] = path
        return payload

    monkeypatch.setattr(minis_cli, "_get_json", fake_get_json)
    result = runner.invoke(minis_cli.app, ["decision-frameworks", *args])
    return result, captured


def test_happy_path_shows_all_frameworks(monkeypatch):
    result, captured = _invoke(
        ["testdev"],
        monkeypatch,
        _payload([_FRAMEWORK_HIGH, _FRAMEWORK_MID, _FRAMEWORK_LOW]),
    )

    assert result.exit_code == 0, result.output
    assert "fw-readability" in result.output
    assert "fw-tests" in result.output
    assert "fw-style" in result.output
    assert "HIGH CONFIDENCE" in result.output
    assert "LOW CONFIDENCE" in result.output
    assert "limit=20" in captured["path"]
    assert "min_confidence=0.0" in captured["path"]


def test_no_frameworks_exits_nonzero(monkeypatch):
    result, _captured = _invoke(["testdev"], monkeypatch, _payload([]))

    assert result.exit_code == 1
    assert "No decision frameworks" in result.output


def test_query_params_include_min_confidence_and_limit(monkeypatch):
    result, captured = _invoke(
        ["testdev", "--min-confidence", "0.5", "--limit", "1"],
        monkeypatch,
        _payload([_FRAMEWORK_HIGH]),
    )

    assert result.exit_code == 0, result.output
    assert "limit=1" in captured["path"]
    assert "min_confidence=0.5" in captured["path"]


def test_revision_validated_badge_singular(monkeypatch):
    fw_one_rev = {**_FRAMEWORK_MID, "revision": 1, "framework_id": "fw-one-rev"}
    result, _captured = _invoke(["testdev"], monkeypatch, _payload([fw_one_rev]))

    assert result.exit_code == 0, result.output
    assert "fw-one-rev" in result.output
    badge = minis_cli._confidence_badge(0.55, 1)
    assert "validated 1 time" in badge
    assert "validated 1 times" not in badge


def test_summary_shows_mean_confidence_and_max_revision(monkeypatch):
    result, _captured = _invoke(
        ["testdev"],
        monkeypatch,
        _payload([_FRAMEWORK_HIGH, _FRAMEWORK_MID]),
    )

    assert result.exit_code == 0, result.output
    assert "70.0%" in result.output
    assert "3" in result.output
