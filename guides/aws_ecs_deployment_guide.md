# Dograh AI — AWS ECS Deployment Guide

This guide details the step-by-step process of deploying the Dograh AI stack to Amazon ECS (Elastic Container Service).

We will deploy a production-grade, highly available architecture using **ECS Fargate**, **AWS Application Load Balancer (ALB)**, and fully managed AWS resources (**RDS**, **ElastiCache**, and **S3**).

---

## 🏗️ Architecture Overview

```mermaid
graph TD
    User([User / Web Console]) -->|HTTPS| ALB[Application Load Balancer]
    Vobiz([Vobiz / Telephony]) -->|HTTPS/WSS Webhooks| ALB
    
    subgraph ECS Cluster [ECS Cluster]
        ALB -->|Port 3010| UI_Task[Next.js UI Service]
        ALB -->|Port 8000| API_Task[FastAPI API Service]
        
        API_Task -->|Triggers jobs| Redis[ElastiCache Redis]
        ARQ_Task[ARQ Worker Service] -->|Processes jobs| Redis
        Orch_Task[Campaign Orchestrator] -->|Schedules campaigns| Redis
        ARI_Task[ARI Manager] -->|Manages bridges| Redis
        
        API_Task -->|Read/Write| Postgres[RDS PostgreSQL]
        ARQ_Task -->|Read/Write| Postgres
        Orch_Task -->|Read/Write| Postgres
        ARI_Task -->|Read/Write| Postgres
    end
    
    API_Task -->|Audio Recordings| S3[Amazon S3 Bucket]
    ARQ_Task -->|Audio Recordings| S3
    
    API_Task -->|Local Embeddings| Ollama[Ollama (nomic-embed-text)]
    ARQ_Task -->|Local Embeddings| Ollama
```

---

## 📋 Prerequisites & AWS Setup

Before launching containers, provision the necessary AWS resources:

### 1. Amazon RDS (PostgreSQL)
* **Engine**: PostgreSQL 17+ (or Aurora Serverless v2)
* **Extensions**: Connect to the DB and run `CREATE EXTENSION IF NOT EXISTS pgvector;`
* **VPC**: Place in private subnets, allowing inbound connections on port `5432` only from the ECS tasks security group.

### 2. Amazon ElastiCache (Redis)
* **Engine**: Redis (v7.x)
* **Access Control**: Enable Transit Encryption and configure Auth Token (Redis password). Allow inbound connections on port `6379` from ECS tasks.

### 3. Amazon S3 (Audio Storage)
* Create a private S3 bucket (e.g., `dograh-audio-recordings`).
* **CORS Configuration** (for client-side audio playback in UI):
  ```json
  [
    {
      "AllowedHeaders": ["*"],
      "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
      "AllowedOrigins": ["https://dashboard.yourdomain.com"],
      "ExposeHeaders": ["ETag"]
    }
  ]
  ```

### 4. Ollama (Optional - Local Embeddings)
If you want to use local embeddings instead of OpenAI/Google embeddings:
* Ollama will be deployed as part of the ECS task (see Task Definition below)
* The `nomic-embed-text` model will be automatically pulled on first run
* Configure your embedding service to use Self-Hosted mode with base URL `http://127.0.0.1:11434`

### 5. IAM Roles
Create two IAM roles for ECS:
1. **ECS Task Execution Role (`ecsTaskExecutionRole`)**:
   * Policies: `AmazonECSTaskExecutionRolePolicy`, plus inline permission to read secrets from AWS Secrets Manager (if storing database passwords there).
2. **ECS Task Role**:
   * Policies: Full access to the configured Amazon S3 bucket for audio uploads and signing URLs.

---

## 🐳 Step 1: Build & Push Images to ECR

Create two private repositories in **Amazon ECR** (Elastic Container Registry):
1. `dograh-api`
2. `dograh-ui`

Execute the following commands in your shell to authenticate, build, and push the images:

```bash
# 1. Authenticate Docker with ECR
aws ecr get-login-password --region <aws-region> | docker login --username AWS --password-stdin <aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com

# 2. Build and push the API Image
docker build -t dograh-api -f api/Dockerfile .
docker tag dograh-api:latest <aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com/dograh-api:latest
docker push <aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com/dograh-api:latest

# 3. Build and push the UI Image
docker build -t dograh-ui -f ui/Dockerfile .
docker tag dograh-ui:latest <aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com/dograh-ui:latest
docker push <aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com/dograh-ui:latest
```

