# Deployment Guide

Describes the production infrastructure, CI/CD pipelines, required GitHub
secrets, and the step-by-step process for deploying or releasing each
component.

---

## Infrastructure overview

| Component | Where it runs | How it gets there |
|---|---|---|
| Flask backend | Azure Container Apps | GitHub Actions on push to `develop` |
| Frontend (web) | Azure Static Web Apps | GitHub Actions on push to `develop` |
| LiveKit SFU | Self-hosted (wherever `LIVEKIT_URL` points) | Manual — see below |
| PostgreSQL | Azure Database for PostgreSQL | Pre-provisioned; Alembic migrations run at deploy time |
| MinIO (object store) | Cloud MinIO instance | Pre-provisioned; `MINIO_SECURE=true` in prod |
| Broadcaster binary | GitHub Releases | GitHub Actions on `broadcaster-v*` tag push |

The broadcaster **always runs on the streamer's laptop** — it is never
deployed to a server. Cloud deployment only covers the backend, frontend,
and the services they depend on.

---

## Automated CI/CD pipelines

### Backend (`backend-deploy.yml`)

**Trigger:** push to `develop` branch (or pull request targeting `develop` for tests only).

**Steps:**
1. Run the full test suite (`pytest`).
2. Build a Docker image from `Streaming-App/Dockerfile`.
3. Push the image to Azure Container Registry (ACR) — tagged `:latest` and `:<git-sha>`.
4. Deploy to Azure Container Apps using the SHA-tagged image.

Deployments only happen on direct push to `develop`. Pull requests run
tests only.

### Frontend (`frontend-deploy.yml`)

**Trigger:** push to `develop` branch.

**Steps:**
1. `npm ci` + lint.
2. `npx expo export --platform web` → `dist/` (reads `API_BASE` and `SOCKET_URL` from secrets at build time).
3. Upload `dist/` to Azure Static Web Apps.

### Broadcaster release (`broadcaster-release.yml`)

**Trigger:** pushing a tag matching `broadcaster-v*`
(e.g. `broadcaster-v1.2.0`).

**Steps (parallel matrix: windows-latest, macos-latest, ubuntu-latest):**
1. Install Python 3.11 and broadcaster dependencies.
2. `pyinstaller broadcaster.spec` on each OS.
3. Upload the three binaries (`Broadcaster-Windows.exe`, `Broadcaster-macOS`, `Broadcaster-Linux`) as GitHub Release assets attached to the tag.

---

## GitHub secrets required

Set these in **Settings → Secrets and variables → Actions** for each repo.

### Backend repo (`Streaming-App`)

| Secret | Description |
|---|---|
| `AZURE_CREDENTIALS` | JSON service principal credentials (`az ad sp create-for-rbac --sdk-auth`) |
| `ACR_LOGIN_SERVER` | ACR hostname, e.g. `myregistry.azurecr.io` |
| `ACR_USERNAME` | ACR admin username |
| `ACR_PASSWORD` | ACR admin password |
| `RESOURCE_GROUP` | Azure resource group name |
| `CONTAINER_ENV` | Azure Container Apps environment name |
| `SECRET_KEY` | Flask secret key (random 32+ char string) |
| `DATABASE_URL` | Full connection string, e.g. `postgresql://user:pass@host/db` |
| `LIVEKIT_API_KEY` | LiveKit API key (matches your LiveKit server config) |
| `LIVEKIT_API_SECRET` | LiveKit API secret (32+ chars) |
| `LIVEKIT_URL` | LiveKit WebSocket URL, e.g. `wss://livekit.example.com` |
| `MINIO_ENDPOINT` | MinIO host:port, e.g. `minio.example.com:443` |
| `MINIO_ACCESS_KEY` | MinIO access key |
| `MINIO_SECRET_KEY` | MinIO secret key |
| `CORS_ORIGINS` | Comma-separated allowed origins, e.g. `https://app.example.com` |

