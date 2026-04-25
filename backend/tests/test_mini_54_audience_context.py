"""Tests for MINI-54: audience-aware review prediction.

Verifies:
- AudienceContext schema defaults to unknown/normal/no-size/not-draft.
- AuthorRelationship and ReviewContext are str enums with correct members.
- ArtifactReviewRequestBaseV1 accepts and round-trips the `audience` field.
- _build_audience_context_section injects relationship and context guidance.
- _build_predictor_system_prompt includes audience section when audience provided.
- Junior / peer / senior relationships produce distinct prompt guidance.
- Hotfix / incident contexts inject triage urgency language.
- Exploratory context injects directional coaching language.
- pr_size_lines thresholds (small / medium / large) produce distinct labels.
- Draft flag injects draft-specific guidance.
- Backward-compat: request without `audience` still validates.
"""
from __future__ import annotations

import pytest

from app.models.schemas import (
    AudienceContext,
    AuthorRelationship,
    ReviewContext,
    ArtifactReviewRequestBaseV1,
    ReviewPredictionRequestV1,
)
from app.core.review_predictor_agent import _build_audience_context_section


# ---------------------------------------------------------------------------
# Schema unit tests
# ---------------------------------------------------------------------------


class TestAudienceContextDefaults:
    def test_default_relationship_is_unknown(self):
        ctx = AudienceContext()
        assert ctx.author_relationship == AuthorRelationship.unknown

    def test_default_review_context_is_normal(self):
        ctx = AudienceContext()
        assert ctx.review_context == ReviewContext.normal

    def test_default_pr_size_is_none(self):
        ctx = AudienceContext()
        assert ctx.pr_size_lines is None

    def test_default_is_draft_is_false(self):
        ctx = AudienceContext()
        assert ctx.is_draft is False


class TestAuthorRelationshipEnum:
    def test_all_members_present(self):
        values = {m.value for m in AuthorRelationship}
        assert values == {"junior", "peer", "senior", "unknown"}

    def test_is_str_enum(self):
        assert isinstance(AuthorRelationship.junior, str)


class TestReviewContextEnum:
    def test_all_members_present(self):
        values = {m.value for m in ReviewContext}
        assert values == {"normal", "hotfix", "incident", "exploratory"}

    def test_is_str_enum(self):
        assert isinstance(ReviewContext.hotfix, str)