---

## 🌐 Step 2: Configure ALB & Target Groups

1. **Target Group 1 (API)**:
   * **Target Type**: IP (required for Fargate)
   * **Protocol**: HTTP (Port 8000)
   * **Health Check Path**: `/api/v1/health`
   * **Interval**: 30 seconds
2. **Target Group 2 (UI)**:
   * **Target Type**: IP
   * **Protocol**: HTTP (Port 3010)
   * **Health Check Path**: `/`
3. **Application Load Balancer**:
   * Create an Internet-facing ALB in your public subnets.
   * Add an **HTTPS (Port 443)** listener using your ACM SSL Certificate.
   * **Routing Rules**:
     * Route `https://api.yourdomain.com/*` $\rightarrow$ Target Group 1 (API).
     * Route `https://dashboard.yourdomain.com/*` $\rightarrow$ Target Group 2 (UI).
   * **Critical setting**: In the ALB Attributes, ensure **Idle Timeout** is set to `3600` seconds (1 hour). This prevents active WebSockets for long calls from being terminated by AWS.

---

## 📝 Step 3: Define ECS Task Definitions

You will create **two** ECS Task Definitions.

### Task Definition 1: Backend Stack (API & Background Workers)
For cost-efficiency and performance, you can group the backend services inside a single Fargate Task Definition. In `awsvpc` network mode, these containers share the same network namespace and can communicate via `localhost`.

Define 8 containers inside this task:

### Volume Configuration for Ollama

The `ollama` and `ollama-init` containers require persistent storage for embedding models. You have two options:

#### Option A: Empty Volume (Simple - For Testing)
Docker-managed volume that persists only while the container exists:

```json
"volumes": [
  {
    "name": "ollama_models",
    "host": {}
  }
]
```

#### Option B: EFS Volume (Recommended for Production)
Persistent storage that survives task restarts:

```json
"volumes": [
  {
    "name": "ollama_models",
    "efsVolumeConfiguration": {
      "fileSystemId": "fs-xxxxxxxx",
      "rootDirectory": "/",
      "transitEncryption": "ENABLED"
    }
  }
]
```

Both `ollama` and `ollama-init` containers must use the same volume to share models.

---

#### 1. `api` (Web Server)
* **Image**: `<aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com/dograh-api:latest`
* **Port Mapping**: Container Port `8000` (TCP)
* **Command**: `sh,-c,alembic -c api/alembic.ini upgrade head && uvicorn api.app:app --host 0.0.0.0 --port 8000`
* **Environment Variables**:
  * `ENVIRONMENT`: `"production"`
  * `LOG_TO_FILE`: `"false"`
  * `BACKEND_API_ENDPOINT`: `"https://api.yourdomain.com"` (or your ALB DNS name)
  * `DATABASE_URL`: `"postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/postgres"`
  * `REDIS_URL`: `"redis://:redissecret@127.0.0.1:6379"`
  * `ENABLE_AWS_S3`: `"false"`
  * `MINIO_ENDPOINT`: `"127.0.0.1:9000"` (internal container communication)
  * `MINIO_ACCESS_KEY`: `"minioadmin"`
  * `MINIO_SECRET_KEY`: `"minioadmin"`
  * `MINIO_BUCKET`: `"voice-audio"`
  * `MINIO_SECURE`: `"false"`
  * `MINIO_PUBLIC_ENDPOINT`: `"http://<your-minio-console-url>:9001"` (browser-accessible URL for presigned URLs)
  * `OLLAMA_HOST`: `"http://127.0.0.1:11434"`
  * `GEMINI_API_KEY`: `"<gemini-api-key>"`
  * `DEEPGRAM_API_KEY`: `"<deepgram-api-key>"`
* **Dependencies**:
  * Set `postgres` container dependency $\rightarrow$ condition `START`
  * Set `redis` container dependency $\rightarrow$ condition `START`

#### 2. `ari-manager` (Telephony Bridge)
* **Image**: Same as above (`dograh-api`)
* **Command**: `python,-m,api.services.telephony.ari_manager`
* **Environment Variables**: Same Database, Redis, API keys, and **MINIO_PUBLIC_ENDPOINT**.

