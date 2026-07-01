# Enterprise Playbook — Parallel-Sandbox Agentic SDLC

> **Purpose:** a battle-tested guide to stand up the parallel-sandbox SDLC orchestrator
> (requirement → analysis → plan → parallel build → integrate) in an enterprise org, with
> mandatory human gates and cost controls. It folds in the [`PLAYBOOK.md`](PLAYBOOK.md)
> single-agent foundation and the [`SANDBOX-ORCHESTRATOR.md`](SANDBOX-ORCHESTRATOR.md) design,
> plus every gotcha hit while bringing it live on a real repo — so you don't rediscover them.
>
> Replace `ORG` with your GitHub organization throughout.

---

## 1. What you get

```
Requirement (GitHub issue + `requirement-parallel` label)
  → 🤖 TRIAGE   : analyze, post structured analysis, decide if a human is needed   [cheap model]
  → 🚦 GATE     : needs-human? → pause; human adds `approved-parallel` to proceed
  → 🤖 PLAN     : decompose into independent, file-fenced slices + ownership map    [cheap model]
  → 🤖 BUILD    : matrix fan-out — one agent per slice, each fenced, each opens a PR [strong model]
  → 🤖 INTEGRATE: merge slices → run full CI → route failures to owning sandbox      [next increment]
  → 👤 HUMAN    : reviews + merges the per-slice PRs                                 ← gate
  → 🏷️  RELEASE  : tag vX.Y.Z → build + release                                       ← human-tagged
```

Plus a persistent **learning log** (`docs/learning-log/`) that grounds planning in past work and
is updated after each requirement, and a standard **parallel CI pipeline** on every push/PR.

**Design principles (carried from the base playbook)**
- **Rules defined once** in a central repo; every project references them (`uses: ORG/sdlc-templates/...@v1`).
- **Human-in-the-loop gates** at: needs-review escalation, every PR merge, and deploy. **AI never merges or deploys.**
- **Event-driven & label-gated** → zero cost until a requirement is filed.
- **Right model for the job** — cheap model for triage/planning, strong model only for code-writing.
- **No two sandboxes write the same file** — the cardinal rule that makes parallelism safe.

---

## 2. Prerequisites (the ones that actually bite)

A checklist gathered from real first-run failures. Verify *all* before expecting a green run.

- [ ] **`gh` token scopes:** `workflow` (push workflow files), `admin:org` (org secrets/settings).
- [ ] **`ANTHROPIC_API_KEY` reachable by the repo.** ⚠️ **Org secrets do NOT reach *private* repos on
      GitHub Free** — even at visibility "All". On Free, either make the repo public, set a
      **repo-level** secret, or upgrade the org to **Team/Enterprise** (enterprises already have this).
- [ ] **The Anthropic account has CREDITS.** Pay-as-you-go, separate from any Claude subscription.
      An empty balance fails with `400 - credit balance too low`. Opus build agents × N slices add up
      fast — see §7 Cost.
- [ ] **Default workflow token = "Read and write"**, and **"Allow Actions to create and approve PRs" = ON**.
- [ ] **Claude Code GitHub App installed** on the org/repos (the build agents need it).
- [ ] **Private repos need Actions minutes/billing** (or self-hosted runners) — on Free, private-repo
      Actions startup-fail with a misleading "workflow file issue."
- [ ] **`make` targets exist** and each **installs its deps** (see §6 gotcha: lockfile/install).
- [ ] Each consuming repo carries **`docs/learning-log/`** (the planner reads its `INDEX.md`).

---

## 3. Architecture

```
ORG/sdlc-templates  ★ central — defined ONCE, pinned at @v1
  .github/workflows/
    standard-sdlc.yml        (reusable: parallel CI)
    release.yml              (reusable: build + release on tag)
    ai-sdlc.yml              (reusable: single-agent Analyst + Developer)
    ai-sdlc-parallel.yml     (reusable: triage → plan → parallel build [→ integrate])
    code-review.yml          (reusable: independent Reviewer)
  scripts/
    triage.py                (analysis + human gate; labels parameterized via env)
    plan.py                  (decompose → slices + .wave/ownership.json)
        ▲ referenced via `uses:` (cross-owner works if central repo is public)
each project repo carries tiny CALLER workflows + a Makefile + docs/learning-log/:
    .github/workflows/{ci,release,ai-sdlc,ai-sdlc-parallel,review}.yml
    scripts/{validate-learning-log.mjs, triage-owner.mjs}
    docs/learning-log/{INDEX.md, entries/, prompts/, RUNBOOK.md}
```