class TestAudienceContextValidation:
    def test_string_coercion_for_relationship(self):
        ctx = AudienceContext(author_relationship="junior")
        assert ctx.author_relationship == AuthorRelationship.junior

    def test_string_coercion_for_context(self):
        ctx = AudienceContext(review_context="hotfix")
        assert ctx.review_context == ReviewContext.hotfix

    def test_pr_size_must_be_non_negative(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AudienceContext(pr_size_lines=-1)

    def test_pr_size_zero_is_valid(self):
        ctx = AudienceContext(pr_size_lines=0)
        assert ctx.pr_size_lines == 0


# ---------------------------------------------------------------------------
# Request schema wiring
# ---------------------------------------------------------------------------


class TestArtifactReviewRequestBaseV1Wiring:
    def _make_request(self, **kwargs) -> ArtifactReviewRequestBaseV1:
        return ReviewPredictionRequestV1(title="Add foo", **kwargs)

    def test_audience_defaults_to_defaults(self):
        req = self._make_request()
        assert req.audience.author_relationship == AuthorRelationship.unknown
        assert req.audience.review_context == ReviewContext.normal

    def test_audience_round_trips(self):
        audience = AudienceContext(
            author_relationship=AuthorRelationship.junior,
            review_context=ReviewContext.hotfix,
            pr_size_lines=42,
            is_draft=True,
        )
        req = self._make_request(audience=audience)
        assert req.audience.author_relationship == AuthorRelationship.junior
        assert req.audience.review_context == ReviewContext.hotfix
        assert req.audience.pr_size_lines == 42
        assert req.audience.is_draft is True

    def test_audience_accepts_dict(self):
        req = self._make_request(
            audience={"author_relationship": "peer", "review_context": "exploratory"}
        )
        assert req.audience.author_relationship == AuthorRelationship.peer
        assert req.audience.review_context == ReviewContext.exploratory

    def test_backward_compat_omit_audience(self):
        # Should validate fine without specifying audience at all.
        req = self._make_request()
        assert req.audience is not None


# ---------------------------------------------------------------------------
# Prompt section tests
# ---------------------------------------------------------------------------


class TestBuildAudienceContextSection:
    def _ctx(self, **kwargs) -> AudienceContext:
        return AudienceContext(**kwargs)

    def test_section_header_always_present(self):
        section = _build_audience_context_section(self._ctx())
        assert "## Author Context" in section

    def test_junior_relationship_produces_coaching_language(self):
        section = _build_audience_context_section(
            self._ctx(author_relationship=AuthorRelationship.junior)
        )
        assert "junior" in section.lower()
        # Should mention coaching or explanation
        assert any(kw in section.lower() for kw in ("coaching", "explanation", "encouragement"))

    def test_peer_relationship_produces_direct_language(self):
        section = _build_audience_context_section(
            self._ctx(author_relationship=AuthorRelationship.peer)
        )
        assert "peer" in section.lower()
        assert "direct" in section.lower()

    def test_senior_relationship_produces_concise_language(self):
        section = _build_audience_context_section(
            self._ctx(author_relationship=AuthorRelationship.senior)
        )
        assert "senior" in section.lower()
        assert "concise" in section.lower()

    def test_unknown_relationship_is_neutral(self):
        section = _build_audience_context_section(
            self._ctx(author_relationship=AuthorRelationship.unknown)
        )
        assert "unknown" in section.lower()
        assert "balanced" in section.lower() or "neutral" in section.lower()

    def test_hotfix_context_produces_triage_language(self):
        section = _build_audience_context_section(
            self._ctx(review_context=ReviewContext.hotfix)
        )
        assert "hotfix" in section.lower() or "Hotfix" in section
        assert "triage" in section.lower()

    def test_incident_context_produces_triage_language(self):
        section = _build_audience_context_section(
            self._ctx(review_context=ReviewContext.incident)
        )
        assert "incident" in section.lower() or "Incident" in section
        assert "triage" in section.lower()

    def test_exploratory_context_produces_coaching_language(self):
        section = _build_audience_context_section(
            self._ctx(review_context=ReviewContext.exploratory)
        )
        assert "exploratory" in section.lower() or "Exploratory" in section
        assert any(kw in section.lower() for kw in ("coaching", "directional"))

    def test_normal_context_produces_standard_language(self):
        section = _build_audience_context_section(
            self._ctx(review_context=ReviewContext.normal)
        )
        assert "normal" in section.lower() or "standard" in section.lower()

    def test_small_pr_size_label(self):
        section = _build_audience_context_section(self._ctx(pr_size_lines=50))
        assert "small" in section.lower()

    def test_medium_pr_size_label(self):
        section = _build_audience_context_section(self._ctx(pr_size_lines=300))
        assert "medium" in section.lower()

    def test_large_pr_size_label(self):
        section = _build_audience_context_section(self._ctx(pr_size_lines=600))
        assert "large" in section.lower()

    def test_no_pr_size_omits_size_line(self):
        section = _build_audience_context_section(self._ctx(pr_size_lines=None))
        assert "lines changed" not in section

    def test_draft_flag_produces_draft_language(self):
        section = _build_audience_context_section(self._ctx(is_draft=True))
        assert "draft" in section.lower()

    def test_non_draft_omits_draft_language(self):
        section = _build_audience_context_section(self._ctx(is_draft=False))
        assert "draft" not in section.lower()

    def test_junior_hotfix_combined(self):
        section = _build_audience_context_section(
            self._ctx(
                author_relationship=AuthorRelationship.junior,
                review_context=ReviewContext.hotfix,
            )
        )
        # Both junior coaching and hotfix triage signals must appear.
        assert any(kw in section.lower() for kw in ("coaching", "explanation", "encouragement"))
        assert "triage" in section.lower()


# ---------------------------------------------------------------------------
# Integration: system prompt includes audience section
# ---------------------------------------------------------------------------


class TestSystemPromptIncludesAudience:
    """Smoke-test that _build_predictor_system_prompt includes the audience block.

    We use a lightweight stub for Mini to avoid DB dependencies.
    """

    def _make_mini_stub(self) -> object:
        class _MiniStub:
            system_prompt = "You are a developer."
            memory_content = None
            evidence_cache = None
            principles_json = None

        return _MiniStub()

    def _make_body(self, **kwargs) -> ReviewPredictionRequestV1:
        return ReviewPredictionRequestV1(title="Test PR", **kwargs)

    def test_audience_section_in_prompt_with_defaults(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = self._make_mini_stub()
        body = self._make_body()
        prompt = _build_predictor_system_prompt(mini, body, artifact_label="Pull Request")
        assert "## Author Context" in prompt

    def test_junior_hotfix_audience_in_system_prompt(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = self._make_mini_stub()
        body = self._make_body(
            audience=AudienceContext(
                author_relationship=AuthorRelationship.junior,
                review_context=ReviewContext.hotfix,
                pr_size_lines=150,
                is_draft=False,
            )
        )
        prompt = _build_predictor_system_prompt(mini, body, artifact_label="Pull Request")
        assert "junior" in prompt.lower()
        assert "triage" in prompt.lower()
        assert "150 lines" in prompt

    def test_senior_peer_in_system_prompt(self):
        from app.core.review_predictor_agent import _build_predictor_system_prompt

        mini = self._make_mini_stub()
        body = self._make_body(
            audience=AudienceContext(author_relationship=AuthorRelationship.senior)
        )
        prompt = _build_predictor_system_prompt(mini, body, artifact_label="Pull Request")
        assert "senior" in prompt.lower()
        assert "concise" in prompt.lower()