#### 3. `campaign-orchestrator` (Outbound Engine)
* **Image**: Same as above (`dograh-api`)
* **Command**: `python,-m,api.services.campaign.campaign_orchestrator`
* **Environment Variables**: Same Database, Redis, API keys, and **MINIO_PUBLIC_ENDPOINT**.

#### 4. `arq-worker` (Background Queue)
* **Image**: Same as above (`dograh-api`)
* **Command**: `python,-m,arq,api.tasks.arq.WorkerSettings,--custom-log-dict,api.tasks.arq.LOG_CONFIG`
* **Environment Variables**: Same Database, Redis, API keys, and **MINIO_PUBLIC_ENDPOINT**.

#### 5. `postgres` (Local Database Container)
* **Image**: `pgvector/pgvector:pg17`
* **Port Mapping**: None required (uses localhost)
* **Environment Variables**:
  * `POSTGRES_USER`: `postgres`
  * `POSTGRES_PASSWORD`: `postgres`
  * `POSTGRES_DB`: `postgres`

#### 6. `redis` (Local Cache Container)
* **Image**: `redis:7`
* **Port Mapping**: None required (uses localhost)
* **Command**: `--requirepass,redissecret`

#### 7. `minio` (Local Audio Storage Container)
* **Image**: `minio/minio`
* **Port Mapping**: None required (uses localhost)
* **Command**: `server,/data,--console-address,:9001`
* **Environment Variables**:
  * `MINIO_ROOT_USER`: `minioadmin`
  * `MINIO_ROOT_PASSWORD`: `minioadmin`
  * `MINIO_API_CORS_ALLOW_ORIGIN`: `"*"`
* **Important**: The `MINIO_PUBLIC_ENDPOINT` environment variable in the `api` container must be set to the MinIO console URL (port 9001) that's accessible from the browser. This is used for generating presigned URLs for document uploads.

#### 8. `ollama` (Local Embeddings Container)
* **Image**: `ollama/ollama:latest`
* **Port Mapping**: None required (uses localhost)
* **Volumes**: Configure one of the following based on your needs:
  * **Empty Volume (Simple)**: Use Docker-managed volume for temporary storage
  * **EFS Volume (Persistent)**: Use Amazon EFS for persistent model storage across task restarts
* **Environment Variables**: None required
* **Mount Points**:
  * **Source Volume**: `ollama_models` (empty or EFS volume)
  * **Container Path**: `/root/.ollama`
  * **Read Only**: `false`
* **Dependencies**: None required

**Important**: The `ollama` container must run before `ollama-init` to ensure the model storage volume is ready. The `ollama-init` container must mount the same volume as the `ollama` container to pull models into persistent storage.

**Empty Volume Configuration (Fargate):**
```json
"volumes": [
  {
    "name": "ollama_models",
    "host": {}
  }
]
```

**EFS Volume Configuration (Recommended for Production):**
```json
"volumes": [
  {
    "name": "ollama_models",
    "efsVolumeConfiguration": {
      "fileSystemId": "fs-xxxxxxxx",
      "rootDirectory": "/",
      "transitEncryption": "ENABLED"
     }
   }
 ]
 ```

#### 9. `ollama-init` (Model Initialization Container)
* **Image**: `ollama/ollama:latest`
* **Entry Point**: `sh -c "sleep 5 && ollama pull nomic-embed-text"`
* **Environment Variables**:
  * `OLLAMA_HOST`: `http://ollama:11434` (Docker service name for internal communication)
