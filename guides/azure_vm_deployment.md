# Deploying Dograh on an Azure Virtual Machine (EC2-equivalent)

This is the **Azure IaaS** path: one Azure VM running the whole Docker Compose
stack. It is the Azure equivalent of an AWS EC2 instance — no Container Apps, no
managed Kubernetes, no App Service.

It follows the same shape as [oci_deployment_guide.md](./oci_deployment_guide.md)
(Path A) and [aws_ecs_deployment_guide.md](./aws_ecs_deployment_guide.md), with
the Azure-specific pieces swapped in:

| Concern | This guide (Azure VM) |
|---|---|
| Firewall | **NSG** (stateful, no return rules needed) |
| Host user | `azureuser` (Azure Ubuntu default) |
| Public address | Standard-SKU **static** public IP, 1:1 NAT to the NIC |
| TLS / ingress | **ngrok** static domain (no DNS, no certificate) |
| Database | `pgvector` in a container, `postgres_data` volume |
| Autoscaling | none — scale the VM **up**, never out |

Nothing in `api/`, `ui/` or `foir-service/` changes for this deployment.

---

## 1. What you are deploying

```mermaid
graph LR
    B["Browser / phone provider"] -->|"HTTPS"| NG["ngrok edge<br/>name.ngrok-free.dev"]
    NG -->|"outbound tunnel"| AG["ngrok agent on VM<br/>(systemd)"]
    AG --> NX["nginx<br/>127.0.0.1:8080"]
    NX -->|"/"| UI["ui :3010<br/>(host 127.0.0.1:3000)"]
    UI -->|"/api/* + WebSockets (Next rewrite)"| API["api :8000"]
    NX -->|"/voice-audio/"| MINIO["minio / SILO :9000"]
    B -.->|"WebRTC audio, UDP 3478 + 49152-49200"| CT["coturn<br/>(host network)"]

    API --> PG["postgres pgvector :5432"]
    API --> RD["redis :6379"]
    API --> MINIO
    API -->|"TURN REST credentials"| CT
    ARQ["arq-worker"] --> PG
    ARQ --> RD
    ARQ --> MINIO
```

| Service | Image | Published on host | Persistence |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | internal only | `postgres_data` volume |
| `redis` | `redis:7` | internal only | `redis_data` volume |
| `minio` | `pgsty/silo:latest` | `127.0.0.1:9000/9001` | `minio_data` volume |
| `api` | built from `api/Dockerfile` | `127.0.0.1:8000` | `shared-tmp` volume |
| `ari-manager` | same image as `api` | none | — |
| `campaign-orchestrator` | same image as `api` | none | — |
| `arq-worker` | same image as `api` | none | `shared-tmp` volume |
| `ui` | built from `ui/Dockerfile` | `127.0.0.1:3000` | none |
| `foir-service` | built from `foir-service/Dockerfile` | none (internal) | — |
| `nginx` | `nginx:alpine` | `127.0.0.1:8080` | `nginx/ngrok.conf` |
| `coturn` | `coturn/coturn:4.8.0` | **host network**, public UDP | `turnserver.conf` |

Facts that shape this guide:

- The OSS `api` container runs **one uvicorn process** and keeps live calls and
  WebRTC sessions **in memory**. Never run more than one `api` replica behind a
  round-robin load balancer. Scale the VM vertically instead.
- **HTTPS is mandatory.** Browsers only grant microphone access
  (`getUserMedia`) on a secure origin. ngrok provides that without a domain.
- **UDP must reach coturn.** Without `3478` and `49152-49200/udp`, calls connect
  with no audio on mobile/corporate networks.
- **`minio/minio` is not anonymously pullable anymore** (Docker Hub 404, Quay
  needs AIStor credentials). This deployment uses **SILO** (`pgsty/silo`), the
  maintained fork — same entrypoint, `MINIO_*` env vars, `/minio/*` health
  routes and on-disk format.
- Migrations run automatically when `api` starts (`alembic upgrade head`, which
  also creates the `vector` extension). No manual SQL.
- The API creates the `voice-audio` bucket with an **anonymous read/write
  policy** so unsigned browser upload/download URLs work. It is reachable only
  through nginx `/voice-audio/`; never expose port 9000.

---

## Fast path (TL;DR)

For readers who already know the stack — details in the referenced sections:

1. Create `rg-dograh` and `dograh-nsg` with **22 (your IP)**, **3478 TCP+UDP**,
   **49152-49200 UDP** — §3
