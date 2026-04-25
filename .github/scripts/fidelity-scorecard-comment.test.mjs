import assert from 'node:assert/strict';
import test from 'node:test';

import { buildFidelityScorecardComment } from './fidelity-scorecard-comment.mjs';

test('renders a durable skipped scorecard comment for PR runs', () => {
  const body = buildFidelityScorecardComment({
    skippedReason: 'Live fidelity evals do not run on pull_request by default.',
    runUrl: 'https://github.com/alliecatowo/minis-ai/actions/runs/123',
  });

  assert.match(body, /## Fidelity Eval Scorecard/);
  assert.match(body, /<!-- minis:fidelity-eval-scorecard -->/);
  assert.match(body, /\*\*Status:\*\* skipped/);
  assert.match(body, /do not run on pull_request/);
  assert.match(body, /actions\/runs\/123/);
});

test('renders report content and truncates long reports', () => {
  const body = buildFidelityScorecardComment({
    reportText: `# Report\n\n${'x'.repeat(50)}`,
    maxReportChars: 20,
  });

  assert.match(body, /\*\*Status:\*\* completed/);
  assert.match(body, /# Report/);
  assert.match(body, /truncated; see workflow artifact/);
});

test('renders explicit failure when eval exits before report generation', () => {
  const body = buildFidelityScorecardComment({
    failureReason: 'Missing required secrets: GEMINI_API_KEY.',
  });

  assert.match(body, /\*\*Status:\*\* failed before a complete scorecard was generated/);
  assert.match(body, /Missing required secrets/);
});

test('keeps generated report visible when eval exits non-zero', () => {
  const body = buildFidelityScorecardComment({
    reportText: '# Report\n\nRegression detected.',
    failureReason: 'Fidelity eval exited non-zero.',
  });

  assert.match(body, /\*\*Status:\*\* completed with non-zero exit/);
  assert.match(body, /Fidelity eval exited non-zero/);
  assert.match(body, /Regression detected/);
});
