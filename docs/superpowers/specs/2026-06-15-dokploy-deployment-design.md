# Dokploy Deployment — Design Spec

- **Date:** 2026-06-15
- **Status:** Approved (pending final user review of this spec)
- **Owner:** wai1998
- **Topic:** Deploy CastraNova-POS to an existing Dokploy instance via a Docker Compose service.

## 1. Goal

Deploy the CastraNova-POS stack (FastAPI backend + React frontend + PostgreSQL) to an
already-running Dokploy server, served over HTTPS on a real domain, with auto-deploy
from the GitHub `dev` branch.

Success criteria:

- `https://api.castranova.nexuslab.asia/docs` serves the FastAPI OpenAPI docs over valid TLS.
- `https://castranova.nexuslab.asia` serves the frontend and a superuser can log in.
- A push to `dev` triggers a redeploy in Dokploy.
- Database data survives a redeploy.

## 2. Locked Decisions

| Item | Choice |
|---|---|
| Dokploy | Already running on the user's cloud server |
| Deploy method | Dokploy **Docker Compose** service (not Application-per-service) |
| Source | GitHub `Waiphyoaung24/CastraNova-pos`, branch `dev`, auto-deploy on push |
| Compose file | New dedicated **`compose.dokploy.yml`** (local `compose.yml` + `compose.override.yml` untouched) |
| Frontend URL | `https://castranova.nexuslab.asia` (apex of the subdomain) |
| Backend API URL | `https://api.castranova.nexuslab.asia` |
| Database | PostgreSQL **in-stack**, named volume `app-db-data` on the server |
| Adminer | **Dropped** (not exposed publicly) |
| Routing / TLS | Dokploy's own Traefik + **Domains UI** + Let's Encrypt |
| Superuser | `nexuslab.dev.mm@gmail.com` |
| Environment | `ENVIRONMENT=production` |

## 3. Why a dedicated compose file (not editing compose.yml)

`compose.yml` cannot deploy on Dokploy unmodified because its Traefik wiring targets the
template's *own* proxy (`compose.traefik.yml`), not Dokploy's:

1. It declares an external network `traefik-public` that does not exist on a Dokploy host
   (Dokploy uses `dokploy-network`) → `docker compose up` hard-fails.
2. Its labels reference `certresolver=le`, a resolver defined only in `compose.traefik.yml`
   (not deployed) → those routers error on Dokploy's Traefik.
3. Its frontend label routes `Host(dashboard.${DOMAIN})`, but we want the apex host.

Editing `compose.yml` in place is rejected because `compose.override.yml` extends it for
local dev (e.g. the `adminer` override carries no image of its own); removing services from
`compose.yml` would break local `docker compose up`. A separate file isolates the Dokploy
concern with zero churn to the local-dev pair.

## 4. Architecture — `compose.dokploy.yml`

A trimmed derivative of `compose.yml` containing four services. Routing/TLS is **not** in
this file; Dokploy injects it from the Domains UI.

### Services

- **db** — `postgres:18`, `restart: always`, healthcheck via `pg_isready`, named volume
  `app-db-data` mounted at `/var/lib/postgresql/data/pgdata`. Network: `default` only.
- **prestart** — built from `backend/Dockerfile`, `command: bash scripts/prestart.sh`
  (runs Alembic migrations + creates the least-privilege `castranova_app` role + seeds the
  superuser). `depends_on: db (service_healthy)`. Network: `default` only. Exits 0.
- **backend** — same image as prestart, `restart: always`, FastAPI on port 8000.
  `depends_on: db (service_healthy)` + `prestart (service_completed_successfully)`.
  Networks: `dokploy-network` (external, for Traefik) + `default` (to reach db).
  Keeps the `/api/v1/utils/health-check/` healthcheck. **No Traefik labels.**
- **frontend** — built from `frontend/Dockerfile`, `restart: always`, nginx on port 80.
  Build args: `VITE_API_URL=${VITE_API_URL}` (resolved from Dokploy env to
  `https://api.castranova.nexuslab.asia`), `NODE_ENV=production`.
  Network: `dokploy-network` only (browser calls the API via the public domain, so it needs
  no internal link to backend/db). **No Traefik labels.**

### Networks

```yaml
networks:
  dokploy-network:
    external: true   # created and managed by Dokploy
  default:
```

### Volumes

```yaml
volumes:
  app-db-data:
```

### Removed vs `compose.yml`

- `adminer` service (entirely).
- All `traefik.*` labels on every service.
- The `traefik-public` external network (replaced by `dokploy-network`).
- `env_file: .env` references are dropped; all config comes from Dokploy's Environment
  panel (avoids the committed `changethis` `.env` shadowing real values).

### Critical gotcha — VITE_API_URL

`VITE_API_URL` is a **build-time** arg compiled into the frontend bundle. It must be set to
`https://api.castranova.nexuslab.asia` at build time. Changing the API host later requires a
frontend rebuild, not just an env change.

## 5. Dokploy Service Configuration (UI)