2. Create a `Standard_D4s_v5` Ubuntu 24.04 VM with a **static** public IP,
   128 GiB Premium SSD, and `guides/azure/cloud-init.sh` as custom data — §4
3. `git clone` the fork, `scp api/.env`, write the root `.env` and
   `turnserver.conf` — §5
4. Install ngrok, bind your static domain, `ngrok service install` + `start` — §6
5. `docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml up -d --build` — §7
6. Verify `/api/v1/health`, run a web call, reboot once — §8, §9

---

## 2. Sizing, region and cost

| Item | Recommendation |
|---|---|
| Image | **Ubuntu 24.04 LTS** (x64). `Canonical:ubuntu-24_04-lts:server:latest` |
| Size (production calls) | **`Standard_D4s_v5`** — 4 vCPU / 16 GB |
| Size (dev / demo) | **`Standard_B4ms`** — 4 vCPU / 16 GB burstable |
| Avoid | `Standard_B2s` (2 vCPU / 4 GB) — OOMs during the API build and on first model load |
| OS disk | **128 GiB Premium SSD** (P10). Use 256 GiB if you expect long recordings |
| Data disk (optional) | 128 GiB Premium SSD mounted at `/var/lib/docker` (see cloud-init) |
| Public IP | **Standard SKU, Static** (Standard SKUs are static-only) |
| Region | Closest to your users **and** your telephony provider |

Why not the smallest size: the `api` image compiles/downloads CPU torch and
pipecat, and the ARQ worker loads a ~1 GB sentiment model into memory. 8 GB is
workable but tight; 4 GB will fail.

> **Burstable (`B`-series) caveat.** Voice pipelines are latency-sensitive and
> CPU-hungry. B-series runs on CPU credits and will throttle after sustained
> load, which shows up as choppy or delayed call audio. `B4ms` is fine for
> testing and short demos; use `D4s_v5` for real traffic.

Approximate monthly cost (pay-as-you-go, Central India — **verify with the
[Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/)**):

| Resource | Spec | ~USD/month |
|---|---|---|
| VM `Standard_B4ms` | 4 vCPU / 16 GB | ~$70 |
| VM `Standard_D4s_v5` | 4 vCPU / 16 GB | ~$170 |
| OS disk | 128 GiB Premium SSD (P10) | ~$20 |
| Static public IP | Standard SKU | ~$4 |
| Egress | first 100 GB/month free, then ~$0.09/GB | varies |
| **Total** | B4ms / D4s_v5 | **~$95 / ~$195** |

Notes:

- Azure bills Premium SSD by **tier**, not by provisioned GiB. 150 GiB falls into
  the 256 GiB tier, so prefer 128 GiB or go all the way to 256 GiB.
- Reserved instances (1-year) cut the VM line by roughly 40%.
- Phone-call audio streams through ngrok and counts as egress; browser WebRTC
  audio does not (it goes directly over TURN).

---

## 3. Network and NSG

Create these first (Portal or CLI). The default VNet/subnet Azure offers during
VM creation is fine.

```bash
RESOURCE_GROUP=rg-dograh
LOCATION=centralindia

az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

az network nsg create --resource-group "$RESOURCE_GROUP" --name dograh-nsg

# SSH - restrict to your own IP
MY_IP=$(curl -4 -s https://ifconfig.me)
az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name dograh-nsg \
  --name Allow-SSH --priority 1000 --protocol Tcp --destination-port-ranges 22 \
  --source-address-prefixes "${MY_IP}/32" --access Allow

# TURN (signaling + relay)
az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name dograh-nsg \
  --name Allow-TURN --priority 1030 --protocol '*' --destination-port-ranges 3478 \
  --source-address-prefixes '*' --access Allow

az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name dograh-nsg \
  --name Allow-TURN-Relay --priority 1040 --protocol Udp \
  --destination-port-ranges 49152-49200 --source-address-prefixes '*' --access Allow
```

Resulting rule set:

| Priority | Name | Source | Port | Why |
|---|---|---|---|---|
| 1000 | `Allow-SSH` | your IP | TCP 22 | administration |
| 1030 | `Allow-TURN` | any | TCP+UDP 3478 | TURN signaling |
| 1040 | `Allow-TURN-Relay` | any | UDP 49152-49200 | TURN media relay |