* **Mount Points**: Same volume as `ollama` container to share models
  * **Source Volume**: `ollama_models` (must match ollama container's volume)
  * **Container Path**: `/root/.ollama`
  * **Read Only**: `false`
* **Dependencies**: Must depend on `ollama` container with condition `START`

**Important**: The `ollama-init` container must use the same volume configuration as the `ollama` container. If using EFS, ensure the `fileSystemId` matches the EFS volume configured for the `ollama` container.

**Note**: The `ollama-init` container must share the same volume as the `ollama` container to pull models into persistent storage. Use the same volume configuration as the main `ollama` container.

---

### Task Definition 2: Frontend Dashboard (UI)
* **Image**: `<aws-account-id>.dkr.ecr.<aws-region>.amazonaws.com/dograh-ui:latest`
* **Port Mapping**: Container Port `3010` (TCP)
* **Environment Variables**:
  * `NODE_ENV`: `"production"`
  * `BACKEND_URL`: `"https://api.yourdomain.com"` (Your public backend URL)
  * `NEXT_PUBLIC_NODE_ENV`: `"oss"`
  * `NEXT_TELEMETRY_DISABLED`: `"1"`

---

## 🚀 Step 4: Run the ECS Services

Create an ECS Cluster and start two Fargate Services:

1. **Service 1: Dograh Backend**
   * **Task Definition**: Task Definition 1 (Backend Stack)
   * **Desired Tasks**: `2` (for high availability)
   * **Security Group**: Allow TCP port `8000` inbound from the ALB Security Group.
   * **Load Balancer Routing**: Link container `api` (port 8000) to Target Group 1 (API).

2. **Service 2: Dograh UI**
   * **Task Definition**: Task Definition 2 (UI)
   * **Desired Tasks**: `2`
   * **Security Group**: Allow TCP port `3010` inbound from the ALB Security Group.
   * **Load Balancer Routing**: Link container `ui` (port 3010) to Target Group 2 (UI).

---

## 🔄 Step 6: Configure Embedding Service (Optional - Ollama)

If using Ollama for local embeddings (instead of OpenAI/Google):

1. After ECS services are running, access the Model Configurations page
2. Configure Embeddings with:
   * **Provider**: Self-Hosted
   * **Base URL**: `http://ollama:11434` (or your Ollama endpoint)
   * **Model**: `nomic-embed-text`
   * **API Key**: Any dummy value (Ollama doesn't require API keys for local access)

## 🔄 Step 7: Update Vobiz XML Settings

Once the services are active and healthy behind the ALB, update your **Vobiz Applications** settings to point to your new production domains:

* **Answer URL**: `https://api.yourdomain.com/api/v1/telephony/inbound/{workflow_id}`
* **Hangup URL**: `https://api.yourdomain.com/api/v1/telephony/vobiz/hangup-callback/workflow/{workflow_id}`
* **Fallback Answer URL**: `https://api.yourdomain.com/api/v1/telephony/inbound/fallback`

Now, when a caller dials your Vobiz number, Vobiz will safely direct HTTPS traffic to your Application Load Balancer, routing the call through your secure, production-grade AWS ECS cluster.

---

## 🚨 Troubleshooting

### Document Upload Fails with "Failed to Fetch" or "ERR_CONNECTION_REFUSED"

**Symptoms:**
- Browser console shows: `Failed to load resource: net::ERR_CONNECTION_REFUSED`
- Document upload fails even though the backend health checks pass
- Logs show: `Generated unsigned upload URL: http://127.0.0.1:9000/...`

**Root Cause:**
The backend is generating presigned URLs using `127.0.0.1:9000` (internal container address), but these URLs need to be accessible from the browser. The browser cannot reach `127.0.0.1:9000` inside the ECS container.

**Solution:**
Set the `MINIO_PUBLIC_ENDPOINT` environment variable in the API task definition to a URL that's accessible from the browser:

```json
{
  "name": "MINIO_PUBLIC_ENDPOINT",
  "value": "http://<your-minio-console-url>:9001"
}
```

**Options for MINIO_PUBLIC_ENDPOINT:**

1. **Use MinIO Console URL (Port 9001)**: If you have a load balancer or direct access to MinIO console
2. **Use ALB Ingress**: Configure ALB to route `/minio/*` to the MinIO container
3. **Use CloudFront Distribution**: If you're using CloudFront, configure it to forward MinIO requests

**Note**: The `MINIO_ENDPOINT` (used for internal container-to-container communication) should remain `127.0.0.1:9000`, but `MINIO_PUBLIC_ENDPOINT` (used for generating URLs for the browser) must be accessible from outside the ECS cluster.

---

## 📌 Important Notes

### Ollama Volume Configuration
When deploying to AWS ECS, ensure both `ollama` and `ollama-init` containers use the **same volume** to share embedding models:

- **For Empty Volume**: Both containers use `"host": {}` with the same volume name `ollama_models`
- **For EFS Volume**: Both containers use the same `fileSystemId` and volume name `ollama_models`

If the volumes don't match, the `ollama-init` container will pull models into a separate, non-persistent volume, and the models won't be available to the main `ollama` container.
