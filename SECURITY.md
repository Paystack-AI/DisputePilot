# Security

## Reporting

Don't open a public issue for a vulnerability. Message a maintainer directly or open a private
security advisory (GitHub → Security → Advisories → "Report a vulnerability").

## Controls in this repo

| Layer | Control |
|---|---|
| Secrets | `.env*` git-ignored; `detect-secrets` pre-commit hook + `gitleaks` in CI block committed secrets |
| Dependencies | Dependabot (npm, pip, GitHub Actions) weekly; `pip-audit` in CI; `dependency-review-action` on every PR |
| Static analysis | CodeQL (JS/TS + Python) on push, PR, and weekly schedule |
| Branch protection | See "Required GitHub settings" below |
| Commit hooks | `pre-commit` runs lint/format/secret-scan before every commit; tests before every push |

## Baseline rules, regardless of what each team builds

- Never commit real secrets, API keys, or `.env` files — use `.env.example` as the template.
- Never log or return secrets, tokens, or password hashes in any API response.
- Any multi-tenant data (if the product ends up multi-tenant) must be scoped per-tenant on every
  query; decide and document the isolation strategy once the schema exists.
- Verify signatures on any inbound webhook; reject malformed or replayed requests.
- Validate and size/type-check any file upload.
- Any endpoint that isn't meant for production (demo/reset/debug endpoints) must be gated behind a
  secret and disabled by default outside of local/staging.

These will get more specific once each team's architecture is settled — update this file as those
decisions land.

## Required GitHub settings (set once the repo is pushed)

Branch protection on `main`:

- Require a pull request before merging (at least 1 approval)
- Require status checks to pass before merging (CI jobs + secret-scan + CodeQL)
- Require branches to be up to date before merging
- Do not allow force pushes; do not allow deletions

Repo settings:

- Enable Dependabot alerts + security updates (Settings → Security)
- Enable secret scanning + push protection (Settings → Security → Code security)
- Restrict who can push directly to `main` (should be no one — PRs only)
