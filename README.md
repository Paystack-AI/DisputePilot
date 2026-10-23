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
# Production Compose

The root `docker-compose.yml` is for local development. A separate production stack is
available in `compose.production.yml`; it has no source mounts, publishes only the Caddy
HTTP/HTTPS ports, enables production cookie settings, and keeps application data in named
volumes.

1. Copy `.env.production.example` to `.env.production` and `ai/.env.production.example` to
   `ai/.env.production`. Replace every placeholder with unique production values. Generate
   the Fernet encryption key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
2. Set the app and API DNS names to this host, allow inbound TCP 80/443 (and optionally UDP
   443), and set `S3_IMAGE` to a pinned, tested image version.
3. Set `ASYNC_DB_URL` and `SYNC_DB_URL` passwords to match `POSTGRES_PASSWORD`, and set the
   RabbitMQ URL password to match `RABBITMQ_DEFAULT_PASS`. Use URL-safe random passwords so
   the connection URLs do not need percent encoding.
4. Start with `docker compose --env-file .env.production -f compose.production.yml up --build -d`.

The frontend proxy stores access, refresh, and admin tokens in `HttpOnly`, same-site cookies;
the browser receives only session metadata. It also checks the request origin for writes made
with an authenticated cookie. Users will need to sign in again after deploying this change.

The stack does not configure off-host backups, restore testing, log retention/alerting, or a
managed secrets service. Set those up before storing production merchant data. Configure and
exercise those operational controls before the first production launch.
