# Dokploy Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy CastraNova-POS to the existing Dokploy instance as a Docker Compose service, served over HTTPS on `castranova.nexuslab.asia` (frontend) and `api.castranova.nexuslab.asia` (backend), auto-deploying from the GitHub `dev` branch.

**Architecture:** A dedicated `compose.dokploy.yml` (derived from `compose.yml`) defines `db`, `prestart`, `backend`, `frontend`. It removes the template's own Traefik labels and `traefik-public` network and `adminer`; Dokploy's Traefik handles routing/TLS via its Domains UI, with web-facing services joined to the external `dokploy-network`. Postgres runs in-stack on the `app-db-data` named volume. All config (including secrets) is supplied through Dokploy's Environment panel, not the repo.

**Tech Stack:** Dokploy (Compose service), Docker Compose, Traefik (Dokploy-managed), PostgreSQL 18, FastAPI, React/Vite, Let's Encrypt.

**Spec:** `docs/superpowers/specs/2026-06-15-dokploy-deployment-design.md`

**Branch:** `feat/dokploy-deploy` (spec already committed here as `1936ad1`).

---

## File Structure

- **Create** `compose.dokploy.yml` (repo root) — the only new file. Sole responsibility: define the Dokploy-deployable stack. Does not touch `compose.yml` / `compose.override.yml` (local dev unaffected).
- No application code changes. No migration changes (the existing `scripts/prestart.sh` flow is reused as-is).

---

## Task 1: Create `compose.dokploy.yml`

**Files:**
- Create: `compose.dokploy.yml`

- [ ] **Step 1: Write the file**

Create `compose.dokploy.yml` at the repo root with exactly this content:

```yaml
services:

  db:
    image: postgres:18
    restart: always
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      retries: 5
      start_period: 30s
      timeout: 10s
    volumes:
      - app-db-data:/var/lib/postgresql/data/pgdata
    environment:
      - PGDATA=/var/lib/postgresql/data/pgdata
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_DB=${POSTGRES_DB}

  prestart:
    image: '${DOCKER_IMAGE_BACKEND}:${TAG:-latest}'
    build:
      context: .
      dockerfile: backend/Dockerfile
    depends_on:
      db:
        condition: service_healthy
        restart: true
    command: bash scripts/prestart.sh
    environment:
      - DOMAIN=${DOMAIN}
      - FRONTEND_HOST=${FRONTEND_HOST}
      - ENVIRONMENT=${ENVIRONMENT}
      - BACKEND_CORS_ORIGINS=${BACKEND_CORS_ORIGINS}
      - SECRET_KEY=${SECRET_KEY}
      - FIRST_SUPERUSER=${FIRST_SUPERUSER}
      - FIRST_SUPERUSER_PASSWORD=${FIRST_SUPERUSER_PASSWORD}
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_USER=${SMTP_USER}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
      - EMAILS_FROM_EMAIL=${EMAILS_FROM_EMAIL}
      - POSTGRES_SERVER=db
      - POSTGRES_PORT=${POSTGRES_PORT}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_APP_USER=${POSTGRES_APP_USER}
      - POSTGRES_APP_PASSWORD=${POSTGRES_APP_PASSWORD}
      - SENTRY_DSN=${SENTRY_DSN}

  backend:
    image: '${DOCKER_IMAGE_BACKEND}:${TAG:-latest}'
    restart: always
    networks:
      - dokploy-network
      - default
    depends_on:
      db:
        condition: service_healthy
        restart: true
      prestart:
        condition: service_completed_successfully
    build:
      context: .
      dockerfile: backend/Dockerfile
    environment:
      - DOMAIN=${DOMAIN}
      - FRONTEND_HOST=${FRONTEND_HOST}
      - ENVIRONMENT=${ENVIRONMENT}
      - BACKEND_CORS_ORIGINS=${BACKEND_CORS_ORIGINS}
      - SECRET_KEY=${SECRET_KEY}
      - FIRST_SUPERUSER=${FIRST_SUPERUSER}
      - FIRST_SUPERUSER_PASSWORD=${FIRST_SUPERUSER_PASSWORD}
      - SMTP_HOST=${SMTP_HOST}
      - SMTP_USER=${SMTP_USER}
      - SMTP_PASSWORD=${SMTP_PASSWORD}
      - EMAILS_FROM_EMAIL=${EMAILS_FROM_EMAIL}
      - POSTGRES_SERVER=db
      - POSTGRES_PORT=${POSTGRES_PORT}
      - POSTGRES_DB=${POSTGRES_DB}
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_APP_USER=${POSTGRES_APP_USER}
      - POSTGRES_APP_PASSWORD=${POSTGRES_APP_PASSWORD}
      - SENTRY_DSN=${SENTRY_DSN}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/utils/health-check/"]
      interval: 10s
      timeout: 5s
      retries: 5

  frontend:
    image: '${DOCKER_IMAGE_FRONTEND}:${TAG:-latest}'
    restart: always
    networks:
      - dokploy-network
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        - VITE_API_URL=${VITE_API_URL}
        - NODE_ENV=production

networks:
  dokploy-network:
    external: true
  default:

volumes:
  app-db-data:
```