- **Create** → Compose service in the target project.
- **Provider:** GitHub → repo `CastraNova-pos` → branch `dev`.
- **Compose Path:** `./compose.dokploy.yml`.
- **Domains tab** — two entries (Dokploy generates the Traefik labels + attaches services to
  `dokploy-network`):
  - Service `frontend`, container port `80`, host `castranova.nexuslab.asia`, HTTPS on,
    cert provider Let's Encrypt.
  - Service `backend`, container port `8000`, host `api.castranova.nexuslab.asia`, HTTPS on,
    cert provider Let's Encrypt.
- **Auto Deploy:** enabled (webhook on push to `dev`).

## 6. Environment Variables (set in Dokploy Environment panel only)

Non-secret:

```
ENVIRONMENT=production
DOMAIN=castranova.nexuslab.asia
FRONTEND_HOST=https://castranova.nexuslab.asia
BACKEND_CORS_ORIGINS=https://castranova.nexuslab.asia,https://api.castranova.nexuslab.asia
VITE_API_URL=https://api.castranova.nexuslab.asia
PROJECT_NAME=CastraNova POS
STACK_NAME=castranova-pos
FIRST_SUPERUSER=nexuslab.dev.mm@gmail.com
POSTGRES_SERVER=db
POSTGRES_PORT=5432
POSTGRES_DB=app
POSTGRES_USER=postgres
POSTGRES_APP_USER=castranova_app
DOCKER_IMAGE_BACKEND=backend
DOCKER_IMAGE_FRONTEND=frontend
```

Secrets — **generated at deploy time, pasted into Dokploy only, never committed:**

```
SECRET_KEY=<generated>
FIRST_SUPERUSER_PASSWORD=<generated>
POSTGRES_PASSWORD=<generated>
POSTGRES_APP_PASSWORD=<generated>
```

Generate each with: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.

`ENVIRONMENT=production` makes the backend refuse to boot if any of `SECRET_KEY`,
`POSTGRES_PASSWORD`, or `FIRST_SUPERUSER_PASSWORD` is still `changethis` — a safety guard,
not a bug.

SMTP and `SENTRY_DSN` are intentionally left unset for the first deploy (see Out of Scope).

## 7. DNS

At the `nexuslab.asia` DNS provider, add two `A` records → the Dokploy server's public IP:

- `castranova` → `<server-ip>`
- `api.castranova` → `<server-ip>`

If the provider is Cloudflare, set both records to **DNS-only (grey cloud)** for the initial
deploy so Let's Encrypt's TLS challenge resolves directly against the server. Proxying can be
re-enabled afterward if desired.

## 8. Data Persistence & Backups

- `app-db-data` is a standard Docker named volume; it survives container recreation and
  redeploys. Dokploy does not delete it on redeploy.
- Scheduled backups are **out of scope** for this deploy. Follow-up: wire Dokploy's
  Volume Backups (or a `pg_dump` schedule) to an S3 destination.

## 9. Security Notes

- Rate limiting stays **enabled** (the dev override that disables it is not present here).
- Adminer is not exposed.
- No secrets in the repo; real values live only in Dokploy's Environment panel.
- Backend runs as the least-privilege `castranova_app` role; migrations run as `postgres`
  (preserved from the existing prestart flow).

## 10. Deploy & Verification Flow

1. Add `compose.dokploy.yml`, commit, push to `dev`.
2. In Dokploy: create the Compose service, set Compose Path, Environment, and Domains.
3. Add the two DNS `A` records.
4. Click **Deploy**. Dokploy clones `dev`, builds the backend + frontend images on the
   server, then runs `db` → `prestart` (migrations + superuser seed) → `backend` + `frontend`.
5. Verify:
   - `https://api.castranova.nexuslab.asia/docs` loads over valid TLS.
   - `https://castranova.nexuslab.asia` loads; log in with `FIRST_SUPERUSER` /
     `FIRST_SUPERUSER_PASSWORD`.
   - Redeploy and confirm existing data persists.

## 11. Out of Scope (follow-ups)

- SMTP / password-reset email delivery.
- Sentry error tracking.
- Scheduled database backups to S3.
- Staging environment.

## 12. Risks / To Verify During Implementation

- **Dokploy `.env` precedence:** confirm the Environment panel values reach the build/runtime
  (Dokploy writes them to the compose working dir); ensure the committed `changethis` `.env`
  does not shadow them. Mitigation: `compose.dokploy.yml` omits `env_file: .env` and relies on
  `${VAR}` interpolation from Dokploy's environment.
- **`dokploy-network` attachment:** confirm Dokploy attaches `backend`/`frontend` to its
  network when domains are added; the explicit `networks:` entry is belt-and-suspenders.
- **Build resources:** the frontend build (bun install + vite build) ran ~15s locally; confirm
  the server has enough RAM/CPU for the on-server build.
- **Apex host TLS:** confirm Let's Encrypt issues for the apex `castranova.nexuslab.asia`
  (DNS-only on Cloudflare if applicable).
