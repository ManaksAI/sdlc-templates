#!/usr/bin/env python3
"""Analysis + triage stage of the autonomous SDLC pipeline.

Reads a requirement (a GitHub issue), analyzes it against the repository using
Claude, posts a structured analysis comment, and decides whether a human must
review before any automated implementation. Emits `proceed=true|false` to
$GITHUB_OUTPUT so the workflow can gate the implementation job.

Env in: ANTHROPIC_API_KEY, GH_TOKEN, REPO, MODEL, ISSUE_NUMBER, ISSUE_TITLE,
        ISSUE_BODY, ISSUE_LABELS (JSON array of names).
"""
import json
import os
import subprocess

import anthropic

REPO = os.environ["REPO"]
ISSUE = os.environ["ISSUE_NUMBER"]
MODEL = os.environ.get("MODEL", "claude-opus-4-8")
title = os.environ.get("ISSUE_TITLE", "")
body = os.environ.get("ISSUE_BODY", "") or "(no description provided)"
labels = json.loads(os.environ.get("ISSUE_LABELS", "[]"))

# Repo file list grounds the analysis in the actual codebase (truncated).
try:
    files = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
except Exception:
    files = []
tree = "\n".join(files[:400]) or "(empty repository)"

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
        "affected_areas": {"type": "array", "items": {"type": "string"}},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "needs_human_review": {"type": "boolean"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "proposed_stories": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "summary", "acceptance_criteria", "affected_areas", "risk_level",
        "needs_human_review", "reasons", "proposed_stories",
    ],
    "additionalProperties": False,
}

PROMPT = f"""You are the analysis stage of an automated SDLC pipeline. A requirement was
filed as a GitHub issue. Analyze it against the repository and return structured output.

REQUIREMENT
Title: {title}
Body:
{body}

REPOSITORY FILES (truncated):
{tree}

Guidance:
- acceptance_criteria must be concrete and testable.
- affected_areas should name real files/dirs from the list when possible.
- proposed_stories breaks the work into small, independently shippable units.
- Set needs_human_review=true when the requirement is ambiguous, underspecified,
  large, or touches anything sensitive (auth, security, payments, infrastructure,
  data migrations, deletes) OR when you are not confident an automated change can
  satisfy it safely. Otherwise false.
- risk_level reflects blast radius if the change is wrong."""

client = anthropic.Anthropic()
resp = client.messages.create(
    model=MODEL,
    max_tokens=4000,
    thinking={"type": "adaptive"},
    output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    messages=[{"role": "user", "content": PROMPT}],
)
text = next(b.text for b in resp.content if b.type == "text")
a = json.loads(text)

# Deterministic safety gates layered on top of the model's judgment.
SENSITIVE = {"sensitive", "security", "infra", "payments"}
sensitive_label = bool(SENSITIVE.intersection(labels))
needs = bool(a["needs_human_review"]) or a["risk_level"] == "high" or sensitive_label

reasons = list(a["reasons"])
if a["risk_level"] == "high":
    reasons.append("risk_level=high (auto-gate)")
if sensitive_label:
    reasons.append("sensitive label present (auto-gate)")


def md(items):
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


comment = f"""## 🤖 Automated analysis

**Summary:** {a['summary']}

**Acceptance criteria**
{md(a['acceptance_criteria'])}

**Likely affected areas**
{md(a['affected_areas'])}

**Proposed stories**
{md(a['proposed_stories'])}

**Risk:** `{a['risk_level']}` · **Human review required:** {'YES' if needs else 'no'}
{md(reasons) if needs else ''}

_Draft for human review — model `{MODEL}`._"""


def gh(*args, check=True):
    subprocess.run(["gh", *args, "--repo", REPO], check=check)


gh("issue", "comment", ISSUE, "--body", comment)

if needs:
    # Label may not exist yet; create-if-missing, then apply.
    subprocess.run(
        ["gh", "label", "create", "needs-human", "--color", "B60205",
         "--description", "Automated pipeline paused — human action required",
         "--repo", REPO],
        check=False,
    )
    gh("issue", "edit", ISSUE, "--add-label", "needs-human", check=False)
    gh("issue", "comment", ISSUE,
       "--body", "⚠️ **Human review required before automated implementation — pipeline paused.**")

with open(os.environ["GITHUB_OUTPUT"], "a") as f:
    f.write(f"proceed={'false' if needs else 'true'}\n")

print(f"proceed={'false' if needs else 'true'} (needs_human_review={needs})")