Key differences from `compose.yml` (intentional):
- No `adminer`, no `proxy`/Traefik service.
- No `traefik.*` labels anywhere.
- `traefik-public` → `dokploy-network` (external, Dokploy-managed).
- No `${VAR?Variable not set}` markers (Dokploy supplies vars; avoids hard-fail during `config`).
- No `env_file: .env` (prevents the committed `changethis` `.env` from shadowing Dokploy env).
- `frontend` `VITE_API_URL` is interpolated from env (set to the production API URL in Dokploy).

---

## Task 2: Validate the compose file

**Files:** none (validation only)

- [ ] **Step 1: Validate YAML + interpolation**

Run (PowerShell, repo root):

```powershell
docker compose -f compose.dokploy.yml config
```

Expected: prints the fully-resolved config with no YAML/parse errors. Warnings about unset
variables (e.g. `SECRET_KEY`) are **fine** — those come from Dokploy at deploy time. There must
be **no** `services.*` schema error and **no** "additional property" error.

- [ ] **Step 2: Confirm the service set**

Run:

```powershell
docker compose -f compose.dokploy.yml config --services
```

Expected output (order may vary):

```
db
prestart
backend
frontend
```

There must be **no** `adminer` and **no** `proxy`.

---

## Task 3: Commit `compose.dokploy.yml`

**Files:** `compose.dokploy.yml`

- [ ] **Step 1: Stage only the new file**

```powershell
git add compose.dokploy.yml
```

- [ ] **Step 2: Commit**

```powershell
git commit -m "feat(deploy): add compose.dokploy.yml for Dokploy stack"
```

(Append the standard `Co-Authored-By` trailer per repo convention.)

- [ ] **Step 3: Verify the commit is clean**

```powershell
git log --oneline -2
git status -sb
```

Expected: the new commit on top of `1936ad1`; `compose.yml` and `compose.override.yml`
unchanged; the pre-existing `routeTree.gen.ts` CRLF noise and untracked dirs still untracked.

---

## Task 4: Generate deployment secrets

**Files:** none (secrets are NOT committed — they go into Dokploy only)

- [ ] **Step 1: Generate four secrets**

Run:

```powershell
python -c "import secrets; [print(k, secrets.token_urlsafe(32)) for k in ['SECRET_KEY','POSTGRES_PASSWORD','POSTGRES_APP_PASSWORD','FIRST_SUPERUSER_PASSWORD']]"
```

Expected: four `KEY value` lines.

- [ ] **Step 2: Store them securely**

Copy the four values into a password manager / secure note. They will be pasted into Dokploy in
Task 8. **Do not** write them into any file under the repo. `FIRST_SUPERUSER_PASSWORD` is the
login password for `nexuslab.dev.mm@gmail.com`.

---

## Task 5: Push branch and merge to `dev`

> Dokploy deploys from the `dev` branch, so `compose.dokploy.yml` must land on `dev` before
> deployment. Per repo flow: feature branch → PR → `dev`.

**Files:** none

- [ ] **Step 1: Push the branch**

```powershell
git push -u origin feat/dokploy-deploy
```

- [ ] **Step 2: Open a PR to `dev`**

Use the `create-pr` skill, or:

```powershell
gh pr create --base dev --head feat/dokploy-deploy --title "Dokploy deployment: compose.dokploy.yml + design/plan" --body "Adds compose.dokploy.yml (Dokploy-tailored stack) plus the deployment design spec and plan. Local dev compose untouched."
```

- [ ] **Step 3: Merge to `dev`**

After review, merge the PR (squash or merge per repo norm). Confirm `compose.dokploy.yml` is
present on `dev`:

```powershell
git fetch origin && git ls-tree origin/dev --name-only | Select-String "compose.dokploy.yml"
```

Expected: prints `compose.dokploy.yml`.

---

## Task 6: Add DNS records (manual — DNS provider for `nexuslab.asia`)

**Prereq:** the Dokploy server's public IPv4 address (visible in Dokploy → Server, or your VPS
provider's dashboard). Call it `<server-ip>`.

- [ ] **Step 1: Create two A records**

| Type | Name | Value | Proxy |
|---|---|---|---|
| A | `castranova` | `<server-ip>` | DNS-only |
| A | `api.castranova` | `<server-ip>` | DNS-only |

If using Cloudflare, set both to **DNS-only (grey cloud)** for the initial deploy so Let's
Encrypt's TLS challenge resolves directly to the server.

- [ ] **Step 2: Verify DNS resolves**

```powershell
nslookup castranova.nexuslab.asia
nslookup api.castranova.nexuslab.asia
```

Expected: both resolve to `<server-ip>`. (May take a few minutes to propagate.)

---

## Task 7: Create the Dokploy Compose service (manual — Dokploy UI)

- [ ] **Step 1: New Compose service**

In the target Dokploy project: **Create Service → Compose**.

- [ ] **Step 2: Set the Git source**

- Provider: **GitHub** (the already-connected account).
- Repository: `Waiphyoaung24/CastraNova-pos`.
- Branch: **`dev`**.