The central repo holds the logic; each repo holds a **doorbell** (caller) because GitHub events fire
only where they happen. CI work is delegated to `make <target>` so the same commands run locally and in CI.

---

## 4. Setup runbook

```bash
# 0. Prereqs: gh authed with workflow + admin:org. Org exists.

# 1. Create/seed the central repo (keep it PUBLIC so callers can reference it cross-owner),
#    add the reusable workflows + scripts/{triage,plan}.py, then tag it:
git -C sdlc-templates tag v1 && git -C sdlc-templates push origin v1

# 2. Org config (set ONCE):
gh secret set ANTHROPIC_API_KEY --org ORG --visibility all     # NOTE: private repos on Free need a REPO secret instead
gh api -X PUT orgs/ORG/actions/permissions/workflow \
   -F default_workflow_permissions=write -F can_approve_pull_request_reviews=true

# 3. Install the Claude Code GitHub App on the org → all repositories.

# 4. Per consuming repo: copy the caller workflows + Makefile + scripts/*.mjs, scaffold
#    docs/learning-log/ (copy from the reference repo). Create the labels:
gh label create requirement-parallel --repo ORG/app --color 1D76DB
gh label create approved-parallel    --repo ORG/app --color 0E8A16

# 5. Use it:
#    File an issue → add `requirement-parallel` → triage + plan post, then pause.
#    Review the plan → add `approved-parallel` → build agents fan out and open per-slice PRs.
#    Review + merge the PRs. Tag vX.Y.Z to release.
```

**Pilot safely:** keep `auto_implement: false` (plan-only) on first repos. Turn on the build
fan-out per repo only after the plans look right on real requirements.

---

## 5. Operating procedure (one requirement, end to end)

1. **File** an issue describing a *multi-part* requirement (so it splits into slices).
2. **Label** `requirement-parallel` → triage analyzes + gates; plan decomposes + posts an
   ownership table (and writes `.wave/ownership.json`).
3. **Review** the plan. If good, add **`approved-parallel`** → build agents fan out (one per slice,
   fenced to its `owns` globs), each opening a `Part of #N` PR. Per-slice CI gates each PR.
4. **Integrate** (next increment): merge slices → run the full suite → route any failure to its
   owning sandbox via `scripts/triage-owner.mjs` against `.wave/ownership.json` → fix/retest loop.
5. **Human merges** the PRs; **tag** a release. Consolidate learnings into `docs/learning-log/`.

---

## 6. Gotchas that cost real time (read before debugging)

Every one of these was hit live. They are the most valuable part of this document.

1. **Org secrets don't reach private repos on Free.** Symptom: `ANTHROPIC_API_KEY` resolves *empty*
   in the run (auth error), even though the org secret exists at visibility "All". Fix: repo-level
   secret, or Team/Enterprise plan, or public repo.
2. **Empty credit balance ≠ bad key.** `400 credit balance too low` means top up the Anthropic
   Console account; `401 invalid x-api-key` means the key is wrong/garbled. Different fixes.
3. **A newly-merged workflow misses the event that's already in flight.** Add a workflow to the
   default branch, then immediately label an issue → only the *previously-registered* workflows fire.
   Fix: re-toggle the label (remove + re-add) once the new workflow is registered.
4. **Workflows only trigger from the DEFAULT branch.** A caller on a feature branch will not fire on
   `issues`/`push` events. Merge it to `main` first.
5. **Shared labels cross pipelines.** If two flows both listen for `approved`, approving one fires
   both. Give each flow its OWN labels (`requirement`/`approved` vs `requirement-parallel`/
   `approved-parallel`). Parameterize the gate script via env (`APPROVE_LABEL`, `REQUIREMENT_LABEL`)
   so one script serves both with different inputs.
6. **`make` targets must install their own deps.** A `test` target that runs `vitest`/`pytest`
   without an install step fails with `command not found`. Every target that needs deps must install first.
7. **Lockfile drift across npm versions.** `npm ci` hard-fails when `package-lock.json` doesn't match
   what the CI's npm resolves (e.g. CI wants `esbuild@0.28.1`, lock has `0.21.5`). Use
   `npm ci || npm install` so a drifted lock falls back to a resolving install instead of red CI.
   (Pinning the Node/npm version in CI is the stricter alternative.)
8. **Reusable-workflow permissions are validated at STARTUP, before `if:`.** A job requesting a
   permission the caller's default token can't grant fails the whole run with a generic "workflow file
   issue." Keep CI on the read-only default token; only request `write`/`id-token: write` where the
   default allows it (the build/implement jobs).
