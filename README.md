# disputepilot-trustlayer

Hackathon team repo. This scaffold intentionally does **not** bake in any product architecture,
routes, schema, or design decisions — those are for the three teams to work out and agree on
together. What's here is the cross-cutting infrastructure every team needs regardless of what gets
built: repo structure, CI, commit hooks, and baseline security.

## Structure

```
frontend/   Web app team
backend/    API/server team
ai/         AI/ML team
```

Each folder has its own minimal, runnable placeholder (a "hello world" health check) plus a README
for that team's own setup instructions. Replace the placeholder as your team's real work lands —
nothing about the shared tooling below depends on what's inside these folders.

## One-time setup

```bash
git clone <repo-url> && cd disputepilot-trustlayer

pip install pre-commit detect-secrets
pre-commit install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
```

Then see each team folder's own README for that stack's setup (`frontend/README.md`,
`backend/README.md`, `ai/README.md`).

## Docs

- [`CONTRIBUTING.md`](CONTRIBUTING.md) — setup, branching, what the hooks/CI check
- [`SECURITY.md`](SECURITY.md) — security controls and required GitHub settings

## Next steps for the team

1. Agree on the product architecture, API contract, and data model together, and write it down
   somewhere shared (this repo, a doc, whatever works) once decided.
2. Replace the placeholder app in each team folder with real work.
3. Update `.github/CODEOWNERS` with actual GitHub usernames.
4. Push to GitHub and turn on branch protection + secret scanning (see `SECURITY.md`).
