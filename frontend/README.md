# DisputePilot + TrustLayer frontend

The merchant workspace and read-only admin console for DisputePilot, built with Next.js (App
Router), TypeScript, TanStack Query, Zustand, Tailwind CSS and Recharts.

All browser requests go through the app's own proxy: the client calls `/api/proxy/<path>` and the
Next.js server forwards it to the FastAPI service at `/api/v1/<path>`. The backend URL is never
exposed to the browser and no CORS configuration is needed.

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local
```

`BACKEND_INTERNAL_URL` points at the API:

- local development: `http://127.0.0.1:8000`
- Docker Compose: `http://disputepilot_api:8000`

## Run

```bash
npm run dev
```

The app is served on `http://localhost:3000`. The API should be running and migrated first.

## Routes

Merchant workspace (authenticated):

- `/` dashboard
- `/reconciliation` and `/reconciliation/session/[id]`
- `/disputes` and `/disputes/[id]`
- `/customers` and `/customers/[id]`
- `/orders`, `/orders/new`, `/orders/[id]`
- `/fulfillments/new`
- `/trust`
- `/settings`, `/settings/paystack`, `/onboarding`

Public and operator:

- `/public/trust/[token]` public TrustLayer page (no auth)
- `/admin/login`, `/admin`, `/admin/merchants`, `/admin/merchants/[id]` read-only console

## Auth model

Merchant access and refresh tokens are stored client-side and attached by the API client. A 401
triggers a single refresh attempt and retries the request; failed refresh returns the user to
`/login`. Admin sessions use a separate token and `/admin/login`; the API client clears the admin
token on 401.

## Checks

These are the same checks CI and pre-commit run:

```bash
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build
```

## Docker

From the repository root:

```bash
docker compose up --build disputepilot_frontend
```

The frontend listens on port 3000. The Docker build bakes `BACKEND_INTERNAL_URL` into the proxy
rewrite, so pass it as a build arg when targeting a different host. The image uses Next.js
standalone output and runs as a non-root user.
