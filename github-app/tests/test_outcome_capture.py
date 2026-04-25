"""Unit tests for github-app/app/outcome_capture.py.

Covers disposition classification for each signal shape:
- Positive reactions → confirmed
- Negative reactions → overpredicted
- Unknown reactions → None / deferred
- Agreeing reply bodies → confirmed
- Disagreeing reply bodies → overpredicted
- Neutral / no-signal bodies → None / deferred
- build_disposition_map priority ordering
"""

from __future__ import annotations

from app.outcome_capture import (
    extract_issue_keys_from_text,
    build_disposition_map,
    classify_reaction,
    classify_reply_body,
    map_signal_issue_key,
    map_pr_review_disposition,
)


# ---------------------------------------------------------------------------
# classify_reaction
# ---------------------------------------------------------------------------


class TestClassifyReaction:
    def test_thumbs_up_confirmed(self):
        assert classify_reaction("+1") == "confirmed"

    def test_heart_confirmed(self):
        assert classify_reaction("heart") == "confirmed"

    def test_hooray_confirmed(self):
        assert classify_reaction("hooray") == "confirmed"

    def test_laugh_confirmed(self):
        assert classify_reaction("laugh") == "confirmed"

    def test_rocket_confirmed(self):
        assert classify_reaction("rocket") == "confirmed"

    def test_thumbs_down_overpredicted(self):
        assert classify_reaction("-1") == "overpredicted"

    def test_confused_overpredicted(self):
        assert classify_reaction("confused") == "overpredicted"

    def test_eyes_no_signal(self):
        assert classify_reaction("eyes") is None

    def test_empty_no_signal(self):
        assert classify_reaction("") is None

    def test_unknown_no_signal(self):
        assert classify_reaction("tada") is None

    def test_case_insensitive(self):
        # GitHub sends lowercase but be defensive
        assert classify_reaction("+1") == "confirmed"


# ---------------------------------------------------------------------------
# classify_reply_body
# ---------------------------------------------------------------------------


class TestClassifyReplyBody:
    def test_disagree_phrase_overpredicted(self):
        assert classify_reply_body("I disagree with this.") == "overpredicted"

    def test_no_thanks_overpredicted(self):
        assert classify_reply_body("No thanks, this is fine.") == "overpredicted"

    def test_not_necessary_overpredicted(self):
        assert classify_reply_body("Not necessary here.") == "overpredicted"

    def test_not_needed_overpredicted(self):
        assert classify_reply_body("Actually not needed in this case.") == "overpredicted"

    def test_nah_overpredicted(self):
        assert classify_reply_body("Nah, this is intentional.") == "overpredicted"

    def test_fixed_confirmed(self):
        assert classify_reply_body("Fixed in latest commit.") == "confirmed"

    def test_done_confirmed(self):
        assert classify_reply_body("Done!") == "confirmed"

    def test_agreed_confirmed(self):
        assert classify_reply_body("Agreed, updating now.") == "confirmed"

    def test_will_do_confirmed(self):
        assert classify_reply_body("Will do, thanks.") == "confirmed"

    def test_lgtm_confirmed(self):
        assert classify_reply_body("lgtm") == "confirmed"

    def test_good_catch_confirmed(self):
        assert classify_reply_body("Good catch!") == "confirmed"

    def test_quote_only_confirmed(self):
        body = "> The original suggestion here\n\nSounds reasonable."
        assert classify_reply_body(body) == "confirmed"

    def test_empty_no_signal(self):
        assert classify_reply_body("") is None

    def test_neutral_no_signal(self):
        assert classify_reply_body("Interesting observation.") is None

    def test_disagree_takes_priority_over_quote(self):
        # Disagreement phrase dominates even when a quote is present
        body = "> some original content\n\nI disagree with this approach."
        assert classify_reply_body(body) == "overpredicted"


# ---------------------------------------------------------------------------
# map_pr_review_disposition
# ---------------------------------------------------------------------------


class TestMapPRReviewDisposition:
    def test_approved_is_deferred(self):
        assert map_pr_review_disposition("APPROVED") == "deferred"

    def test_changes_requested_is_deferred(self):
        assert map_pr_review_disposition("CHANGES_REQUESTED") == "deferred"

    def test_none_is_deferred(self):
        assert map_pr_review_disposition(None) == "deferred"

    def test_unknown_is_deferred(self):
        assert map_pr_review_disposition("COMMENTED") == "deferred"


# ---------------------------------------------------------------------------
# build_disposition_map
# ---------------------------------------------------------------------------


class TestBuildDispositionMap:
    def test_positive_reaction_wins(self):
        result = build_disposition_map(
            comment_reactions=["+1"],
            reply_bodies=["I disagree with this"],
            pr_review_state="CHANGES_REQUESTED",
        )
        assert result == "confirmed"

    def test_negative_reaction_wins(self):
        result = build_disposition_map(
            comment_reactions=["-1"],
            reply_bodies=["Agreed, will fix"],
        )
        assert result == "overpredicted"

    def test_first_non_none_reaction_wins(self):
        # "eyes" has no signal, "+1" comes second — should still be confirmed
        result = build_disposition_map(comment_reactions=["eyes", "+1"])
        assert result == "confirmed"

    def test_reply_body_used_when_no_reaction_signal(self):
        result = build_disposition_map(
            comment_reactions=["eyes"],
            reply_bodies=["Fixed!"],
        )
        assert result == "confirmed"

    def test_pr_review_state_fallback_is_deferred(self):
        result = build_disposition_map(pr_review_state="APPROVED")
        assert result == "deferred"

    def test_no_signals_is_deferred(self):
        result = build_disposition_map()
        assert result == "deferred"

    def test_empty_lists_is_deferred(self):
        result = build_disposition_map(comment_reactions=[], reply_bodies=[])
        assert result == "deferred"

    def test_multiple_replies_first_signal_wins(self):
        result = build_disposition_map(
            reply_bodies=["Agreed!", "I disagree though"],
        )
        assert result == "confirmed"

    def test_overpredicted_reply_captured(self):
        result = build_disposition_map(reply_bodies=["No thanks, this is intentional."])
        assert result == "overpredicted"


class TestIssueKeyExtraction:
    def test_extracts_multiple_issue_keys_in_order(self):
        body = (
            "### Review by @allie's mini\n\n"
            "**Blocker** `sec-1`: Validate input boundaries.\n"
            "**Note** `style-2`: Rename variable."
        )
        assert extract_issue_keys_from_text(body) == ["sec-1", "style-2"]

    def test_signal_matches_nested_comment_key(self):
        parent = (
            "**Blocker** `sec-1`: Validate input boundaries.\n"
            "**Note** `style-2`: Rename variable."
        )
        signal = "> **Note** `style-2`: Rename variable.\n\nFixed."
        assert map_signal_issue_key(parent_comment_body=parent, signal_body=signal) == "style-2"

    def test_signal_falls_back_to_only_key(self):
        parent = "**Question** `auth-1`: Should this use a constant?"
        assert map_signal_issue_key(parent_comment_body=parent, signal_body="Yep, good call.") == "auth-1"

    def test_signal_ambiguous_without_disambiguation(self):
        parent = (
            "**Blocker** `sec-1`: Validate input boundaries.\n"
            "**Note** `style-2`: Rename variable."
        )
        assert map_signal_issue_key(parent_comment_body=parent, signal_body="Good point.") is None
