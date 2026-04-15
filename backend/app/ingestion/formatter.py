"""Format raw GitHub data into structured evidence text for LLM analysis.

Evidence is organized by context type and weighted by personality signal strength.
Conflict evidence (pushback, disagreement, defense of positions) is prioritized
because it reveals authentic values more reliably than routine activity.
"""

from __future__ import annotations

import re

from app.ingestion.github import GitHubData

# Patterns that suggest strong emotion or conflict -- these comments are gold
_CONFLICT_PATTERNS = re.compile(
    r"(?i)"
    r"(?:i disagree|i don't think|i wouldn't|actually,?\s|but\s|however,?\s"
    r"|nit:|nit\b|instead,?\s|why not|shouldn't we|have you considered"
    r"|i'd prefer|i'd rather|the problem with|this breaks|this will cause"
    r"|strongly feel|concerned about|not a fan of|pushback|blocker"
    r"|LGTM.*but|approve.*but|let's not|please don't|we should avoid"
    r"|hard disagree|respectfully)"
)

_STRONG_EMOTION_PATTERNS = re.compile(
    r"(?:"
    r"[A-Z]{3,}|!!+|[!?]{2,}"  # CAPS, multiple exclamation/question marks
    r"|:\)|:\(|:D|<3|:3|;\)|xD|lol|lmao|haha"  # Emoticons and laughter
    r"|\b(?:love|hate|amazing|terrible|awesome|awful|perfect|horrible)\b"  # Strong sentiment
    r")"
)


def format_evidence(data: GitHubData) -> str:
    """Turn raw GitHub API data into a formatted evidence document.

    Evidence is organized into sections by type and annotated with signal
    strength markers to guide the LLM extraction.
    """
    sections: list[str] = []

    if data.profile:
        sections.append(_format_profile(data.profile))

    if data.repos:
        sections.append(_format_repos(data.repos))

    # Technical profile: language aggregation and topics
    if data.repos:
        sections.append(_format_language_profile(data.repos, data.repo_languages))

    # HIGH SIGNAL: Code review comments (conflict, values, communication style)
    if data.review_comments:
        conflict, routine = _partition_review_comments(data.review_comments)
        if conflict:
            sections.append(_format_review_comments(
                conflict,
                header="Code Review Comments -- CONFLICT & PUSHBACK",
                preamble=(
                    "[HIGHEST SIGNAL] These comments contain disagreement, pushback, or "
                    "strong opinions. They reveal the developer's true engineering values "
                    "and decision-making priorities. Pay close attention to their exact "
                    "wording, what they defend, and how they frame objections."
                ),
            ))
        if routine:
            sections.append(_format_review_comments(
                routine,
                header="Code Review Comments -- Routine",
                preamble=(
                    "Routine review comments showing everyday communication style, "
                    "tone, and what they notice during reviews."
                ),
            ))
    elif data.review_comments:
        sections.append(_format_review_comments(
            data.review_comments,
            header="Code Review Comments",
            preamble=(
                "[HIGHEST SIGNAL] Review comments reveal engineering values, "
                "communication style, and personality -- especially when there "
                "is disagreement or pushback."
            ),
        ))

    # HIGH SIGNAL: Full PR review threads with reviewer feedback and conversation
    if data.pr_review_threads:
        sections.append(_format_pr_review_threads(data.pr_review_threads))

    # MEDIUM-HIGH SIGNAL: Issue discussions
    if data.issue_comments:
        sections.append(_format_issue_comments(data.issue_comments))

    # MEDIUM-HIGH SIGNAL: Issue thread discussions (created / participated in)
    if data.issue_threads:
        sections.append(_format_issue_threads(data.issue_threads))

    # MEDIUM SIGNAL: PR descriptions
    if data.pull_requests:
        sections.append(_format_prs(data.pull_requests))

    # LOWER SIGNAL: Commit messages (useful for patterns, less for personality)
    if data.commits:
        sections.append(_format_commits(data.commits))

    # MEDIUM SIGNAL: Commit diffs for significant commits (code-level decisions)
    if data.commit_diffs:
        sections.append(_format_commit_diffs(data.commit_diffs))

    return "\n\n".join(sections)


