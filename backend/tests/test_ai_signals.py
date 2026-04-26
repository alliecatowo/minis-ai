from app.synthesis.ai_signals import score_ai_authorship


def test_ai_flavored_text_scores_higher_and_exposes_markers() -> None:
    ai_text = """Here is a structured breakdown of the migration plan:

- Phase 1: Design decisions, implementation details, and rollout steps.
  - Validate schema, test coverage, and production constraints.
  - Confirm observability, fallback behavior, and incident pathways.

It is important to note that timeline expectations can vary depending on integration risk.
Let me know if you want a deeper implementation checklist.
"""
    likelihood, markers = score_ai_authorship(ai_text, baseline_style=None)
    print(f"AI sample likelihood={likelihood} markers={markers}")

    assert likelihood >= 0.55
    assert markers["here_is_preamble"] is True
    assert markers["nested_bullets_detected"] is True
    assert markers["let_me_know_closing"] is True


def test_human_flavored_text_scores_lower() -> None:
    human_text = (
        "Pushed a quick fix after lunch. I broke the parser yesterday and this backs it out. "
        "Sorry about the churn; I'll clean up the tests tomorrow."
    )
    likelihood, markers = score_ai_authorship(human_text, baseline_style=None)
    print(f"Human sample likelihood={likelihood} markers={markers}")

    assert likelihood <= 0.35
    assert markers["here_is_preamble"] is False
    assert markers["nested_bullets_detected"] is False
    assert markers["let_me_know_closing"] is False


def test_baseline_style_can_discount_em_dash_signal() -> None:
    text = "We should split this into two commits — one for schema and one for API wiring."
    without_baseline, _ = score_ai_authorship(text, baseline_style=None)
    with_baseline, _ = score_ai_authorship(text, baseline_style={"em_dash_density": 0.50})

    assert with_baseline < without_baseline