**Do not open** 5432, 6379, 8000, 8080, 9000, 9001 or 3010. With the ngrok
variant, the UI is served through an outbound tunnel — ports 80/443 are not
needed either. Add them only if you later switch to a custom domain (section 14).

> Azure NSGs are **stateful**: return traffic for allowed inbound flows is
> automatic, and all outbound traffic is allowed by default. That outbound
> access is required for ngrok, Hugging Face model downloads and LLM/TTS APIs.

---

## 4. Launch the VM

### Portal

1. **Virtual machines → Create → Azure virtual machine**.
2. **Basics**
   - Resource group: `rg-dograh`
   - Name: `dograh`
   - Region: `Central India` (or nearest)
   - Image: **Ubuntu Server 24.04 LTS - x64 Gen2**
   - Size: `Standard_D4s_v5` (or `B4ms`)
   - Authentication: **SSH public key** → your key
   - Username: `azureuser`
3. **Disks** — OS disk **Premium SSD**, size **128 GiB**. Delete-with-VM: **off**.
   *(Optional: add a 128 GiB data disk for `/var/lib/docker`.)*
4. **Networking**
   - Virtual network/subnet: default
   - Public IP: **Create new → Standard SKU → Static**
   - NIC network security group: **Advanced → `dograh-nsg`**
   - Delete public IP and NIC when VM is deleted: **off**
5. **Advanced → Custom data** — paste the contents of
   [`guides/azure/cloud-init.sh`](azure/cloud-init.sh).
   *(The Portal field is limited to ~64 KB; this script is well under that.)*
6. **Review + create**.

### CLI equivalent

```bash
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name dograh \
  --location "$LOCATION" \
  --image Canonical:ubuntu-24_04-lts:server:latest \
  --size Standard_D4s_v5 \
  --admin-username azureuser \
  --ssh-key-values ~/.ssh/id_ed25519.pub \
  --os-disk-size-gb 128 \
  --storage-sku Premium_LRS \
  --public-ip-sku Standard \
  --nsg dograh-nsg \
  --custom-data guides/azure/cloud-init.sh

# Static public IP (Standard SKU is static by default; confirm):
az network public-ip show --resource-group "$RESOURCE_GROUP" \
  --name dograhPublicIP --query "{ip:ipAddress, alloc:publicIPAllocationMethod}" -o table
```

`az vm create` prints `publicIpAddress`. Note it down — **it must never
change**, because coturn advertises it and ngrok/telephony webhooks depend on
it. Static allocation guarantees that across stop/deallocate.

> **Quota check.** New subscriptions often have 0 vCPUs for `Dsv5` families in a
> region. If creation fails with `OperationNotAllowed`, run
> `az vm list-usage --location "$LOCATION" -o table`, then either pick another
> size/region or request a quota increase. Burstable `B`-series sizes usually
> have more headroom.

> **Do not use Azure Spot** for this workload. Eviction mid-call drops live
> calls and, with a static IP bound to a Spot VM, can leave the address
> unavailable.

### Verify host prep

```bash
ssh azureuser@<public-ip>

docker --version && docker compose version    # compose must be v2.24.4+
sudo swapon --show                            # 4G /swapfile
nproc && free -h                              # 4 CPUs / ~16 GB
df -h /                                       # ~120 GB free
```

If Docker is missing or cloud-init failed, check
`sudo tail -100 /var/log/cloud-init-output.log`, then copy the script up and run
it manually:

```bash
# from your workstation, in the repo root
scp guides/azure/cloud-init.sh azureuser@<public-ip>:~/

# on the VM
sudo bash ~/cloud-init.sh
```

---

## 5. Get the code and secrets onto the VM

The compose stack needs **three** things that are not in git: `api/.env`, a
root `.env`, and `turnserver.conf`.

### 5.1 Clone the fork

```bash
cd ~
git clone https://github.com/saurabhkumar9901/AI-Voice-Calling-Agent.git
cd ~/AI-Voice-Calling-Agent
```

`pipecat/` is committed as normal files in this fork, so `--recursive` is **not**
needed. For a private repo, use a GitHub Personal Access Token as the password.

The compose project name is derived from the folder, so the Docker network is
`ai-voice-calling-agent_app-network`.

### 5.2 Copy `api/.env`

From your workstation (PowerShell):

```powershell
scp "D:\dograh 19-08\dograh\api\.env" azureuser@<public-ip>:~/AI-Voice-Calling-Agent/api/.env
```

