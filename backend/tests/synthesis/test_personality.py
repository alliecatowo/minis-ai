"""Tests for the PersonalityTypologist inference agent (ALLIE-430).

Covers:
- infer_personality_typology() returns the expected PersonalityTypology shape
- Evidence IDs are populated per dimension
- Cross-validation detects MBTI/Big Five contradiction correctly
- Empty evidence returns a graceful empty typology
- build_personality_block() renders the compact system-prompt section
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import PersonalityTypology, PersonalityTypologyFramework, TypologyDimension
from app.synthesis.personality import (
    _MBTIDimension,
    _BigFiveTrait,
    _DISCProfile,
    _TypologyInferenceResult,
    _run_cross_validation,
    infer_personality_typology,
)
from app.synthesis.spirit import build_personality_block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uuid() -> str:
    return str(uuid.uuid4())


def _make_finding(
    mini_id: str,
    category: str = "personality",
    content: str = "Direct, blunt code review style",
    confidence: float = 0.85,
    source_type: str = "github",
) -> MagicMock:
    obj = MagicMock()
    obj.id = _make_uuid()
    obj.mini_id = mini_id
    obj.category = category
    obj.content = content
    obj.confidence = confidence
    obj.source_type = source_type
    return obj


def _make_quote(
    mini_id: str,
    quote: str = "nit: fix this before merge",
    context: str = "code review",
    significance: str = "high",
    source_type: str = "github",
) -> MagicMock:
    obj = MagicMock()
    obj.id = _make_uuid()
    obj.mini_id = mini_id
    obj.quote = quote
    obj.context = context
    obj.significance = significance
    obj.source_type = source_type
    return obj


def _make_evidence(
    mini_id: str,
    item_type: str = "pr_review",
    content: str = "Rejected PR: missing unit tests. Will not merge.",
    source_type: str = "github",
) -> MagicMock:
    obj = MagicMock()
    obj.id = _make_uuid()
    obj.mini_id = mini_id
    obj.item_type = item_type
    obj.content = content
    obj.source_type = source_type
    return obj


def _make_canned_typology_output(
    finding_id: str,
    quote_id: str,
) -> _TypologyInferenceResult:
    """Build a canned _TypologyInferenceResult for an INTJ-ish profile."""
    return _TypologyInferenceResult(
        mbti_type="INTJ",
        mbti_confidence=0.82,
        mbti_dimensions=[
            _MBTIDimension(
                dimension="E_I",
                score=0.2,  # strongly I
                preference="I",
                evidence_ids=[finding_id, quote_id],
                reasoning="Prefers async written communication, minimal collaboration signals",
            ),
            _MBTIDimension(
                dimension="S_N",
                score=0.8,  # strongly N
                preference="N",
                evidence_ids=[finding_id],
                reasoning="Abstract architecture discussions dominate review comments",
            ),
            _MBTIDimension(
                dimension="T_F",
                score=0.85,  # strongly T
                preference="T",
                evidence_ids=[finding_id, quote_id],
                reasoning="Logic-first feedback, minimal empathy markers in reviews",
            ),
            _MBTIDimension(
                dimension="J_P",
                score=0.78,  # strongly J
                preference="J",
                evidence_ids=[finding_id],
                reasoning="Consistent commit discipline, thorough documentation practices",
            ),
        ],
        big_five=[
            _BigFiveTrait(
                trait="openness",
                score=0.80,
                evidence_ids=[finding_id],
                reasoning="Experiments with new frameworks, broad repo variety",
            ),
            _BigFiveTrait(
                trait="conscientiousness",
                score=0.88,
                evidence_ids=[finding_id, quote_id],
                reasoning="High test coverage demands, thorough documentation",
            ),
            _BigFiveTrait(
                trait="extraversion",
                score=0.22,  # low E → consistent with MBTI I
                evidence_ids=[quote_id],
                reasoning="Low communication volume, prefers solo deep work",
            ),
            _BigFiveTrait(
                trait="agreeableness",
                score=0.30,  # low A → consistent with MBTI T
                evidence_ids=[finding_id],
                reasoning="Direct, critical feedback without diplomatic softening",
            ),
            _BigFiveTrait(
                trait="neuroticism",
                score=0.25,
                evidence_ids=[finding_id],
                reasoning="Calm responses to production bugs, measured risk tolerance",
            ),
        ],
        big_five_confidence=0.78,
        disc=_DISCProfile(
            primary="C",
            secondary="D",
            evidence_ids=[finding_id],
            reasoning="Systematic, detail-oriented reviews with direct delivery",
        ),
        enneagram=None,
        cross_validation=[],  # populated by _run_cross_validation
        overall_confidence=0.80,
        summary=(
            "A precise, systematic engineer who prioritizes quality and correctness over speed. "
            "Communicates directly and expects rigor from collaborators."
        ),
    )


def _make_contradictory_typology_output(
    finding_id: str,
    quote_id: str,
) -> _TypologyInferenceResult:
    """Build a _TypologyInferenceResult with MBTI E but Big Five low E (contradiction)."""
    return _TypologyInferenceResult(
        mbti_type="ENTJ",
        mbti_confidence=0.70,
        mbti_dimensions=[
            _MBTIDimension(
                dimension="E_I",
                score=0.75,  # E
                preference="E",
                evidence_ids=[finding_id],
                reasoning="Leads discussions, high comment volume",
            ),
            _MBTIDimension(
                dimension="S_N",
                score=0.72,
                preference="N",
                evidence_ids=[finding_id],
                reasoning="Abstract thinking",
            ),
            _MBTIDimension(
                dimension="T_F",
                score=0.80,
                preference="T",
                evidence_ids=[finding_id],
                reasoning="Logic-first",
            ),
            _MBTIDimension(
                dimension="J_P",
                score=0.75,
                preference="J",
                evidence_ids=[finding_id],
                reasoning="Structured approach",
            ),
        ],
        big_five=[
            _BigFiveTrait(
                trait="openness",
                score=0.70,
                evidence_ids=[finding_id],
                reasoning="Tech curiosity",
            ),
            _BigFiveTrait(
                trait="conscientiousness",
                score=0.80,
                evidence_ids=[finding_id],
                reasoning="Systematic",
            ),
            _BigFiveTrait(
                trait="extraversion",
                score=0.20,  # LOW E despite MBTI E — contradiction!
                evidence_ids=[quote_id],
                reasoning="Actually low engagement",
            ),
            _BigFiveTrait(
                trait="agreeableness",
                score=0.35,
                evidence_ids=[finding_id],
                reasoning="Direct feedback",
            ),
            _BigFiveTrait(
                trait="neuroticism",
                score=0.30,
                evidence_ids=[finding_id],
                reasoning="Calm",
            ),
        ],
        big_five_confidence=0.65,
        disc=_DISCProfile(
            primary="D",
            secondary="C",
            evidence_ids=[finding_id],
            reasoning="Results-driven",
        ),
        enneagram=None,
        cross_validation=[],
        overall_confidence=0.68,
        summary="Leader with high standards.",
    )


def _make_mock_session(
    findings: list[Any],
    quotes: list[Any],
    evidence: list[Any],
) -> MagicMock:
    """Return a mock async SQLAlchemy session that returns the given rows."""
    session = MagicMock()

    # scalars().all() chains
    findings_scalars = MagicMock()
    findings_scalars.all.return_value = findings

    quotes_scalars = MagicMock()
    quotes_scalars.all.return_value = quotes

    evidence_scalars = MagicMock()
    evidence_scalars.all.return_value = evidence

    findings_result = MagicMock()
    findings_result.scalars.return_value = findings_scalars

    quotes_result = MagicMock()
    quotes_result.scalars.return_value = quotes_scalars

    evidence_result = MagicMock()
    evidence_result.scalars.return_value = evidence_scalars

    # execute() is called three times in order: findings, quotes, evidence
    session.execute = AsyncMock(side_effect=[findings_result, quotes_result, evidence_result])
    return session


# ---------------------------------------------------------------------------
# Tests: infer_personality_typology — contract shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_infer_personality_typology_returns_correct_shape() -> None:
    """infer_personality_typology returns a PersonalityTypology with expected frameworks."""
    mini_id = _make_uuid()
    finding = _make_finding(mini_id)
    quote = _make_quote(mini_id)
    evidence = _make_evidence(mini_id)

    canned = _make_canned_typology_output(finding.id, quote.id)

    session = _make_mock_session([finding], [quote], [evidence])

    mock_agent_result = MagicMock()
    mock_agent_result.output = canned

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    with patch("app.synthesis.personality.Agent", return_value=mock_agent):
        result = await infer_personality_typology(mini_id, session, username="testdev")

    assert isinstance(result, PersonalityTypology)
    assert result.summary
    assert len(result.frameworks) >= 3  # MBTI + Big Five + DISC

    framework_names = {f.framework for f in result.frameworks}
    assert "MBTI" in framework_names
    assert "Big Five (OCEAN)" in framework_names
    assert "DISC" in framework_names


@pytest.mark.asyncio
async def test_infer_personality_typology_evidence_ids_populated() -> None:
    """Each MBTI dimension must carry at least one evidence_id."""
    mini_id = _make_uuid()
    finding = _make_finding(mini_id)
    quote = _make_quote(mini_id)
    evidence = _make_evidence(mini_id)

    canned = _make_canned_typology_output(finding.id, quote.id)
    session = _make_mock_session([finding], [quote], [evidence])

    mock_agent_result = MagicMock()
    mock_agent_result.output = canned
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_agent_result)

    with patch("app.synthesis.personality.Agent", return_value=mock_agent):
        result = await infer_personality_typology(mini_id, session, username="testdev")

    mbti = next(f for f in result.frameworks if f.framework == "MBTI")
    # The aggregate evidence list on the MBTI framework should be non-empty
    assert len(mbti.evidence) > 0, "MBTI framework must carry evidence IDs"


@pytest.mark.asyncio
async def test_infer_personality_typology_empty_evidence_returns_graceful() -> None:
    """When the DB has no evidence, return empty PersonalityTypology without crashing."""
    mini_id = _make_uuid()
    session = _make_mock_session([], [], [])

    result = await infer_personality_typology(mini_id, session, username="ghost")

    assert isinstance(result, PersonalityTypology)
    assert result.frameworks == []
    assert result.summary  # should have a descriptive message


# ---------------------------------------------------------------------------
# Tests: cross-validation
# ---------------------------------------------------------------------------


def test_cross_validation_consistent_intj() -> None:
    """INTJ profile (I + T + J) with low E, low A, high C should pass all checks."""
    finding_id = _make_uuid()
    quote_id = _make_uuid()
    output = _make_canned_typology_output(finding_id, quote_id)

    flags = _run_cross_validation(output)

    assert len(flags) == 3, "Expected exactly 3 cross-validation checks"
    inconsistent = [f for f in flags if not f.consistent]
    assert inconsistent == [], (
        f"INTJ + Big Five should be consistent but got: {[f.note for f in inconsistent]}"
    )


def test_cross_validation_detects_mbti_e_vs_big5_low_e() -> None:
    """MBTI E with Big Five low E should be flagged as inconsistent."""
    finding_id = _make_uuid()
    quote_id = _make_uuid()
    output = _make_contradictory_typology_output(finding_id, quote_id)

    flags = _run_cross_validation(output)

    # Check that MBTI I ↔ Big Five low Extraversion flag exists and is inconsistent
    ei_flags = [f for f in flags if "Extraversion" in f.check]
    assert len(ei_flags) == 1
    ei_flag = ei_flags[0]
    assert not ei_flag.consistent, "MBTI E with Big Five low E should be flagged"
    assert "contradicts" in ei_flag.note.lower() or ei_flag.note  # has a note


def test_cross_validation_returns_three_checks() -> None:
    """_run_cross_validation always returns exactly 3 checks when all dimensions present."""
    finding_id = _make_uuid()
    quote_id = _make_uuid()
    output = _make_canned_typology_output(finding_id, quote_id)
    flags = _run_cross_validation(output)
    assert len(flags) == 3


# ---------------------------------------------------------------------------
# Tests: build_personality_block (spirit integration)
# ---------------------------------------------------------------------------


def _sample_typology() -> PersonalityTypology:
    return PersonalityTypology(
        summary="A precise, systematic engineer with low extraversion.",
        frameworks=[
            PersonalityTypologyFramework(
                framework="MBTI",
                profile="INTJ",
                confidence=0.82,
                dimensions=[
                    TypologyDimension(name="E_I", value="I", confidence=0.80),
                    TypologyDimension(name="S_N", value="N", confidence=0.60),
                    TypologyDimension(name="T_F", value="T", confidence=0.70),
                    TypologyDimension(name="J_P", value="J", confidence=0.56),
                ],
                evidence=["abc-123"],
            ),
            PersonalityTypologyFramework(
                framework="Big Five (OCEAN)",
                profile="O=0.80 | C=0.88 | E=0.22 | A=0.30 | N=0.25",
                confidence=0.78,
                dimensions=[
                    TypologyDimension(name="Openness", value="0.80"),
                    TypologyDimension(name="Conscientiousness", value="0.88"),
                    TypologyDimension(name="Extraversion", value="0.22"),
                    TypologyDimension(name="Agreeableness", value="0.30"),
                    TypologyDimension(name="Neuroticism", value="0.25"),
                ],
            ),
            PersonalityTypologyFramework(
                framework="DISC",
                profile="C-primary, D-secondary",
                confidence=0.75,
                dimensions=[
                    TypologyDimension(name="primary", value="C"),
                    TypologyDimension(name="secondary", value="D"),
                ],
            ),
        ],
    )


def test_build_personality_block_includes_mbti() -> None:
    """build_personality_block renders MBTI type in the output."""
    typology = _sample_typology()
    block = build_personality_block(typology)
    assert "INTJ" in block


def test_build_personality_block_includes_disc() -> None:
    """build_personality_block renders DISC profile."""
    typology = _sample_typology()
    block = build_personality_block(typology)
    assert "DISC" in block
    assert "C-primary" in block


def test_build_personality_block_includes_big_five() -> None:
    """build_personality_block renders Big Five scores."""
    typology = _sample_typology()
    block = build_personality_block(typology)
    assert "Big Five" in block


def test_build_personality_block_empty_typology_returns_empty_string() -> None:
    """build_personality_block returns empty string for empty typology."""
    empty = PersonalityTypology(summary=None, frameworks=[])
    block = build_personality_block(empty)
    assert block == ""


def test_build_personality_block_none_returns_empty_string() -> None:
    """build_personality_block returns empty string for None input."""
    block = build_personality_block(None)  # type: ignore[arg-type]
    assert block == ""


def test_build_personality_block_includes_enneagram_when_present() -> None:
    """build_personality_block renders Enneagram when it's in the frameworks."""
    typology = _sample_typology()
    typology.frameworks.append(
        PersonalityTypologyFramework(
            framework="Enneagram",
            profile="5w4",
            confidence=0.72,
            dimensions=[
                TypologyDimension(name="type", value="5"),
                TypologyDimension(name="wing", value="4"),
            ],
        )
    )
    block = build_personality_block(typology)
    assert "5w4" in block
    assert "Enneagram" in block
