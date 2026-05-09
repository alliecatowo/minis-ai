"""Test that pipeline stages emit structured metrics."""

import logging

import pytest

from app.synthesis.pipeline import _log_stage_metric


@pytest.fixture
def caplog_with_level(caplog):
    """Fixture to capture logs at INFO level."""
    with caplog.at_level(logging.INFO):
        yield caplog


def test_log_stage_metric_basic(caplog_with_level):
    """Test basic stage metric logging."""
    _log_stage_metric(stage="fetch", duration_ms=1500.5, items=42)

    assert len(caplog_with_level.records) == 1
    record = caplog_with_level.records[0]
    assert "pipeline_stage_metric" in record.message
    assert "stage=fetch" in record.message
    assert "duration_ms=1500.5" in record.message
    assert "items=42" in record.message


def test_log_stage_metric_with_source(caplog_with_level):
    """Test stage metric logging with source."""
    _log_stage_metric(stage="explore", source="github", tokens_in=500, tokens_out=1200)

    assert len(caplog_with_level.records) == 1
    record = caplog_with_level.records[0]
    assert "pipeline_stage_metric" in record.message
    assert "stage=explore" in record.message
    assert "source=github" in record.message
    assert "tokens_in=500" in record.message
    assert "tokens_out=1200" in record.message


def test_log_stage_metric_with_all_fields(caplog_with_level):
    """Test stage metric logging with all fields."""
    _log_stage_metric(
        stage="synthesize",
        source="chief",
        duration_ms=3000.0,
        items=10,
        tokens_in=2000,
        tokens_out=5000,
        request_count=3,
    )

    assert len(caplog_with_level.records) == 1
    record = caplog_with_level.records[0]
    assert "pipeline_stage_metric" in record.message
    assert "stage=synthesize" in record.message
    assert "source=chief" in record.message
    assert "duration_ms=3000.0" in record.message
    assert "items=10" in record.message
    assert "tokens_in=2000" in record.message
    assert "tokens_out=5000" in record.message
    assert "request_count=3" in record.message


def test_log_stage_metric_omits_zero_fields(caplog_with_level):
    """Test that zero-valued fields are omitted from logs."""
    _log_stage_metric(stage="save", duration_ms=500.0)

    assert len(caplog_with_level.records) == 1
    record = caplog_with_level.records[0]
    assert "pipeline_stage_metric" in record.message
    assert "stage=save" in record.message
    assert "duration_ms=500.0" in record.message
    # Items, tokens, request_count should not be in the message
    assert "items=" not in record.message
    assert "tokens_in=" not in record.message
    assert "tokens_out=" not in record.message
    assert "request_count=" not in record.message


def test_log_stage_metric_minimal(caplog_with_level):
    """Test minimal stage metric with just stage name."""
    _log_stage_metric(stage="fetch")

    assert len(caplog_with_level.records) == 1
    record = caplog_with_level.records[0]
    assert "pipeline_stage_metric" in record.message
    assert "stage=fetch" in record.message
