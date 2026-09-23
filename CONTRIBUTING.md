# Contributing

## One-time setup

```bash
# Pre-commit (needs Python 3)
pip install pre-commit detect-secrets
pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

Then follow the README inside whichever team folder(s) you work in (`frontend/`, `backend/`, `ai/`)
for that stack's own setup.

## Branching

- `main` is protected by a local hook — commits must be made on a branch, then merged into `main`
  (PR or fast-forward merge, whichever's faster mid-hackathon).
- Branch names: `feat/short-description`, `fix/short-description`, `chore/short-description`.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) — enforced by
  the `commit-msg` hook: `feat: add login form`, `fix: correct date parsing`.

## What runs when

| When | What runs |
|---|---|
| `git commit` | file hygiene checks, secret scan, lint/format for whichever team's files changed, commit message format |
| `git push` | tests for whichever team's files changed |
| PR opened / push to PR | full CI for each team touched: lint + test + build, gitleaks, CodeQL, dependency review |

If a hook fails, fix the issue and re-commit — don't skip hooks (`--no-verify`) unless you've cleared
it with the team; CI runs the same checks and will still block the PR.

## Pull requests

Use the PR template checklist. Keep PRs scoped to one team/feature where possible — easier to review,
easier to revert. Flag any breaking change to a shared contract (API shape, schema, event format)
explicitly and give the other teams a heads-up before merging.

## Cross-team contract

This repo intentionally ships without a fixed API contract, schema, or route structure baked in —
those are for the three teams to agree on together. Once you do, write the agreed contract down
somewhere the whole team can see it (a shared doc, an OpenAPI file committed to `backend/`, etc.) and
keep it updated as it changes.