Then on the VM, add the JWT secret if it is not already there:

```bash
cd ~/AI-Voice-Calling-Agent
grep -qE '^OSS_JWT_SECRET=.+' api/.env || echo "OSS_JWT_SECRET=$(openssl rand -hex 32)" >> api/.env
```

| Variable in `api/.env` | What to do |
|---|---|
| `BACKEND_API_ENDPOINT` | leave as-is — the override sets it to `PUBLIC_URL` |
| `TURN_HOST=localhost` | leave as-is — overridden to `PUBLIC_IP` |
| `DATABASE_URL`, `REDIS_URL`, `MINIO_ENDPOINT` (`localhost`) | leave as-is — overridden by compose `environment:` |
| `UI_APP_URL` | leave as-is — overridden to `PUBLIC_URL` |
| Provider keys (Gemini, etc.) | keep — the API containers load them |
| `OSS_JWT_SECRET` | **must be set**; the code default is public, so tokens could be forged |

`environment:` in compose always wins over `env_file:`, which is why the
`localhost` values are harmless here.

### 5.3 Create the root `.env` and `turnserver.conf`

Both live in the repo root on the VM, next to `docker-compose-ecs.yaml`, and both
are gitignored. Replace the ngrok domain with your own (section 6).

```bash
cd ~/AI-Voice-Calling-Agent

cat > .env <<EOF
PUBLIC_URL=https://<your-name>.ngrok-free.dev
PUBLIC_IP=$(curl -4 -s https://ifconfig.me)
PRIVATE_IP=$(ip -4 route get 1.1.1.1 | awk '{print $7}')
TURN_SECRET=$(openssl rand -hex 32)
EOF
chmod 600 .env
set -a; . ./.env; set +a

cat > turnserver.conf <<TURN
listening-port=3478
min-port=49152
max-port=49200
external-ip=${PUBLIC_IP}/${PRIVATE_IP}
relay-ip=${PRIVATE_IP}
realm=dograh
use-auth-secret
static-auth-secret=${TURN_SECRET}
fingerprint
no-tls
no-dtls
no-cli
no-multicast-peers
log-file=stdout
TURN

cat .env          # PUBLIC_IP = static public IP, PRIVATE_IP = 10.x.x.x
ls -la .env turnserver.conf   # both must exist
```

If `ifconfig.me` is blocked, read the public address from Azure's metadata
service instead (no internet needed):

```bash
curl -s -H Metadata:true \
  "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text"
```

**Why `external-ip=PUBLIC/PRIVATE` matters on Azure:** the VM's NIC only sees
its **private** address; the public IP is 1:1 NAT in the Azure fabric. Without
the mapping, coturn advertises the private address and remote peers cannot reach
the relay — calls connect but carry no audio.

Do not regenerate `TURN_SECRET` casually: if you do, regenerate
`turnserver.conf` as well and recreate the stack.

---

## 6. Set up ngrok (HTTPS without a domain)

ngrok makes an **outbound** connection, so no inbound ports are needed and no
certificate has to be managed.