### Frontend repo (`FE-Streaming-app`)

| Secret | Description |
|---|---|
| `AZURE_STATIC_WEB_APPS_API_TOKEN` | Deployment token from the Static Web App resource |
| `API_BASE` | Backend URL, e.g. `https://streaming-backend.azurecontainerapps.io` |
| `SOCKET_URL` | Same as `API_BASE` (or a separate Socket.IO URL) |

---

## Releasing a new backend / frontend version

1. Merge your feature branch into `develop`.
2. GitHub Actions runs automatically:
   - Backend: tests → Docker build → push to ACR → deploy to Container Apps.
   - Frontend: lint → web export → deploy to Static Web Apps.
3. Monitor the Actions tab for failures.
4. If the migration set changed (new Alembic revision), run it against
   the production database — see [Database migrations](#database-migrations) below.

---

## Releasing a new broadcaster binary

```bash
# In Streaming-App repo
git tag broadcaster-v1.2.0
git push origin broadcaster-v1.2.0
```

This triggers `broadcaster-release.yml`. Once the Action completes (~5 min),
three binaries are attached to the GitHub Release at that tag:
- `Broadcaster-Windows.exe`
- `Broadcaster-macOS`
- `Broadcaster-Linux`

Streamers download the binary for their OS from the Releases page and run it —
no install, no Python needed.

> The tag name must start with `broadcaster-v`. Anything else won't trigger
> the workflow.

---

## Database migrations

Alembic migrations do **not** run automatically at deploy time — run them
manually against the production database when a migration is included in
a release.

```bash
# From your local machine or a migration runner with DATABASE_URL set
cd Streaming-App
export DATABASE_URL="postgresql://user:pass@prod-host/db"
flask --app run db upgrade
```

To check which revision production is currently on:

```bash
flask --app run db current
```

To check what migrations are pending:

```bash
flask --app run db heads
```

> Always back up the database before running migrations on production.

---

## LiveKit self-hosted setup

LiveKit is not deployed by the CI pipelines — it must be provisioned
separately and its URL set in both the backend secrets and the broadcaster's
`.env` (or login dialog URL).

Minimal self-hosted LiveKit on a VM:

```bash
# Download latest binary from https://github.com/livekit/livekit/releases
./livekit-server --config livekit.yaml --bind 0.0.0.0
```

The `livekit.yaml` in this repo is a development config. For production,
set a real domain, enable TLS, and configure TURN. See
[LiveKit self-hosting docs](https://docs.livekit.io/home/self-hosting/deployment/).

Firewall rules required:
- `7880/tcp` — LiveKit HTTP/WebSocket
- `7881/tcp` — LiveKit RTC (alternative)
- `50000–60000/udp` — WebRTC media

---

## Environment variables: dev vs. production differences

| Variable | Dev (`.env`) | Production |
|---|---|---|
| `FLASK_ENV` | `development` | `production` |
| `DATABASE_URL` | empty (SQLite) or local Postgres | Azure PostgreSQL connection string |
| `MINIO_SECURE` | `false` | `true` |
| `LIVEKIT_URL` | `ws://localhost:7880` | `wss://your-livekit-domain` |
| `CORS_ORIGINS` | `*` | Specific frontend domain(s) |
| `SECRET_KEY` | any string | Strong random 32+ char string |
| `RATELIMIT_STORAGE_URI` | `memory://` | `redis://...` (recommended) |

---

## Rollback

**Backend:** re-deploy the previous Docker image SHA via the Azure portal
or CLI:

```bash
az containerapp update \
  --name streaming-backend \
  --resource-group <RESOURCE_GROUP> \
  --image <ACR_LOGIN_SERVER>/streaming-backend:<previous-sha>
```

**Frontend:** use the Azure Static Web Apps portal to revert to a previous
deployment (Environments → Production → Deployment history → Reactivate).

**Broadcaster:** streamers can download any previous release binary from
the GitHub Releases page.
