# Deploying Dograh to Azure Container Apps — Lift & Shift (Portal Only)

> [!NOTE]
> This is the **Approach B: All-in-Container-Apps** guide. Every service from [docker-compose-ecs.yaml](file:///d:/dograh%2021-7/dograh/docker-compose-ecs.yaml) — including PostgreSQL, Redis, and MinIO — runs as a Container App. **Zero code changes. No CLI required.**

---

## Architecture Overview

```mermaid
graph TB
    subgraph Internet
        User["Browser / Mobile App"]
    end

    subgraph ACA["Container Apps Environment — dograh-env"]
        PG["postgres<br/>pgvector/pgvector:pg17<br/>:5432 internal"]
        REDIS["redis<br/>redis:7<br/>:6379 internal"]
        MINIO["minio<br/>minio/minio<br/>:9000/:9001 internal"]
        API["api<br/>dograh-api image<br/>:8000 public"]
        ARI["ari-manager<br/>dograh-api image<br/>no ingress"]
        CAMP["campaign-orchestrator<br/>dograh-api image<br/>no ingress"]
        ARQ["arq-worker<br/>dograh-api image<br/>no ingress"]
        UI["ui<br/>dograh-ui image<br/>:3010 public"]
    end

    User -->|HTTPS| UI
    User -->|HTTPS| API
    UI -->|"http://api:8000"| API
    API --> PG
    API --> REDIS
    API --> MINIO
    ARI --> PG
    ARI --> REDIS
    CAMP --> PG
    CAMP --> REDIS
    ARQ --> PG
    ARQ --> REDIS
    ARQ --> MINIO
```

All 8 Container Apps live in the **same environment**, so they can reach each other by **app name** as hostname — exactly like Docker Compose service names.

---

## Step 1: Create a Resource Group

1. Go to **[portal.azure.com](https://portal.azure.com)** → Search **"Resource groups"** → **+ Create**
2. Fill in:
   - **Subscription**: Your subscription
   - **Resource group**: `enxtai`
   - **Region**: `Central India` (or your preferred region)
3. Click **Review + Create** → **Create**

---

## Step 2: Create Azure Container Registry (ACR)

You need a registry to store your two custom Docker images.

1. Search **"Container registries"** → **+ Create**
2. **Basics** tab — Fill in:
   - **Resource group**: `enxtai`
   - **Registry name**: `dograhacr` (globally unique, alphanumeric only)
   - **Location**: `Central India`
   - **Domain name label scope**: `Unsecure`
   - **Pricing plan**: `Standard`
   - **Role assignment permissions mode**: `RBAC Registry Permissions`
3. **Networking** tab (leave defaults):
   - **Connectivity configuration**: `Public access (all networks)`
   - **Regional endpoint / Dedicated data endpoint**: `Disabled` (unchecked)
4. Click **Review + Create** → **Create**
5. After creation → go to your **`dograhacr`** container registry in the Azure portal.
6. On the left menu, scroll to **Settings** and click **Access keys**.
7. Click the **Admin user** toggle to **Enabled**. (The username and password fields will only appear *after* you enable this).
8. Once enabled, note down these three values from the same page:
   - **Login server**: `dograhacr.azurecr.io`
   - **Username**: `dograhacr`
   - **Password**: (copy the first password)

### Push Your Two Images

From your project root (`d:\dograh 21-7\dograh`), run these in PowerShell:

```powershell
# Log in to ACR
docker login dograhacr.azurecr.io -u dograhacr -p <password>
```

**Option A: If you already built the images using docker-compose**
```powershell
# Tag and push existing API image
docker tag dograh-api:latest dograhacr.azurecr.io/dograh-api:latest
docker push dograhacr.azurecr.io/dograh-api:latest

# Tag and push existing UI image
# NOTE: only reuse a locally-built UI image for Azure if it was built with
# --build-arg BACKEND_URL=https://<api-public-url>. A plain
# `docker compose build ui` bakes in the local http://api:8000 backend, which
# breaks browser API calls once deployed. When in doubt, rebuild per Option B.
docker tag dograh-ui:latest dograhacr.azurecr.io/dograh-ui:latest
docker push dograhacr.azurecr.io/dograh-ui:latest
```
# For azure based : 
```docker build --build-arg BACKEND_URL=https://api.delightfulplant-df21b4fc.centralindia.azurecontainerapps.io -t dograhacr.azurecr.io/dograh-ui:latest -f ui/Dockerfile .
```

**Option B: If you haven't built the images yet**
```powershell
# Build and push API image
docker build -t dograhacr.azurecr.io/dograh-api:latest -f api/Dockerfile .
docker push dograhacr.azurecr.io/dograh-api:latest

# Build and push UI image.
# IMPORTANT: the UI bakes the backend URL into its rewrite rules at build time
# (ui/Dockerfile defaults to the local http://api:8000). For Azure you must
# pass your api app's public URL explicitly, otherwise browser API calls will
# target the wrong backend. Replace <api-public-url> with your api app URL
# (e.g. https://api.happyocean-xxxxxxxx.centralindia.azurecontainerapps.io).
# If you don't know it yet, build with a placeholder, deploy the api app first
# to learn its URL, then rebuild + push the UI image with the real URL.
docker build --build-arg BACKEND_URL=https://<api-public-url> -t dograhacr.azurecr.io/dograh-ui:latest -f ui/Dockerfile .
docker push dograhacr.azurecr.io/dograh-ui:latest
```

> [!TIP]
> **Don't have Docker locally?** Use **ACR Tasks** to build in the cloud: go to your ACR → **Services** → **Tasks** → **+ Quick task** → upload a `.tar.gz` of your source code and specify the Dockerfile.

---

## Step 3: Create a Storage Account (for Persistent Volumes)

Container Apps are ephemeral. Without volumes, PostgreSQL, Redis, and MinIO **lose all data on restart**. Azure Files provides persistent storage.

1. Search **"Storage accounts"** → **+ Create**
2. Fill in:
   - **Resource group**: `enxtai`
   - **Storage account name**: `dograhstorage` (globally unique, lowercase)
   - **Region**: `Central India`
   - **Primary service**: `Azure Files` (or leave as "Choose preferred storage type")
   - **Performance**: `Standard`
   - **Redundancy**: Select **Locally-redundant storage (LRS)** (cheapest/recommended here) or `ZRS` for production. *(Avoid GRS unless you specifically want to pay for cross-region replication).*
3. Click **Review + Create** → **Create**
4. After creation → go to the storage account → **Data storage** → **File shares** → create **4 file shares**:

   | File Share Name | Quota |
   |---|---|
   | `postgres-data` | 10 GiB (increase as needed) |
   | `redis-data` | 2 GiB |
   | `minio-data` | 50 GiB (increase as needed) |
   | `shared-tmp` | 5 GiB — scratch space shared by `api` and `arq-worker` (see note below) |

> [!IMPORTANT]
> The `shared-tmp` share is **required for call recordings, transcripts, and summaries**. When a call ends, the `api` app writes audio/transcript temp files and the `arq-worker` app reads them back to upload to MinIO and generate the summary/transcript. Container Apps do **not** share filesystems, so without a common file share mounted at `/tmp` on **both** apps, completion jobs fail with "temp file not found" and calls end up with no recording, transcript, or summary. This mirrors the `shared-tmp:/tmp` volume in `docker-compose-ecs.yaml`.

5. Go to **Security + networking** → **Access keys** → Note the **Storage account name** and **Key1**

---

## Step 4: Create the Container Apps Environment

1. Search **"Container Apps"** → **+ Create**
2. **Basics** tab:
   - **Resource group**: `enxtai`
   - **Container app name**: `dummy-app` (We are creating a temporary app just to force Azure to create the environment)
   - **Region**: `Central India`
3. Still on the Basics tab, under **Container Apps environment**, click the blue link **Create new environment**.
   - **Environment name**: `dograh-env`
   - **Zone redundancy**: `Disabled`
   - Go to the **Monitoring** tab in the pop-up and set **Log Analytics workspace** to `Create new` → `dograh-logs`
   - Click **Create** to close the pop-up.
4. Back on the main screen, click **Next: Container >**
   - Leave "Use quickstart image" checked.
5. Click **Review + Create** → **Create**. 
*(Once deployed, your environment exists! You can safely delete `dummy-app` later).*

### Add Azure Files Storage to the Environment

After the environment is created:

1. Go to **dograh-env** → **Settings** → **Volume mounts**
2. Click **+ Add** → **Server Message Block (SMB)** and add all four shares:

   | Name (reference) | Storage account | Access key | File share |
   |---|---|---|---|
   | `redis-vol` | `dograhstorage` | (paste Key1) | `redis-data` | **Read/Write** |
   | `minio-vol` | `dograhstorage` | (paste Key1) | `minio-data` | **Read/Write** |
   | `shared-tmp-vol` | `dograhstorage` | (paste Key1) | `shared-tmp` | **Read/Write** |

*(Note: We do not attach the postgres share here because Postgres is incompatible with Azure Files SMB storage)*

> [!IMPORTANT]
> You **must** add the Azure Files storage to the **environment** first. Only then can you mount them in individual Container Apps.

---

## Step 5: Create Container Apps (in Order)

Create the services in dependency order: infrastructure first, then backend, then frontend.

---

### 5A. PostgreSQL (pgvector)

1. Search **"Container Apps"** → **+ Create**
2. **Basics** tab:
   - **Container app name**: `postgres`
   - **Container Apps Environment**: `dograh-env`
   - Uncheck "Use quickstart image"
3. **Container** tab:
   - **Image source**: Docker Hub or other registries
   - **Image and tag**: `pgvector/pgvector:pg17`
   - **CPU and Memory**: `1 vCPU, 2 Gi`
   - **Command override**: *(leave empty)*
   - **Arguments override**: `-c, tcp_keepalives_idle=60, -c, tcp_keepalives_interval=60, -c, tcp_keepalives_count=5` *(This prevents Azure's 4-minute idle connection timeout)*
   - **Environment variables**:
     | Name | Value |
     |---|---|
     | `POSTGRES_USER` | `postgres` |
     | `POSTGRES_PASSWORD` | `postgres` |
     | `POSTGRES_DB` | `postgres` |
     | `PGDATA` | `/var/lib/postgresql/data/pgdata` |
4. **Ingress** tab:
   - **Ingress**: Enabled
   - **Ingress traffic**: `Limited to Container Apps Environment` (internal only)
   - **Ingress type / Transport**: `TCP`
   - **Target port**: `5432`
   - **Exposed port**: `5432`
5. Click **Review + Create** → **Create**.

6. Click **Review + Create** → **Create**.

> [!WARNING]
> **Important Note about PostgreSQL in Azure Container Apps**
> PostgreSQL is fundamentally incompatible with standard Azure Files (SMB) storage due to POSIX permission and locking requirements.
> 
> For this deployment guide, we will use **Ephemeral Storage** for PostgreSQL, which means the database will be wiped if the container is restarted. 
> 
> **For Production:** You MUST use the official **Azure Database for PostgreSQL - Flexible Server** service instead of running Postgres inside a container app.

#### Set Scale for Postgres
Azure requires you to adjust scaling *after* the initial creation:
1. Go to your newly created **postgres** container app.
2. In the left menu, go to **Application** --> **Revision and replicas**.
3. Click **+ Create new revision**.
4. Click on your `postgres` container to edit it.
5. On the "Create and deploy new revision" screen, look for the **Scale** tab (or section).
   - Set **Min replicas**: `1`
   - Set **Max replicas**: `1`
6. Click **Create** at the bottom to deploy the new revision.

> [!WARNING]
> **Set min AND max replicas to 1 for postgres.** Scaling a database container to multiple replicas will cause data corruption. This is a single-instance database, not a cluster.

---

### 5B. Redis

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `redis`, Environment: `dograh-env`
3. **Container** tab:
   - **Image source**: Docker Hub or other registries
   - **Image and tag**: `redis:7`
   - **CPU and Memory**: `0.5 vCPU, 1 Gi`
   - **Command override**: `redis-server, --requirepass, redissecret, --appendonly, yes`
   - **Arguments override**: *(leave empty)*
   - **No environment variables needed**
4. **Ingress** tab:
   - **Ingress**: Enabled
   - **Ingress traffic**: `Limited to Container Apps Environment` (internal only)
   - **Ingress type / Transport**: `TCP`
   - **Target port**: `6379`
   - **Exposed port**: `6379`
5. Click **Review + Create** → **Create**.

#### Attach Storage & Set Scale for Redis
1. Go to your newly created **redis** container app.
2. In the left menu, go to **Revision and Replicas**.
3. Click **+ Create new revision**.
4. Click on your `redis` container to edit it.
5. Go to the **Volume mounts** tab.
6. Click **+ Add**:
   - Volume: `redis-vol`
   - Mount path: `/data`
   - Sub-path: `redisdata`
7. Click **Save** on the container edit panel.
8. Go to the **Scale** tab (or section) on the revision screen:
   - Set **Min replicas**: `1`, **Max replicas**: `1`
9. Click **Create** to deploy.

---

### 5C. MinIO (S3 Object Storage)

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `minio`, Environment: `dograh-env`
3. **Container** tab:
   - **Image source**: Docker Hub
   - **Image and tag**: `minio/minio:latest`
   - **CPU and Memory**: `1 vCPU, 2 Gi`
   - **Command override**: *(leave empty)*
   - **Arguments override**: `server, /data, --console-address, :9001`
   - **Environment variables**:
     | Name | Value |
     |---|---|
     | `MINIO_ROOT_USER` | `minioadmin` |
     | `MINIO_ROOT_PASSWORD` | `minioadmin` |
     | `MINIO_API_CORS_ALLOW_ORIGIN` | `*` |
4. **Ingress**:
   - Enabled → **Limited to Container Apps Environment**
   - Target port: `9000`
   - Transport: `HTTP/1`
5. Click **Review + Create** → **Create**.

#### Attach Storage & Set Scale for MinIO
1. Go to your newly created **minio** container app.
2. In the left menu, go to **Revision and replicas**.
3. Click **+ Create new revision**.
4. Click on your `minio` container to edit it.
5. Go to the **Volume mounts** tab.
6. Click **+ Add**:
   - Volume: `minio-vol`
   - Mount path: `/data`
   - Sub-path: `miniodata`
7. Click **Save** on the container edit panel.
8. Go to the **Scale** tab (or section) on the revision screen:
   - Set **Min replicas**: `1`, **Max replicas**: `1`
9. Click **Create** to deploy.

> [!TIP]
> To access the MinIO Console (port 9001) for debugging, you can temporarily change ingress to accept traffic from anywhere and set the target port to 9001. Remember to revert this after debugging.

---

### 5D. API Server (FastAPI)

This is the main API service. It runs Alembic migrations on startup, then serves via uvicorn.

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `api`, Environment: `dograh-env`
3. **Container** tab:
   - **Image source**: Azure Container Registry
   - **Registry**: `dograhacr.azurecr.io`
   - **Image**: `dograh-api`
   - **Tag**: `latest`
   - **CPU and Memory**: `2 vCPU, 4 Gi`
   - **Command override**: `sh, -c, alembic -c api/alembic.ini upgrade head && uvicorn api.app:app --host 0.0.0.0 --port 8000`
   - **Environment variables**:

     | Name | Value |
     |---|---|
     | `ENVIRONMENT` | `production` |
     | `LOG_LEVEL` | `INFO` |
     | `LOG_TO_FILE` | `false` |
     | `DATABASE_URL` | `postgresql+asyncpg://postgres:postgres@postgres:5432/postgres` |
     | `REDIS_URL` | `redis://:redissecret@redis:6379` |
     | `ENABLE_AWS_S3` | `false` |
     | `MINIO_ENDPOINT` | `minio:80` |
     | `MINIO_ACCESS_KEY` | `minioadmin` |
     | `MINIO_SECRET_KEY` | `minioadmin` |
     | `MINIO_BUCKET` | `voice-audio` |
     | `MINIO_SECURE` | `false` |
     | `MINIO_PUBLIC_ENDPOINT` | `minio:80` |
     | `BACKEND_API_ENDPOINT` | *(set after creation — use the api app's public URL)* |
     | `UI_APP_URL` | *(set after creation — use the ui app's public URL)* |
     | `TURN_SECRET` | `dograh-turn-secret-change-in-production` |
     | `TURN_HOST` | `localhost` |
     | `OSS_JWT_SECRET` | *(generate a strong random string)* |

4. **Ingress** tab:
   - **Ingress**: Enabled
   - **Ingress traffic**: `Accepting traffic from anywhere` (public)
   - **Target port**: `8000`
   - **Transport**: `Auto`
5. **Scale** tab:
   - Min replicas: `1`
   - Max replicas: `3`
   - Scale rule: HTTP concurrent requests (default)
6. **Create**

After creation, add **health probes**:
1. Go to the `api` Container App → **Application** → **Containers** → click the container → **Health probes**
2. Add:
   - **Startup probe**: HTTP GET, path `/api/v1/health`, port `8000`, initial delay `60s`, period `10s`, failure threshold `18`
   - **Liveness probe**: HTTP GET, path `/api/v1/health`, port `8000`, initial delay `0s` (startup probe handles delay), period `30s`
   - **Readiness probe**: HTTP GET, path `/api/v1/health`, port `8000`, initial delay `0s`, period `10s`

Note the **Application URL** after creation (e.g., `https://api.happyocean-xxxxxxxx.centralindia.azurecontainerapps.io`).

#### Attach Shared Scratch Storage for `api`
1. Go to your newly created **api** container app.
2. In the left menu, go to **Revision and replicas**.
3. Click **+ Create new revision**.
4. Click on your `api` container to edit it.
5. Go to the **Volume mounts** tab.
6. Click **+ Add**:
   - Volume: `shared-tmp-vol`
   - Mount path: `/tmp`
7. Click **Save** on the container edit panel.
8. Click **Create** to deploy.

> [!IMPORTANT]
> Mounting `shared-tmp-vol` at `/tmp` on **both** `api` and `arq-worker` is what lets call recordings, transcripts, and summaries work: `api` writes the temp files when a call ends and `arq-worker` reads them back. Skip this and every call will complete with no recording, transcript, or summary.

---

### 5E. ARI Manager (Telephony Bridge)

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `ari-manager`, Environment: `dograh-env`
3. **Container** tab:
   - **Image**: `dograhacr.azurecr.io/dograh-api:latest` (same image as api)
   - **CPU and Memory**: `0.5 vCPU, 1 Gi`
   - **Command override**: `python, -m, api.services.telephony.ari_manager`
   - **Environment variables**: Same as api (copy all from step 5D)
4. **Ingress**: **Disabled** (no HTTP traffic)
5. **Scale**: Min: `1`, Max: `1`
6. **Create**

---

### 5F. Campaign Orchestrator

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `campaign-orchestrator`, Environment: `dograh-env`
3. **Container** tab:
   - **Image**: `dograhacr.azurecr.io/dograh-api:latest`
   - **CPU and Memory**: `0.5 vCPU, 1 Gi`
   - **Command override**: `python, -m, api.services.campaign.campaign_orchestrator`
   - **Environment variables**: Same as api
4. **Ingress**: **Disabled**
5. **Scale**: Min: `1`, Max: `1`
6. **Create**

---

### 5G. ARQ Worker (Background Queue)

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `arq-worker`, Environment: `dograh-env`
3. **Container** tab:
   - **Image**: `dograhacr.azurecr.io/dograh-api:latest`
   - **CPU and Memory**: `1 vCPU, 2 Gi`
   - **Command override**: `python, -m, arq, api.tasks.arq.WorkerSettings, --custom-log-dict, api.tasks.arq.LOG_CONFIG`
   - **Environment variables**: Same as api
4. **Ingress**: **Disabled**
5. **Scale**: Min: `1`, Max: `3` (scale on queue depth)
6. **Create**

#### Attach Shared Scratch Storage for `arq-worker`
Same procedure as for `api` above: new revision → edit container → **Volume mounts** → **+ Add** → Volume: `shared-tmp-vol`, Mount path: `/tmp` → Save → Create. Both apps must mount the **same** share so temp files written by `api` are visible to `arq-worker`.

> [!NOTE]
> The worker also runs the **follow-up callback scheduler** (per-minute cron, no extra container needed) and the **local sentiment model**. On first use the worker downloads ~1 GB of model weights from Hugging Face and holds them in memory — allow outbound internet egress and expect the first sentiment classification after a deploy to take a minute or two. The 1 vCPU / 2 Gi sizing above accommodates this; raise RAM if you see OOM restarts in the worker's log stream.

---

### 5H. UI Dashboard (Next.js)

1. **Container Apps** → **+ Create**
2. **Basics**: Name: `ui`, Environment: `dograh-env`
3. **Container** tab:
   - **Image**: `dograhacr.azurecr.io/dograh-ui:latest`
   - **CPU and Memory**: `0.5 vCPU, 1 Gi`
   - **Environment variables**:
     | Name | Value |
     |---|---|
     | `NODE_ENV` | `production` |
     | `BACKEND_URL` | `http://api:8000` |
     | `NEXT_PUBLIC_NODE_ENV` | `oss` |
     | `NEXT_TELEMETRY_DISABLED` | `1` |
4. **Ingress** tab:
   - Enabled → **Accepting traffic from anywhere** (public)
   - **Target port**: `3010`
   - **Transport**: `Auto`
5. **Scale**: Min: `1`, Max: `3`
6. **Create**

Note the **Application URL** (e.g., `https://ui.happyocean-xxxxxxxx.centralindia.azurecontainerapps.io`).

---

## Step 6: Post-Creation — Update Cross-References

Now that all apps are created, go back and set the URLs that reference each other:

1. Go to **`api`** Container App → **Application** → **Containers** → **Edit and deploy** → update these env vars:
   - `BACKEND_API_ENDPOINT` → `https://api.happyocean-xxxxxxxx.centralindia.azurecontainerapps.io` (the public URL of your api app)
   - `UI_APP_URL` → `https://ui.happyocean-xxxxxxxx.centralindia.azurecontainerapps.io`
   - `MINIO_PUBLIC_ENDPOINT` → same as `MINIO_ENDPOINT` (`minio:9000`) for internal use, or the api public URL if serving files externally
2. Do the same update for `ari-manager`, `campaign-orchestrator`, and `arq-worker`

---

## Step 7: Verify Everything is Running

### Check Container Status
1. Go to each Container App → **Application** → **Revisions and replicas**
2. Click the active revision → **Replica** → check **Running** status
3. If a replica shows **Failed** or **Waiting**, click it to see container logs

### Check Logs
1. Go to any Container App → **Monitoring** → **Log stream**
2. Select the container and view real-time stdout/stderr

### Test the Endpoints
- **API Health**: Open `https://api.<your-env>.centralindia.azurecontainerapps.io/api/v1/health`
- **UI Dashboard**: Open `https://ui.<your-env>.centralindia.azurecontainerapps.io`

---

## Step 8: Custom Domains & HTTPS (Optional)

Azure Container Apps provides free managed TLS certificates:

1. Go to `api` Container App → **Settings** → **Custom domains** → **+ Add**
2. Enter your domain: `api.dograh.com`
3. Azure shows DNS records to add:
   - **CNAME** or **A record** + **TXT record** for validation
4. Add them in your DNS provider → click **Validate** → **Bind**
5. Azure automatically provisions a free TLS certificate
6. Repeat for `ui` → `app.dograh.com`

After binding, update all env vars (`BACKEND_API_ENDPOINT`, `UI_APP_URL`) to use your custom domains.

---

## Quick Reference Card

### All Services at a Glance

| # | App Name | Image | Command | CPU | RAM | Ingress | Port |
|---|---|---|---|---|---|---|---|
| 1 | `postgres` | `pgvector/pgvector:pg17` | *(default)* | 1 | 2 Gi | Internal TCP | 5432 |
| 2 | `redis` | `redis:7` | `redis-server --requirepass redissecret --appendonly yes` | 0.5 | 1 Gi | Internal TCP | 6379 |
| 3 | `minio` | `minio/minio` | `server /data --console-address :9001` | 1 | 2 Gi | Internal HTTP | 9000 |
| 4 | `api` | `dograhacr.azurecr.io/dograh-api:latest` | `sh -c "alembic ... && uvicorn ..."` | 2 | 4 Gi | **Public** HTTP | 8000 |
| 5 | `ari-manager` | `dograhacr.azurecr.io/dograh-api:latest` | `python -m api.services.telephony.ari_manager` | 0.5 | 1 Gi | Disabled | — |
| 6 | `campaign-orchestrator` | `dograhacr.azurecr.io/dograh-api:latest` | `python -m api.services.campaign.campaign_orchestrator` | 0.5 | 1 Gi | Disabled | — |
| 7 | `arq-worker` | `dograhacr.azurecr.io/dograh-api:latest` | `python -m arq api.tasks.arq.WorkerSettings ...` | 1 | 2 Gi | Disabled | — |
| 8 | `ui` | `dograhacr.azurecr.io/dograh-ui:latest` | *(default CMD)* | 0.5 | 1 Gi | **Public** HTTP | 3010 |

### Shared Environment Variables (for api, ari-manager, campaign-orchestrator, arq-worker)

```env
ENVIRONMENT=production
LOG_LEVEL=INFO
LOG_TO_FILE=false
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/postgres
REDIS_URL=redis://:redissecret@redis:6379
ENABLE_AWS_S3=false
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=voice-audio
MINIO_SECURE=false
MINIO_PUBLIC_ENDPOINT=minio:9000
BACKEND_API_ENDPOINT=https://<api-public-url>
UI_APP_URL=https://<ui-public-url>
TURN_SECRET=dograh-turn-secret-change-in-production
TURN_HOST=localhost
OSS_JWT_SECRET=<generate-a-strong-random-string>
```

> [!IMPORTANT]
> These are the **exact same values** from your `docker-compose-ecs.yaml`. The service names (`postgres`, `redis`, `minio`, `api`) work as hostnames because all apps are in the same Container Apps Environment.

### Volume Mounts Summary

| App | Azure Files Share | Mount Path | Sub-path |
|---|---|---|---|
| `postgres` | `postgres-data` | `/var/lib/postgresql/data` | `pgdata` |
| `redis` | `redis-data` | `/data` | — |
| `minio` | `minio-data` | `/data` | — |
| `api` | `shared-tmp` | `/tmp` | — |
| `arq-worker` | `shared-tmp` | `/tmp` | — |

---

## Cost Estimate (Central India, Consumption Plan)

| Resource | Spec | ~Monthly (INR) |
|---|---|---|
| Container Registry (Basic) | 10 GB included | ₹425 |
| Storage Account (LRS) | ~62 GiB files | ₹150 |
| `postgres` | 1 vCPU, 2 Gi, always-on | ₹2,800 |
| `redis` | 0.5 vCPU, 1 Gi, always-on | ₹1,400 |
| `minio` | 1 vCPU, 2 Gi, always-on | ₹2,800 |
| `api` | 2 vCPU, 4 Gi, always-on | ₹5,600 |
| `ari-manager` | 0.5 vCPU, 1 Gi | ₹1,400 |
| `campaign-orchestrator` | 0.5 vCPU, 1 Gi | ₹1,400 |
| `arq-worker` | 1 vCPU, 2 Gi | ₹2,800 |
| `ui` | 0.5 vCPU, 1 Gi | ₹1,400 |
| **Total** | | **≈ ₹20,175/month** |

> [!TIP]
> On the Consumption plan, idle containers with no HTTP traffic (like workers) still incur charges if `min replicas > 0`. To save costs during development, set workers' min replicas to `0` and use a KEDA scale rule to wake them on queue activity.

---

## Production Hardening Checklist

- [ ] **Secrets**: Move `POSTGRES_PASSWORD`, `REDIS_URL`, `MINIO_SECRET_KEY`, `OSS_JWT_SECRET` to Container App **Secrets** (Settings → Secrets) and reference them via `secretref:` in env vars
- [ ] **Backups**: Set up Azure Files **snapshots** on a schedule for `postgres-data` and `minio-data`
- [ ] **Password rotation**: Change default passwords (`postgres`, `redissecret`, `minioadmin`) to strong values
- [ ] **Custom domains**: Bind `api.dograh.com` and `app.dograh.com` with managed TLS certificates
- [ ] **Network restriction**: Set `postgres`, `redis`, `minio` ingress to **internal only** (already covered above)
- [ ] **Log retention**: Configure Log Analytics workspace retention (default 30 days, extend if needed)
- [ ] **Alerts**: Set up Azure Monitor alerts for container restart loops, high CPU, and health probe failures
- [ ] **CORS**: Update `MINIO_API_CORS_ALLOW_ORIGIN` from `*` to your specific domains

> [!CAUTION]
> This approach runs **stateful databases in ephemeral containers**. While Azure Files provides persistence, there is **no automatic failover, replication, or point-in-time restore** like managed database services offer. For production workloads with critical data, consider migrating Postgres to Azure Database for PostgreSQL Flexible Server and Redis to Azure Cache for Redis.
