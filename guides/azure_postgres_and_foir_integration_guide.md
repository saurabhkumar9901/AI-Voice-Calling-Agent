# Azure PostgreSQL Flexible Server, FOIR Service Integration, and Deployment Guide

This guide documents the complete end-to-end setup and migration process for Azure Database for PostgreSQL Flexible Server, `pgvector` extension activation, Azure Container Apps (ACA) secret propagation, automated database migrations, and FOIR tool-calling integration.

---

## Table of Contents
1. [Azure Database for PostgreSQL Flexible Server Provisioning](#1-azure-database-for-postgresql-flexible-server-provisioning)
2. [Enabling `pgvector` Extension](#2-enabling-pgvector-extension)
3. [Connection String & Azure Container Apps (ACA) Secrets](#3-connection-string--azure-container-apps-aca-secrets)
4. [Database Migrations & Container Startup](#4-database-migrations--container-startup)
5. [Verification, Container Teardown, and Storage Cleanup](#5-verification-container-teardown-and-storage-cleanup)
6. [FOIR Tool-Calling Integration & Prompting Best Practices](#6-foir-tool-calling-integration--prompting-best-practices)
7. [Transcript Diagnosis & Common Pitfalls](#7-transcript-diagnosis--common-pitfalls)

---

## 1. Azure Database for PostgreSQL Flexible Server Provisioning

### Target Infrastructure Specification
* **Server Name**: `enxtai`
* **Engine / Version**: PostgreSQL 17
* **Compute Tier**: Burstable `Standard_B1ms` (1 vCore, 2 GiB RAM — ~$12–$15/month for dev/unblock, upgradeable to General Purpose `GP_D2s_v3+` for production)
* **Storage**: 32 GB
* **Backup Retention**: 7 Days
* **Admin Username**: `dograhadmin`
* **Admin Password**: `Admin@123` *(Note: Percent-encode `@` as `%40` in connection URLs)*
* **Database**: `postgres`
* **Networking**: Public Access + Allow Access from Azure Services + Developer IP Firewall rule

### Deployment via Azure Portal
1. Navigate to **Azure Database for PostgreSQL flexible servers** in the Azure Portal.
2. Click **+ Create**.
3. Under **Basics**:
   * **Server Name**: `enxtai`
   * **PostgreSQL Version**: `17`
   * **Workload Type**: `Development` -> Select **Standard_B1ms** (Burstable).
   * **Storage**: `32 GB` | **Backup**: `7 days`.
   * **Admin User**: `dograhadmin` | **Password**: `Admin@123`
4. Under **Networking**:
   * **Connectivity**: `Public access (allowed IP addresses)`.
   * **Azure Access**: Check **Allow public access from any Azure service within Azure to this server**.
   * **Firewall Rules**: Add your local developer IP (`+ Add current client IP address`).
5. Click **Review + Create** -> **Create**.

### Deployment via Azure CLI
```bash
# 1. Provision PostgreSQL Server
az postgres flexible-server create \
  --resource-group rg-enxtai \
  --name enxtai \
  --location eastus \
  --version 17 \
  --sku-name Standard_B1ms \
  --tier Burstable \
  --storage-size 32 \
  --admin-user dograhadmin \
  --admin-password 'Admin@123' \
  --public-access AzureServices \
  --yes

# 2. Add Developer Public IP
az postgres flexible-server firewall-rule create \
  --resource-group rg-enxtai \
  --name enxtai \
  --rule-name AllowDevIP \
  --start-ip-address <YOUR_PUBLIC_IP> \
  --end-ip-address <YOUR_PUBLIC_IP>
```

---

## 2. Enabling `pgvector` Extension

`pgvector` must be allowlisted in server parameters before creating the extension in PostgreSQL.

### Step 1: Whitelist Extension in Azure
* **Portal**: Go to server `enxtai` -> **Settings** -> **Server parameters** -> Search `azure.extensions` -> Select **`VECTOR`** -> Save.
* **CLI**:
  ```bash
  az postgres flexible-server parameter set \
    --resource-group rg-enxtai \
    --server-name enxtai \
    --name azure.extensions \
    --value VECTOR
  ```

### Step 2: Initialize Extension in Database
Connect via `psql` or SQL editor:
```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- Verification
SELECT * FROM pg_extension WHERE extname = 'vector';
```

---

## 3. Connection String & Azure Container Apps (ACA) Secrets

Because special characters like `@` are present in `Admin@123`, the password must be percent-encoded as `Admin%40123`.

### Connection URL Formats
* **`asyncpg` (SQLAlchemy / FastAPI app runtime)**:
  `postgresql+asyncpg://dograhadmin:Admin%40123@enxtai.postgres.database.azure.com:5432/postgres?ssl=require`
* **`psycopg2` / Alembic / SQL Clients**:
  `postgresql://dograhadmin:Admin%40123@enxtai.postgres.database.azure.com:5432/postgres?sslmode=require`

### Configuring Secrets & Environment Variables in ACA
Deploy secret `db-url` and bind `DATABASE_URL=secretref:db-url` across all microservices (`api`, `ari-manager`, `campaign-orchestrator`, `arq-worker`):

```bash
RESOURCE_GROUP="rg-enxtai"
DB_URL="postgresql+asyncpg://dograhadmin:Admin%40123@enxtai.postgres.database.azure.com:5432/postgres?ssl=require"

for APP in api ari-manager campaign-orchestrator arq-worker; do
  echo "Updating secret and env var for $APP..."
  az containerapp secret set --name $APP --resource-group $RESOURCE_GROUP --secrets db-url="$DB_URL"
  az containerapp update --name $APP --resource-group $RESOURCE_GROUP --set-env-vars DATABASE_URL=secretref:db-url
done
```

---

## 4. Database Migrations & Container Startup

The `api` service automatically applies migrations before starting Uvicorn using the container command override:

```bash
sh -c "alembic -c api/alembic.ini upgrade head && uvicorn api.app:app --host 0.0.0.0 --port 8000"
```

### Manual Execution Options
* **Local Machine**:
  ```bash
  export DATABASE_URL="postgresql+asyncpg://dograhadmin:Admin%40123@enxtai.postgres.database.azure.com:5432/postgres?ssl=require"
  alembic -c api/alembic.ini upgrade head
  ```
* **ACA Console**: Execute inside the ACA container console for `api`.

---

## 5. Verification, Container Teardown, and Storage Cleanup

### 1. Verification
1. Test signup (`POST /auth/signup`) and login (`POST /auth/login`) endpoints.
2. Confirm `200 OK` response writing to `enxtai`.
3. Inspect `alembic_version` and table structure:
   ```sql
   SELECT * FROM alembic_version;
   \d knowledge_base_chunks; -- Verify embedding vector(1536) column
   ```

### 2. Teardown Old Postgres Container App
```bash
# 1. Scale down old postgres app to 0 to verify independence
az containerapp update --name postgres --resource-group rg-enxtai --min-replicas 0 --max-replicas 0

# 2. Restart API to ensure smooth transition
az containerapp revision restart --name api --resource-group rg-enxtai

# 3. Delete old postgres container app
az containerapp delete --name postgres --resource-group rg-enxtai --yes
```

### 3. Storage Account Cleanup
Do **NOT** mount SMB file shares for PostgreSQL (CIFS/SMB breaks POSIX file locking). Delete *only* the unused `postgres-data` share from `dograhstorage` while preserving application storage:

```bash
# Delete unused postgres-data share
az storage share delete --account-name dograhstorage --name postgres-data
```
> **Preserved File Shares**: `redis-data`, `minio-data`, `shared-tmp`.

---

## 6. FOIR Tool-Calling Integration & Prompting Best Practices

### Service Tool Schema (`foir-service/dograh-tool.json`)
When configuring FOIR calculation tools for voice agents, explicit units (**full INR amounts**) must be specified in the schema descriptions to prevent unit conversion errors (e.g. passing `5` instead of `500000`):

```json
{
  "name": "calculate_foir_eligibility",
  "description": "Calculate personal loan eligibility using 70% FOIR model. Call ONLY after net_monthly_income, existing_emi are LOCKED with explicit haan, and tenure_years (5/6/7) is known. Do not guess values.",
  "method": "POST",
  "url": "http://foir-service:8089/calculate-foir",
  "timeout_ms": 8000,
  "parameters": [
    {
      "name": "net_monthly_income",
      "type": "number",
      "description": "LOCKED net monthly salary/income in full Indian Rupees (e.g. 500000 for 5 lakh, 50000 for 50k)",
      "required": true
    },
    {
      "name": "existing_emi",
      "type": "number",
      "description": "LOCKED existing total EMI in full Indian Rupees (e.g. 50000 for 50k, 0 if none)",
      "required": true
    },
    {
      "name": "other_obligations",
      "type": "number",
      "description": "Other monthly obligations in full Indian Rupees, default 0",
      "required": false
    },
    {
      "name": "tenure_years",
      "type": "number",
      "description": "Loan tenure 5, 6 or 7. Ask customer. Default 6 since all banks offer up to 6 years.",
      "required": true
    }
  ]
}
```

### ACA Internal Networking for FOIR Service
When calling `foir-service` from other services inside the **same Azure Container Apps Environment**:
* Use internal HTTP endpoints: `http://foir-service/calculate-foir` (or `http://foir-service:8089/calculate-foir`).
* External `.internal.<env-id>.<region>.azurecontainerapps.io` URLs are private to the ACA VNet and will not resolve from local development machines without external ingress.

---

## 7. Transcript Diagnosis & Common Pitfalls

### Case Study: FOIR Calculation Discrepancy
In a test transcript:
* **User Input**: Income = ₹500,000 (5 Lakhs), Existing EMI = ₹50,000, Tenure = 6 Years.
* **Expected Result**: 
  * `max_total_emi` = 70% of 500,000 = ₹350,000
  * `available_emi` = 350,000 - 50,000 = **₹300,000** (3 Lakhs/month)
  * `max_loan` = (300,000 / 1903) * 100,000 = **₹15,764,582** (~157.6 Lakhs / 1.57 Crore)
* **Agent Response**: *"Maine check kiya hai teen lakh available par chhe saal mein lagbhag 157.6 lakh indicative ban raha hai..."*

### Diagnosis
The agent spoke **157.6 Lakhs** because the tool was called with `available_emi = 300,000` (from an income input of ₹350,000 or input confusion). While ₹300,000 available EMI correctly yields **157.6 Lakhs**, the input was incorrect for a ₹500,000 income profile.

### Lessons Learned
1. **Always specify full currency units in tool definitions** (`full Indian Rupees`, e.g. `500000`).
2. **System Prompt Constraint**: Require the LLM to strictly echo the `message` string returned by `foir-service` response rather than re-interpreting or recalculating numbers in prose.