def _partition_review_comments(
    comments: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split review comments into conflict/opinionated vs routine."""
    conflict = []
    routine = []
    for comment in comments:
        body = (comment.get("body") or "").strip()
        if not body:
            continue
        if _CONFLICT_PATTERNS.search(body):
            conflict.append(comment)
        else:
            routine.append(comment)
    return conflict, routine


def _format_profile(profile: dict) -> str:
    name = profile.get("name") or profile.get("login", "Unknown")
    bio = profile.get("bio") or "No bio"
    company = profile.get("company") or "Not specified"
    location = profile.get("location") or "Not specified"
    public_repos = profile.get("public_repos", 0)
    followers = profile.get("followers", 0)

    return f"""## Developer Profile
- **Name**: {name}
- **Bio**: {bio}
- **Company**: {company}
- **Location**: {location}
- **Public repos**: {public_repos}
- **Followers**: {followers}"""


def _format_repos(repos: list[dict]) -> str:
    lines = ["## Top Repositories"]
    for repo in repos[:15]:
        name = repo.get("full_name", repo.get("name", "unknown"))
        desc = repo.get("description") or "No description"
        lang = repo.get("language") or "Unknown"
        stars = repo.get("stargazers_count", 0)
        topics = repo.get("topics") or []
        topic_str = f" [{', '.join(topics)}]" if topics else ""
        lines.append(f"- **{name}** ({lang}, {stars} stars): {desc}{topic_str}")

    # Complete catalog of remaining repos
    remaining = repos[15:]
    if remaining:
        lines.append("")
        lines.append(f"## Complete Repository Catalog ({len(repos)} total)")
        for repo in remaining:
            name = repo.get("name", "unknown")
            lang = repo.get("language") or "?"
            stars = repo.get("stargazers_count", 0)
            desc = repo.get("description") or ""
            desc_str = f": {desc[:80]}" if desc else ""
            lines.append(f"- {name} ({lang}, {stars}★){desc_str}")

    return "\n".join(lines)


def _format_language_profile(
    repos: list[dict], repo_languages: dict[str, dict[str, int]]
) -> str:
    """Build a technical profile from language usage and repository topics."""
    lines = ["## Technical Profile"]

    # Aggregate languages by repo count and track which repos use each language
    lang_repos: dict[str, list[str]] = {}
    lang_primary_count: dict[str, int] = {}

    for repo in repos:
        repo_name = repo.get("full_name") or repo.get("name", "")
        short_name = repo.get("name") or repo_name
        primary_lang = repo.get("language")
        if primary_lang:
            lang_primary_count[primary_lang] = lang_primary_count.get(primary_lang, 0) + 1

        # Use per-repo language data if available, else fall back to primary language
        if repo_name in repo_languages:
            for lang in repo_languages[repo_name]:
                lang_repos.setdefault(lang, []).append(short_name)
        elif primary_lang:
            lang_repos.setdefault(primary_lang, []).append(short_name)

    if lang_repos:
        lines.append("\n### Languages (by repository count)")
        sorted_langs = sorted(lang_repos.items(), key=lambda x: len(x[1]), reverse=True)
        for lang, repo_names in sorted_langs:
            count = len(repo_names)
            primary = lang_primary_count.get(lang, 0)
            # Show which repos use this language
            repo_list = ", ".join(repo_names[:8])
            if len(repo_names) > 8:
                repo_list += f", +{len(repo_names) - 8} more"
            suffix = f" (primary in {primary})" if primary > 0 else ""
            lines.append(f"- {lang}: {count} repos{suffix} — {repo_list}")

    # Aggregate topics across all repos
    all_topics: dict[str, int] = {}
    for repo in repos:
        for topic in repo.get("topics") or []:
            all_topics[topic] = all_topics.get(topic, 0) + 1

    if all_topics:
        lines.append("\n### Technology Stack (from repository topics)")
        sorted_topics = sorted(all_topics.items(), key=lambda x: x[1], reverse=True)
        topic_strs = [f"{topic} ({count})" for topic, count in sorted_topics[:20]]
        lines.append(", ".join(topic_strs))

    return "\n".join(lines)


def _format_commits(commits: list[dict]) -> str:
    lines = ["## Commit Messages"]
    lines.append(
        "(Commit messages reveal work patterns and how the developer "
        "describes changes -- look for naming conventions, detail level, "
        "and whether they write explanatory commits vs terse ones)\n"
    )
    for commit in commits[:50]:
        commit_data = commit.get("commit", {})
        message = commit_data.get("message", "")
        # Include full message (first line + body) for richer signal
        msg_lines = message.split("\n")
        first_line = msg_lines[0] if msg_lines else ""
        body = "\n".join(msg_lines[1:]).strip() if len(msg_lines) > 1 else ""
        repo_name = commit.get("repository", {}).get("full_name", "unknown")

        lines.append(f"- [{repo_name}] {first_line}")
        if body and len(body) < 300:
            lines.append(f"  {body}")
    return "\n".join(lines)


def _format_prs(prs: list[dict]) -> str:
    lines = ["## Pull Request Descriptions"]
    lines.append(
        "(PR descriptions show how the developer explains and motivates "
        "their work, how much context they provide, and their writing style "
        "when presenting changes to others)\n"
    )
    for pr in prs[:30]:
        title = pr.get("title", "Untitled")
        body = (pr.get("body") or "").strip()
        repo_url = pr.get("repository_url", "")
        repo_name = repo_url.rsplit("/", 2)[-2:] if "/" in repo_url else ["unknown"]
        repo_label = "/".join(repo_name) if len(repo_name) == 2 else repo_url

        lines.append(f"### [{repo_label}] {title}")
        if body:
            if len(body) > 1500:
                body = body[:1500] + "..."
            lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _format_review_comments(
    comments: list[dict],
    header: str,
    preamble: str,
) -> str:
    lines = [f"## {header}"]
    lines.append(f"({preamble})\n")

    for comment in comments[:80]:
        body = (comment.get("body") or "").strip()
        if not body:
            continue
        diff_hunk = comment.get("diff_hunk", "")
        path = comment.get("path", "")

        # Annotate emotional intensity
        emotion_markers = _STRONG_EMOTION_PATTERNS.findall(body)
        emotion_tag = ""
        if emotion_markers:
            emotion_tag = f" [STRONG EMOTION: {', '.join(emotion_markers[:3])}]"

        if path:
            lines.append(f"**File: {path}**{emotion_tag}")
        elif emotion_tag:
            lines.append(f"**Comment**{emotion_tag}")

        if diff_hunk:
            diff_lines = diff_hunk.strip().split("\n")
            context = "\n".join(diff_lines[-5:]) if len(diff_lines) > 5 else diff_hunk
            lines.append(f"```diff\n{context}\n```")

        # Preserve exact quote formatting for few-shot extraction
        lines.append(f'> "{body}"')
        lines.append("")
    return "\n".join(lines)


def _format_issue_comments(comments: list[dict]) -> str:
    lines = ["## Issue Discussion Comments"]
    lines.append(
        "(Issue comments show how the developer communicates about "
        "problems and solutions, how they ask questions, and how they "
        "interact with collaborators in open discussion)\n"
    )
    for comment in comments[:50]:
        body = (comment.get("body") or "").strip()
        if not body:
            continue
        issue_url = comment.get("html_url", "")

        # Flag conflict/emotion
        has_conflict = bool(_CONFLICT_PATTERNS.search(body))
        has_emotion = bool(_STRONG_EMOTION_PATTERNS.search(body))
        tags = []
        if has_conflict:
            tags.append("CONFLICT/OPINION")
        if has_emotion:
            tags.append("STRONG EMOTION")
        tag_str = f" [{', '.join(tags)}]" if tags else ""

        if len(body) > 500:
            body = body[:500] + "..."

        lines.append(f'- {tag_str}"{body}"')
        if issue_url:
            lines.append(f"  *Source: {issue_url}*")
        lines.append("")
    return "\n".join(lines)


def _format_pr_review_threads(threads: list[dict]) -> str:
    """Format full PR review threads including reviewer comments and conversation.

    These threads show both the review feedback received on the developer's PRs
    (how others respond to their work) and the developer's responses (how they
    defend or accept criticism), which is a strong personality signal.
    """
    lines = ["## Pull Request Review Threads"]
    lines.append(
        "[HIGH SIGNAL] Full review conversations on this developer's PRs. "
        "The developer's responses to feedback reveal how they defend decisions, "
        "accept criticism, and collaborate under review pressure. "
        "Reviewer feedback also shows what aspects of their code draw scrutiny.\n"
    )

    for thread in threads[:15]:
        pr_title = thread.get("pr_title", "Untitled PR")
        pr_url = thread.get("pr_url", "")
        pr_body_snippet = thread.get("pr_body_snippet", "")
        review_comments = thread.get("review_comments", [])
        conversation_comments = thread.get("conversation_comments", [])

        if not review_comments and not conversation_comments:
            continue

        lines.append(f"### PR: {pr_title}")
        if pr_url:
            lines.append(f"*{pr_url}*")
        if pr_body_snippet:
            lines.append(f"**PR description:** {pr_body_snippet[:300]}")
        lines.append("")

        if review_comments:
            lines.append("**Inline review comments:**")
            for c in review_comments[:15]:
                author = c.get("author", "unknown")
                body = (c.get("body") or "").strip()
                path = c.get("path", "")
                diff_hunk = c.get("diff_hunk", "")

                if not body:
                    continue

                has_conflict = bool(_CONFLICT_PATTERNS.search(body))
                has_emotion = bool(_STRONG_EMOTION_PATTERNS.search(body))
                signal_tag = ""
                if has_conflict:
                    signal_tag = " [CONFLICT/OPINION]"
                elif has_emotion:
                    signal_tag = " [STRONG EMOTION]"

                if path:
                    lines.append(f"- **{author}** on `{path}`{signal_tag}:")
                else:
                    lines.append(f"- **{author}**{signal_tag}:")

                if diff_hunk:
                    diff_lines = diff_hunk.strip().split("\n")
                    context = "\n".join(diff_lines[-4:]) if len(diff_lines) > 4 else diff_hunk
                    lines.append(f"  ```diff\n  {context}\n  ```")

                if len(body) > 600:
                    body = body[:600] + "..."
                lines.append(f'  > "{body}"')
            lines.append("")

        if conversation_comments:
            lines.append("**PR conversation:**")
            for c in conversation_comments[:10]:
                author = c.get("author", "unknown")
                body = (c.get("body") or "").strip()
                if not body:
                    continue
                if len(body) > 400:
                    body = body[:400] + "..."
                has_conflict = bool(_CONFLICT_PATTERNS.search(body))
                signal_tag = " [CONFLICT/OPINION]" if has_conflict else ""
                lines.append(f"- **{author}**{signal_tag}: {body}")
            lines.append("")

    return "\n".join(lines)


def _format_issue_threads(threads: list[dict]) -> str:
    """Format issue discussion threads the developer created or participated in.

    Issue threads show how the developer frames problems (in issues they create)
    and how they engage in technical discussion (in issues they comment on).
    """
    lines = ["## Issue Discussion Threads"]
    lines.append(
        "[MEDIUM-HIGH SIGNAL] Full issue threads where this developer either "
        "reported a problem (showing their problem framing and technical writing) "
        "or participated in discussion (showing collaboration style and opinions).\n"
    )

    for thread in threads[:20]:
        title = thread.get("title", "Untitled Issue")
        url = thread.get("url", "")
        body = (thread.get("body") or "").strip()
        state = thread.get("state", "")
        author = thread.get("author", "unknown")
        comments = thread.get("comments", [])

        lines.append(f"### Issue: {title} [{state}]")
        if url:
            lines.append(f"*{url}*")
        if body:
            if len(body) > 600:
                body = body[:600] + "..."
            lines.append(f"**Opened by {author}:** {body}")

        if comments:
            lines.append("")
            lines.append("**Discussion:**")
            for c in comments[:10]:
                c_author = c.get("author", "unknown")
                c_body = (c.get("body") or "").strip()
                if not c_body:
                    continue
                has_conflict = bool(_CONFLICT_PATTERNS.search(c_body))
                has_emotion = bool(_STRONG_EMOTION_PATTERNS.search(c_body))
                tags = []
                if has_conflict:
                    tags.append("CONFLICT/OPINION")
                if has_emotion:
                    tags.append("STRONG EMOTION")
                tag_str = f" [{', '.join(tags)}]" if tags else ""
                lines.append(f"- **{c_author}**{tag_str}: {c_body}")

        lines.append("")

    return "\n".join(lines)


def _format_commit_diffs(commit_diffs: list[dict]) -> str:
    """Format commit diffs for the most impactful commits.

    Diffs show actual code decisions — what the developer adds, removes, and
    how they structure changes. This reveals technical preferences, refactoring
    patterns, and the granularity of their atomic commits.
    """
    lines = ["## Significant Commit Diffs"]
    lines.append(
        "[MEDIUM SIGNAL] Actual code diffs for the most impactful commits "
        "(ranked by total lines changed). Shows technical style, what kinds of "
        "changes they make, and how they structure code modifications.\n"
    )

    for diff in commit_diffs[:20]:
        sha = diff.get("sha", "")[:8]
        repo = diff.get("repo", "unknown")
        message = diff.get("message", "").split("\n")[0]  # first line only
        additions = diff.get("additions", 0)
        deletions = diff.get("deletions", 0)
        files = diff.get("files", [])

        lines.append(f"### [{repo}] {message}")
        lines.append(f"*SHA: {sha} | +{additions} -{deletions} lines*")

        for f in files[:5]:
            filename = f.get("filename", "")
            status = f.get("status", "")
            fa = f.get("additions", 0)
            fd = f.get("deletions", 0)
            patch = (f.get("patch") or "").strip()

            lines.append(f"\n**{filename}** ({status}, +{fa} -{fd})")
            if patch:
                lines.append(f"```diff\n{patch}\n```")

        lines.append("")

    return "\n".join(lines)