- [ ] **Step 3: Set the Compose path**

- Compose Path: **`./compose.dokploy.yml`**.
- Compose Type: **`docker-compose`** (not Swarm/stack).

Expected: Dokploy saves the service; no fields rejected.

---

## Task 8: Set Environment variables in Dokploy (manual — Dokploy UI)

- [ ] **Step 1: Paste non-secret env**

In the service's **Environment** panel, paste:

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
DOCKER_IMAGE_BACKEND=castranova-backend
DOCKER_IMAGE_FRONTEND=castranova-frontend
SMTP_HOST=
SMTP_USER=
SMTP_PASSWORD=
EMAILS_FROM_EMAIL=info@castranova.nexuslab.asia
SENTRY_DSN=
```

> Note: `DOCKER_IMAGE_BACKEND`/`FRONTEND` use `castranova-` prefixes (not the repo defaults
> `backend`/`frontend`) to avoid image-name collisions with other stacks on the shared Dokploy
> host.

- [ ] **Step 2: Paste the four secrets from Task 4**

```
SECRET_KEY=<from Task 4>
POSTGRES_PASSWORD=<from Task 4>
POSTGRES_APP_PASSWORD=<from Task 4>
FIRST_SUPERUSER_PASSWORD=<from Task 4>
```

- [ ] **Step 3: Save**

Expected: 21 variables saved. Double-check there is **no** remaining `changethis` value — the
backend refuses to boot in `production` if `SECRET_KEY`, `POSTGRES_PASSWORD`, or
`FIRST_SUPERUSER_PASSWORD` is `changethis`.

---

## Task 9: Configure Domains in Dokploy (manual — Dokploy UI)

- [ ] **Step 1: Add the frontend domain**

In the service's **Domains** tab → **Add Domain**:
- Service Name: `frontend`
- Container Port: `80`
- Host: `castranova.nexuslab.asia`
- HTTPS: **on**
- Certificate: **Let's Encrypt**

- [ ] **Step 2: Add the backend domain**

**Add Domain** again:
- Service Name: `backend`
- Container Port: `8000`
- Host: `api.castranova.nexuslab.asia`
- HTTPS: **on**
- Certificate: **Let's Encrypt**

Expected: two domains listed, both HTTPS, both bound to the correct service/port.

---

## Task 10: Deploy and verify

- [ ] **Step 1: Deploy**

Click **Deploy** in the Dokploy service. Watch the build/deploy logs.

Expected log progression: clones `dev` → builds `castranova-backend` + `castranova-frontend`
images → `db` becomes healthy → `prestart` runs Alembic migrations + seeds the superuser and
exits 0 → `backend` + `frontend` start. No `traefik-public`/network errors.

- [ ] **Step 2: Verify the backend over TLS**

```powershell
curl.exe -i https://api.castranova.nexuslab.asia/api/v1/utils/health-check/
```

Expected: `HTTP/2 200` with a valid certificate (no TLS warning).

- [ ] **Step 3: Verify the API docs**

Open `https://api.castranova.nexuslab.asia/docs` in a browser. Expected: the FastAPI Swagger UI
loads over valid HTTPS.

- [ ] **Step 4: Verify the frontend + login**

Open `https://castranova.nexuslab.asia`. Expected: the app loads. Log in with
`nexuslab.dev.mm@gmail.com` / `FIRST_SUPERUSER_PASSWORD` (from Task 4). Confirm the sidebar
(including the latest Exchange Rates settings) renders and an authenticated API call succeeds
(no CORS error in the browser console).

- [ ] **Step 5: Verify data persistence**

Trigger a redeploy in Dokploy (or push a trivial commit to `dev`). After it completes, log in
again and confirm the superuser and any created data still exist (the `app-db-data` volume
survived).

---

## Task 11: Post-deploy follow-ups (track, not now)

- [ ] Wire scheduled DB backups: Dokploy **Volume Backups** (or a `pg_dump` schedule) for
  `app-db-data` → an S3 destination.
- [ ] Configure SMTP (`SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`/`EMAILS_FROM_EMAIL`) to enable
  password-reset emails.
- [ ] Optionally set `SENTRY_DSN` for error tracking.
- [ ] Optionally add a staging environment (second Dokploy service on a `staging` branch /
  `staging.castranova.nexuslab.asia`).

---

## Self-Review Notes

- **Spec coverage:** every spec section maps to a task — compose design §4 → Task 1; Dokploy
  service §5 → Task 7/9; env §6 → Task 8; DNS §7 → Task 6; persistence §8 → Task 10 Step 5;
  deploy/verify §10 → Task 10; out-of-scope §11 → Task 11.
- **Deviation from spec §6:** `DOCKER_IMAGE_BACKEND/FRONTEND` use `castranova-` prefixes (spec
  listed bare `backend`/`frontend`) to prevent image-name collisions on the shared host. Benign,
  noted in Task 8.
- **Risks (spec §12):** validated where possible pre-deploy (Task 2 config check), and called out
  in Task 10 verification (TLS on apex host, network attachment, env precedence via no
  `env_file`).
