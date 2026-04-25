import fs from 'node:fs';

const DEFAULT_MARKER = '<!-- minis:fidelity-eval-scorecard -->';
const DEFAULT_TITLE = '## Fidelity Eval Scorecard';
const DEFAULT_LIMIT = 6000;

function buildRunUrl(env) {
  if (!env.GITHUB_SERVER_URL || !env.GITHUB_REPOSITORY || !env.GITHUB_RUN_ID) {
    return null;
  }
  return `${env.GITHUB_SERVER_URL}/${env.GITHUB_REPOSITORY}/actions/runs/${env.GITHUB_RUN_ID}`;
}

function truncateReport(report, limit) {
  if (report.length <= limit) {
    return report;
  }
  return `${report.slice(0, limit)}\n\n...(truncated; see workflow artifact for full report)`;
}

export function buildFidelityScorecardComment({
  reportPath,
  reportText,
  skippedReason,
  failureReason,
  runUrl,
  maxReportChars = DEFAULT_LIMIT,
  marker = DEFAULT_MARKER,
} = {}) {
  const lines = [DEFAULT_TITLE, marker, ''];

  let body = reportText;
  if (body === undefined && reportPath && fs.existsSync(reportPath)) {
    body = fs.readFileSync(reportPath, 'utf8');
  }

  if (skippedReason) {
    lines.push('**Status:** skipped');
    lines.push('');
    lines.push(skippedReason);
  } else if (body && body.trim()) {
    lines.push(failureReason ? '**Status:** completed with non-zero exit' : '**Status:** completed');
    if (failureReason) {
      lines.push('');
      lines.push(`> ${failureReason}`);
    }
    lines.push('');
    lines.push(truncateReport(body, maxReportChars));
  } else if (failureReason) {
    lines.push('**Status:** failed before a complete scorecard was generated');
    lines.push('');
    lines.push(failureReason);
  } else {
    lines.push('**Status:** unavailable');
    lines.push('');
    lines.push('Eval report was not generated. Check workflow logs and artifacts for the failing step.');
  }

  lines.push('');
  lines.push('---');
  if (runUrl) {
    lines.push(`_Non-blocking. [Workflow run](${runUrl}) · [How to run locally & read this scorecard](docs/FIDELITY_EVAL.md)_`);
  } else {
    lines.push('_Non-blocking. [How to run locally & read this scorecard](docs/FIDELITY_EVAL.md)_');
  }

  return `${lines.join('\n')}\n`;
}

export function writeFidelityScorecardComment(env = process.env) {
  const body = buildFidelityScorecardComment({
    reportPath: env.FIDELITY_REPORT_PATH || 'backend/eval-report.md',
    skippedReason: env.FIDELITY_SKIPPED_REASON || '',
    failureReason: env.FIDELITY_FAILURE_REASON || '',
    runUrl: buildRunUrl(env),
    maxReportChars: Number.parseInt(env.FIDELITY_COMMENT_MAX_CHARS || `${DEFAULT_LIMIT}`, 10),
  });

  const outputPath = env.FIDELITY_COMMENT_PATH || 'fidelity-scorecard-comment.md';
  fs.writeFileSync(outputPath, body);
  return body;
}

if (import.meta.url === `file://${process.argv[1]}`) {
  writeFidelityScorecardComment();
}