9. **`claude-code-action` needs `id-token: write` + `--allowedTools` + the GitHub App.** Missing any:
   the job "succeeds" but the agent does nothing (no branch, no PR). Build agents need
   `Bash,Edit,Read,Write,Glob,Grep`; reviewers (read-only) need `Bash,Read,Glob,Grep`.
10. **Agents inherit a broken baseline.** If `main`'s `make ci` is red, build agents burn their turns
    fighting it and may bail without opening PRs. Keep `main` green — a broken baseline silently
    sabotages the fan-out.
11. **`trivy-action` tags are `v`-prefixed**; **`gitleaks-action@v2` breaks on PR events** (run the
    gitleaks CLI directly); **re-running a successful run replays the OLD event** (re-trigger via a
    fresh event, e.g. toggle the label).

---

## 7. Cost control (do this from day one)

The build fan-out spawns **N strong-model agent sessions per requirement** — the single biggest cost.

- **Split models:** triage + planning use a cheap `analysis_model` (e.g. `claude-sonnet-4-6`); only
  the build agents use the strong `model` (e.g. `claude-opus-4-8`). This is wired as separate inputs.
- **Cap fan-out:** `max_sandboxes` (start 2–4). Review bandwidth, not agent count, is the real limit.
- **Label-gated:** zero spend until a requirement is filed and approved.
- **`--max-turns`** on the build agents to bound runaway sessions.
- **Monitor spend** on the Anthropic Console; alert on balance. Keep credits topped up — a dry balance
  halts the whole pipeline mid-flow.
- **Plan-only mode** (`auto_implement: false`) costs only two cheap-model calls per requirement — use
  it broadly; enable the expensive build fan-out only where it pays off.

---

## 8. Enterprise adaptations (make the gates mandatory)

**Identity & access**
- Org/Enterprise **rulesets** + a `.github` repo for org-wide CODEOWNERS, issue/PR templates.
- Enforce **SSO/SAML**; scope the GitHub App + OIDC minimally.

**Mandatory gates (don't rely on convention)**
- **Branch protection on `main`:** required status checks (the CI jobs) + **N approving reviews** +
  **CODEOWNERS** review + linear history. Now neither humans nor agents merge unreviewed.
- Require an **`approved-parallel` label by a CODEOWNER** before the build fan-out runs.
- Keep **`auto_implement: false`** by default; enable autonomous build per-repo, deliberately, on
  low-risk services first.

**CI/CD at scale**
- **Self-hosted or larger runners** for private-repo Actions volume/cost; set concurrency limits.
- **Dependency caching** and **affected-only testing** (Nx/Turborepo/Bazel or `paths:` filters) for
  large monorepos — critical once pipelines feel slow.
- **GitHub Environments + deployment approvals** for staging → prod. `main` ≠ production; deploy is a
  gated promotion, never automatic.
- Real **SAST/DAST/secret-scanning/SBOM** in the PR gate; tune severity baselines.

**Secrets & supply chain**
- Org/Environment secrets; **OIDC to cloud** (AWS/GCP/Azure) instead of long-lived keys.
- **Pin third-party actions to commit SHAs** (not tags); enable Dependabot.

**AI governance & audit**
- Every agent action lands in Actions logs + PR history — keep the human merge/deploy gates non-negotiable.
- **Scope autonomy gradually:** triage/plan-only across all repos first; build fan-out on a few
  low-risk services; expand as trust builds.
- **Data sensitivity:** triage/plan send issue text + a file listing (not full source); build agents
  run in your CI and read the repo. Confirm this matches policy; for stricter needs route Claude via
  your approved cloud (Bedrock/Vertex) and review the action's data flow.

**Platform / golden path**
- At many-team scale, add a catalog (Backstage) with software templates = your project template, and
  org rulesets as enforcement. This is the paved-road / platform-engineering pattern.

---

## 9. Rollout sequence (proven order, small → large)

1. Stand up the central repo + template + org config (§4). Tag `@v1`.
2. **Plan-only** (`auto_implement: false`) on a few repos — learn what analyses + plans look like;
   cost ≈ a couple of cheap-model calls per requirement.
3. Add **branch protection** + **CODEOWNERS** so the gates are mandatory.
4. Add the **Reviewer** on all PRs.
5. Enable the **build fan-out** on one or two low-risk services; watch the first runs closely
   (expect to shake out the §6 gotchas). Keep `main` green.
6. Add the **integrate + defect-triage** increment once per-slice PRs are trustworthy.
7. Wire **environments + deploy approvals**; integrate real security scanners; add caching /
   affected-only testing once pipelines feel slow.

> Watch for: friction points (automate them before scaling), what you keep skipping (drop it), and
> where one agent struggles (only then split it). Capture each lesson in the learning log.
```