1. Create a free account at [dashboard.ngrok.com](https://dashboard.ngrok.com).
2. Copy your **authtoken**.
3. Claim a **static domain** under *Universal Gateway → Domains* (the free plan
   includes one, e.g. `your-name.ngrok-free.dev`).
4. Put that domain in the root `.env` as `PUBLIC_URL` (section 5.3).

Install the agent:

```bash
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
  | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
# ngrok's repo is distro-agnostic; the codename is only a label.
echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
  | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt-get update && sudo apt-get install -y ngrok

ngrok config add-authtoken <your-authtoken>
```

### Run it as a service (survives reboots)

Do **not** use a bare `tmux` session as the long-term setup — it does not come
back after a reboot. Write the tunnel into the agent config instead:

```bash
mkdir -p ~/.config/ngrok

# Load PUBLIC_URL from the root .env written in section 5.3
cd ~/AI-Voice-Calling-Agent
set -a; . ./.env; set +a

cat > ~/.config/ngrok/ngrok.yml <<EOF
version: 3
agent:
  authtoken: <your-authtoken>
endpoints:
  - name: dograh
    url: ${PUBLIC_URL}
    upstream:
      url: 8080
EOF

sudo ngrok service install --config /home/azureuser/.config/ngrok/ngrok.yml
sudo ngrok service start
systemctl status ngrok --no-pager
```

Expected: `Session Status online`, forwarding your static domain to
`http://localhost:8080`.

> If you already have ngrok running **on your PC** with the same static domain,
> stop it first — one static domain can only be online from one agent at a time.

### Why the override file is required

`docker-compose-ecs.yaml` was written for AWS ECS, where TLS, the load balancer
and secret injection come from AWS. On a bare VM it has these gaps, which
[`docker-compose.ngrok.yaml`](../docker-compose.ngrok.yaml) closes without
editing the ECS file:

| Gap in `docker-compose-ecs.yaml` | Effect on a VM | Fixed by |
|---|---|---|
| No HTTPS (UI on plain `:3000`) | Browsers block the microphone on `http://`, so test calls fail | ngrok TLS |
| No coturn | VM only knows its private `10.x` address → calls with **no audio** | `coturn` service |
| UI `BACKEND_URL: http://api:8000` | Browser gets an unreachable backend and falls back to `http://localhost:8000` | `BACKEND_URL=${PUBLIC_URL}` |
| `MINIO_PUBLIC_ENDPOINT: localhost:9000` | Uploads and recording playback break for remote users | nginx `/voice-audio/` + `sub_filter` |
| 8000/9000/9001/3000 published on all interfaces | Docker bypasses the host firewall | rebound to `127.0.0.1` |
| No `restart:` policy | Containers stay down after a crash or reboot | `restart: unless-stopped` |
| `pgsty/minio` image | Renamed upstream | `pgsty/silo` |
| `TURN_HOST=localhost` | API tells browsers to use a TURN server **on the visitor's PC** | `TURN_HOST=${PUBLIC_IP}` |

---

## 7. Build and start the stack

```bash
cd ~/AI-Voice-Calling-Agent
docker compose version        # v2.24.4+ required for !override

D="docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml"
$D up -d --build
$D ps
```

- The first build takes **15–30 minutes** on x64 (CPU torch, pipecat, Next.js).
  Follow it from a second SSH session with `$D logs -f api`.
- `api` runs migrations on start and has a 180 s healthcheck `start_period`, so
  it shows `starting` for up to ~3 minutes.
- `ui` waits for `api` to be healthy; `nginx` waits for `ui` and `minio`.
- `api` and `arq-worker` share the `shared-tmp` volume. That is what allows call
  recordings, transcripts and summaries to work: `api` writes temp files at call
  end, `arq-worker` reads them back to upload to object storage. Do not remove
  it.

**Always pass both `-f` files, in that order**, for every compose command
(`ps`, `logs`, `restart`, `down`, ...). The `D=` alias above saves typing.

If Compose rejects the files with `unknown shorthand flag: 'f'`, the Compose v2
plugin is missing — re-run `guides/azure/cloud-init.sh` or install
`docker-compose-plugin` from Docker's apt repo.

---

## 8. Verify

```bash
# On the VM, layer by layer
D="docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml"
set -a; . ./.env; set +a

$D ps                                        # api healthy; ui/nginx/coturn running
curl -s  localhost:8000/api/v1/health        # API  -> JSON
curl -sI localhost:3000 | head -1            # UI   -> HTTP/1.1 200
curl -sI localhost:8080 | head -1            # nginx-> HTTP/1.1 200

# Through the tunnel
curl -fsS "${PUBLIC_URL}/api/v1/health"
curl -fsSI "${PUBLIC_URL}" | head -1
```

Then open `${PUBLIC_URL}` from any device (mobile data is the honest test):

1. Free ngrok shows a **"You are about to visit…"** interstitial once — click
   **Visit Site**. Telephony webhooks are unaffected.
2. **Sign up** — creates the first local OSS account on the VM.
3. **Model Configurations** — add your LLM / STT / TTS provider keys.
4. Open an agent and run a **web call**; allow the microphone.
5. Upload a document and play back a recording to exercise `/voice-audio/`.
6. For Vobiz / Twilio / Cloudonix, point the provider webhook at `${PUBLIC_URL}`.

---

## 9. Start on boot

Two independent pieces:

| Component | After a VM reboot |
|---|---|
| Docker containers | Restart automatically (`restart: unless-stopped`) |
| ngrok agent | Restarts automatically (`ngrok service` + `systemctl enable`) |

Confirm:

```bash
D="docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml"

sudo systemctl is-enabled docker ngrok
sudo reboot
# ... reconnect
cd ~/AI-Voice-Calling-Agent
$D ps
systemctl status ngrok --no-pager
```

---

## 10. Operate

```bash
D="docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml"

$D logs -f --tail=100 api
$D logs --tail=50 ui nginx coturn arq-worker
$D restart api
$D up -d --force-recreate api ari-manager campaign-orchestrator arq-worker   # after editing api/.env
```

**Update to the latest code from your fork**

```bash
cd ~/AI-Voice-Calling-Agent
git pull
$D up -d --build
docker image prune -f
```

The root `.env`, `turnserver.conf` and `api/.env` are gitignored, so `git pull`
never overwrites them.

**Disk** — builds are large. The `api` image alone is several GB.

```bash
df -h / ; docker system df
docker builder prune -f
docker image prune -f
```

**Azure-side operations**

```bash
# Stop billing when idle (static IP is retained; containers resume on start)
az vm deallocate --resource-group rg-dograh --name dograh

# Console output, in case SSH is unreachable
az vm boot-diagnostics get-boot-log --resource-group rg-dograh --name dograh

# Run a command without SSH
az vm run-command invoke --resource-group rg-dograh --name dograh \
  --command-id RunShellScript --scripts "cd /home/azureuser/AI-Voice-Calling-Agent && docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml ps"
```

> Deallocating stops compute billing but keeps the disk (and the static IP)
> billed. A **stopped (not deallocated)** VM still bills compute — always
> deallocate.

---

## 11. Backups

Nothing here is managed for you. Minimum viable setup:

1. **Nightly logical Postgres dump**, kept off the VM:

   ```bash
   mkdir -p ~/backups
   cat > ~/backups/dograh-backup.sh <<'SH'
   #!/bin/bash
   set -euo pipefail
   cd /home/azureuser/AI-Voice-Calling-Agent
   D="docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml"
   $D exec -T postgres pg_dump -U postgres postgres | gzip > ~/backups/dograh-$(date +%F).sql.gz
   find ~/backups -name 'dograh-*.sql.gz' -mtime +14 -delete
   SH
   chmod +x ~/backups/dograh-backup.sh
   (crontab -l 2>/dev/null; echo "15 2 * * * /home/azureuser/backups/dograh-backup.sh") | crontab -
   ```

   Then copy `~/backups` off the VM (Azure Files mount, `az storage blob upload`,
   or `scp`) — a backup on the same disk is not a backup.

2. **Disk snapshots / Azure Backup** on the OS disk. The `minio_data` volume
   (call audio) lives there. Enable **Azure Backup** for the VM, or schedule
   snapshots:

   ```bash
   az snapshot create --resource-group rg-dograh --name dograh-$(date +%F) \
     --source <os-disk-resource-id>
   ```

3. **Back up `.env`, `turnserver.conf` and `api/.env`** to your password
   manager. They hold the only copies of the TURN secret, JWT secret and
   provider keys.

4. **Test a restore** before you need it.

---

## 12. Hardening checklist

- [ ] Rotate defaults: `OSS_JWT_SECRET` (via `api/.env`) plus the DB/Redis/MinIO
      passwords, which are hardcoded in `docker-compose-ecs.yaml`
      (`postgres`/`redissecret`/`minioadmin` are public knowledge). Changing a
      password means editing **every** service that references it **and**
      recreating the volume it belongs to, or the existing data will reject the
      new credentials.
- [ ] SSH limited to your IP in the NSG; key-only auth (no password).
- [ ] NSG allows only 22 + 3478 + 49152-49200; verify nothing else answers from
      the internet:

      ```bash
      # sudo apt-get install -y nmap   (or use an online port checker)
      nmap -Pn -p 22,80,443,3000,3010,5432,6379,8000,8080,9000,9001 <public-ip>
      ```

- [ ] `8000`/`3000`/`9000`/`9001`/`8080` bound to `127.0.0.1` (the ngrok
      override does this) — confirm with `ss -lntp`.
- [ ] `ENABLE_TELEMETRY=false` if you later switch to the upstream
      `docker-compose.yaml` (the ECS-based stack in this guide does not send
      telemetry).
- [ ] Azure Defender / Microsoft Defender for Cloud enabled on the subscription.
- [ ] `unattended-upgrades` enabled for OS security patches.
- [ ] Uptime check on `${PUBLIC_URL}/api/v1/health` (Azure Monitor or any
      external prober).
- [ ] Disk alert at 80% — full disks break Postgres and the Docker builder.
- [ ] `/voice-audio/` exposed only through nginx (the bucket policy is anonymous
      read/write by design).
- [ ] Never run more than one `api` replica.

---

## 13. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Permission denied (publickey)` on SSH | Wrong user | Azure Ubuntu user is **`azureuser`**, not `ubuntu` |
| `docker: permission denied while trying to connect` | Group not applied to current shell | `newgrp docker` or log out/in |
| `unknown shorthand flag: 'f' in -f` | Compose v2 plugin missing | Install `docker-compose-plugin`; re-run cloud-init |
| `!override` / `!reset` parse error | Compose older than v2.24.4 | Upgrade the Compose plugin |
| `dial tcp: lookup minio ... no such host` | Stack started with only one `-f` file | Always pass **both** files, in order |
| `docker pull minio/minio` → 404 / unauthorized | Community image is no longer public | Use `pgsty/silo`, already set in `docker-compose.ngrok.yaml` |
| Site loads, **microphone blocked** | Origin is not HTTPS or cert is untrusted | Use the ngrok `https://` URL, not `http://<ip>:3000` |
| `ERR_NGROK_3200` | ngrok agent not running / wrong domain | `systemctl status ngrok`; ensure only one agent owns the domain |
| ngrok interstitial every visit | Free plan behavior | Click through, or use a paid plan / custom domain |
| Calls connect, **no audio** | UDP blocked | Open 3478 TCP+UDP and 49152-49200 UDP in the **NSG**; check `turnserver.conf` has `external-ip=PUBLIC/PRIVATE` |
| One-way audio only on mobile/corporate networks | TURN relay not reachable | Same as above; verify `relay-ip` is the private `10.x` address |
| Call ends with **no recording/transcript/summary** | `shared-tmp` volume missing on `api` or `arq-worker` | Restore the `shared-tmp:/tmp` mounts; recreate both services |
| `api` restarts / OOM-killed | Too little RAM, model load | Use 16 GB; confirm swap with `swapon --show` |
| Build fails: `no space left on device` | Disk too small | 128 GiB minimum; `docker builder prune -f`; or attach a data disk |
| First sentiment classification hangs ~1–2 min | ARQ worker downloads ~1 GB weights from Hugging Face | Ensure outbound egress; wait once after deploy |
| Recording playback 404s | `HTTP://localhost:9000` URLs not rewritten | Use the stack through **nginx/ngrok**, not direct `:3000` |
| Webhooks from telephony never arrive | `BACKEND_API_ENDPOINT` still points at an old URL | Set `PUBLIC_URL` in the root `.env`, then recreate the API-image services |
| VM unreachable after a firewall change | ufw enabled with no SSH rule | Use Azure **Serial console** / `az vm run-command` to fix ufw |
| `OperationNotAllowed` creating the VM | vCPU quota for that family/region | Check `az vm list-usage`, change size/region, or request quota |

---

## 14. Optional next steps

**Custom domain instead of ngrok.** Add ports 80/443 to the NSG, point a DNS
`A` record at the static IP, and terminate TLS with nginx + Let's Encrypt.
[oci_deployment_guide.md § Variant 2](oci_deployment_guide.md) has the full
recipe (nginx template, certbot, renewal deploy hook). Two caveats:

- That variant pulls **upstream** `ghcr.io/dograh-hq` images, which do not
  include this fork's changes (`foir-service`, modified API/UI). Keep building
  your own images and drop the stock-image assumption, or layer the same
  nginx/certbot config on top of `docker-compose-ecs.yaml`.
- `BACKEND_API_ENDPOINT`, `UI_APP_URL`, `TURN_HOST` and the UI's `BACKEND_URL`
  all switch from the ngrok domain to your own domain.

**Managed PostgreSQL.** Move the database off the VM for automated backups and
point-in-time restore. Follow
[azure_postgres_and_foir_integration_guide.md](azure_postgres_and_foir_integration_guide.md):
whitelist the `VECTOR` extension, then set
`DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/postgres?ssl=require`
for `api`, `ari-manager`, `campaign-orchestrator` and `arq-worker`, and drop the
`postgres` service.

**Container Apps instead of a VM.** If you want managed ingress, revisions and
scale rules instead of a VM, see
[azure_container_apps_deployment.md](azure_container_apps_deployment.md). It is a
different topology (8 Container Apps + Azure Files), not a lift-and-shift of
this compose file.
