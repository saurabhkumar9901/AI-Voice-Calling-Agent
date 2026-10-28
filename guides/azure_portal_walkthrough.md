# Azure Portal Walkthrough — Dograh on a Single VM

**Everything in this document is done in a browser at
[portal.azure.com](https://portal.azure.com).** No Azure CLI, no local Docker.
The only shell work happens in **Azure Cloud Shell**, which is a pane inside the
portal.

Read [azure_vm_deployment.md](azure_vm_deployment.md) for the reasoning behind
each choice; this file is the click-by-click version.

**What you end up with:** one Ubuntu VM running the whole Dograh stack
(Postgres, Redis, MinIO/SILO, API, workers, UI, FOIR service, nginx, coturn),
reachable over HTTPS at an ngrok address, with call audio relayed over TURN.

**Time:** ~15 minutes of clicking + 15–30 minutes of unattended build.

---

## Before you start

Collect these:

| Item | Where |
|---|---|
| Azure subscription with VM quota | portal.azure.com |
| Your public IP (for the SSH rule) | the NSG blade offers "Add current client IP" |
| `api/.env` from your PC | `D:\dograh 19-08\dograh\api\.env` |
| The cloud-init script contents | [azure/cloud-init.sh](azure/cloud-init.sh) — open it and copy everything |
| An ngrok account | sign up free at dashboard.ngrok.com |

> Keep the repository and this guide open on a second screen. You will copy/paste
> a few multi-line blocks.

---

## Phase 1 — Resource group

1. Sign in at **[portal.azure.com](https://portal.azure.com)**.
2. In the top search bar, type **Resource groups** → click **Resource groups**.
3. Click **+ Create**.
4. Fill in:
   - **Subscription**: yours
   - **Resource group**: `rg-dograh`
   - **Region**: `Central India` (or the region closest to your users)
5. Click **Review + create** → **Create**.

---

## Phase 2 — Network security group (the firewall)

6. Search **Network security groups** → **+ Create**.
7. **Basics**: subscription, **Resource group** `rg-dograh`, **Name**
   `dograh-nsg`, **Region** `Central India` → **Review + create** → **Create**.
8. Open `dograh-nsg` → left menu **Settings → Inbound security rules**.
9. Click **+ Add** and create rule 1 — SSH:
   - Source: **IP Addresses**
   - Source IP addresses/CIDR ranges: click **Add current client IP address**
     (or paste your IP as `x.x.x.x/32`)
   - Destination: **Any**
   - Service: **Custom**
   - Destination port ranges: `22`
   - Protocol: **TCP**
   - Action: **Allow**
   - Priority: `1000`
   - Name: `Allow-SSH`
   - → **Add**
10. **+ Add** again — rule 2, TURN signaling:
    - Source: **Any**
    - Destination: **Any**
    - Service: **Custom**
    - Destination port ranges: `3478`
    - Protocol: **Any** *(this covers both TCP and UDP)*
    - Action: **Allow**, Priority `1030`, Name `Allow-TURN` → **Add**
11. **+ Add** again — rule 3, TURN media relay:
    - Source: **Any**, Destination: **Any**, Service: **Custom**
    - Destination port ranges: `49152-49200`
    - Protocol: **UDP**
    - Action: **Allow**, Priority `1040`, Name `Allow-TURN-Relay` → **Add**

You now have exactly three inbound rules. **Do not add** 80, 443, 3000, 3010,
5432, 6379, 8000, 8080, 9000 or 9001 — ngrok needs none of them, and the app
ports are bound to loopback on the VM.

> If you skip the two TURN rules, browser calls connected over mobile/corporate
> networks will have **no audio**.

---

## Phase 3 — Create the VM

12. Search **Virtual machines** → **+ Create → Azure virtual machine**.
13. **Basics** tab:

    | Field | Value |
    |---|---|
    | Subscription | yours |
    | Resource group | `rg-dograh` |
    | Virtual machine name | `dograh` |
    | Region | `Central India` |
    | Availability options | **No infrastructure redundancy required** |
    | Security type | **Standard** |
    | Image | **Ubuntu Server 24.04 LTS - x64 Gen2** |
    | VM architecture | **x64** |
    | Size | **Standard_D4s_v5** (4 vCPU / 16 GiB) — see note below |
    | Authentication type | **SSH public key** |
    | Username | `azureuser` |
    | SSH public key source | **Generate new key pair** |
    | Key pair name | `dograh-key` |
    | Public inbound ports | **None** |
    | Licensing | leave unchecked |

    If `Standard_D4s_v5` is not in the list, click **See all sizes**, type
    `D4s_v5` in the search box, then **Select**. A cheaper dev option is
    `Standard_B4ms` (same 4 vCPU / 16 GiB, burstable — fine for testing, but it
    throttles under sustained call load).

14. **Disks** tab:
    - **OS disk type**: `Premium SSD (locally-redundant storage)`
    - **OS disk size**: click **Change size** → **128 GiB** (the default 30 GiB
      is too small for the Docker build)
    - Encryption: leave the default (platform-managed key)
    - *Optional:* **+ Create and attach a disk** → 128 GiB Premium SSD, if you
      later want `/var/lib/docker` on its own disk
15. **Networking** tab:
    - **Virtual network**: **Create new** → name `dograh-vnet`, address space
      `10.0.0.0/16`, subnet `default` `10.0.0.0/24` → **OK**
    - **Subnet**: `default`
    - **Public IP**: **Create new** → name `dograh-ip`, **SKU Standard**,
      **Assignment Static**, Routing preference **Microsoft network** → **OK**
    - **NIC network security group**: **Advanced** → **Network security group**
      → `dograh-nsg`
    - **Delete public IP and NIC when VM is deleted**: **unchecked**
    - **Load balancing**: None
16. **Management** tab: leave defaults (boot diagnostics on).
17. **Monitoring** tab: leave defaults.
18. **Advanced** tab → **Custom data**: paste the **entire** contents of
    [azure/cloud-init.sh](azure/cloud-init.sh).
    This installs Docker + Compose, adds 4 GB swap, and creates `~/dograh`.
19. **Review + create**. Wait for "Validation passed".
20. Click **Create**. In the **Generate new key pair** dialog click
    **Download private key and create resource**.
    → `dograh-key.pem` lands in your Downloads folder. **You cannot download it
    again** — keep it safe.
21. Wait for "Your deployment is complete" (2–5 min) → **Go to resource**.
22. On the **Overview** page, note the **Public IP address**. It is static and
    must never change (coturn advertises it).

Sanity check on the same page: **Networking** should list `dograh-nsg`, and the
public IP should show **Static**.

---

## Phase 4 — Open Cloud Shell and connect

23. Click the **Cloud Shell** icon in the portal top bar (`>_`).
24. Choose **Bash**.
25. First time only: click **Create storage** (a small storage account is
    created for the shell) and wait for the prompt.
26. Upload your private key: toolbar **Upload/Download files** (the
    up-arrow icon) → **Upload** → select `dograh-key.pem`.
27. In the shell:

    ```bash
    chmod 600 ~/dograh-key.pem
    ssh -i ~/dograh-key.pem azureuser@<PUBLIC_IP>
    ```

    Type `yes` at the fingerprint prompt. You are now on the VM.

    > `Permission denied (publickey)` → wrong key or wrong user. The user is
    > **`azureuser`**, not `ubuntu`.
    > `UNPROTECTED PRIVATE KEY FILE` → run `chmod 600` again.

28. Verify the host preparation:

    ```bash
    docker --version && docker compose version
    free -h
    df -h /
    sudo swapon --show
    ```

    Expect Docker + Compose v2.24.4 or newer, ~16 GB RAM, ~120 GB free, 4 GB
    swap. If Docker is missing, check
    `sudo tail -100 /var/log/cloud-init-output.log`.

> Cloud Shell has an inactivity timeout. Everything in Phase 6 runs inside
> `tmux`, so a timeout cannot kill the build.

---

## Phase 5 — Get an ngrok domain (second browser tab)

29. Open **https://dashboard.ngrok.com** → sign up / sign in.
30. **Getting Started → Your Authtoken** → copy the token.
31. In the left menu open **Universal Gateway → Domains** (older dashboards:
    **Endpoints → Domains**) → **+ Create domain** / **New Domain**.
    Accept the free static domain and note it, e.g.
    `dograh-abc123.ngrok-free.app`.
32. Copy that domain — it goes into `PUBLIC_URL` below.

> If ngrok is already running on your PC with the same domain, stop it first:
> one static domain can only be online from one agent at a time.

---

## Phase 6 — Deploy the stack (Cloud Shell, on the VM)

33. Install git and clone the repository:

    ```bash
    sudo apt-get update && sudo apt-get install -y git
    cd ~
    git clone https://github.com/saurabhkumar9901/AI-Voice-Calling-Agent.git
    cd ~/AI-Voice-Calling-Agent
    ```

    Private fork? Use a GitHub Personal Access Token as the password when
    prompted. Using a different fork URL? That is fine — just adjust the path.

34. Copy `api/.env` from your PC:
    - Type `exit` to return to Cloud Shell.
    - **Rename** your local file to `api-env.txt` (dotfiles are awkward to pick
      in the upload dialog), then toolbar → **Upload** → select it.
    - Then:

      ```bash
      scp -i ~/dograh-key.pem ~/api-env.txt \
        azureuser@<PUBLIC_IP>:~/AI-Voice-Calling-Agent/api/.env
      ssh -i ~/dograh-key.pem azureuser@<PUBLIC_IP>
      cd ~/AI-Voice-Calling-Agent
      ```

    No local `api/.env`? Copy `api/.env.example` instead — the stack boots, but
    you will need provider keys in the UI before calls work.

35. Add the JWT secret (the built-in default is public knowledge):

    ```bash
    grep -qE '^OSS_JWT_SECRET=.+' api/.env \
      || echo "OSS_JWT_SECRET=$(openssl rand -hex 32)" >> api/.env
    ```

36. Create the root `.env`. **Replace the domain** with yours from step 31:

    ```bash
    cat > .env <<EOF
    PUBLIC_URL=https://dograh-abc123.ngrok-free.app
    PUBLIC_IP=$(curl -4 -s https://ifconfig.me)
    PRIVATE_IP=$(ip -4 route get 1.1.1.1 | awk '{print $7}')
    TURN_SECRET=$(openssl rand -hex 32)
    EOF
    chmod 600 .env
    set -a; . ./.env; set +a
    cat .env
    ```

    `PUBLIC_IP` must equal the **Public IP address** from step 22. If
    `ifconfig.me` is blocked, read it from Azure's metadata service:

    ```bash
    curl -s -H Metadata:true \
      "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text"
    ```

37. Create the TURN config (uses the variables you just exported):

    ```bash
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
    ```

    `external-ip=PUBLIC/PRIVATE` is what makes TURN work on Azure: the VM's NIC
    only has the private `10.x` address, and the public IP is 1:1 NAT.

38. Install ngrok and register the authtoken:

    ```bash
    curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
      | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
      | sudo tee /etc/apt/sources.list.d/ngrok.list
    sudo apt-get update && sudo apt-get install -y ngrok

    ngrok config add-authtoken <YOUR_AUTHTOKEN>
    ```

39. Run ngrok as a **service** so it survives reboots:

    ```bash
    cd ~/AI-Voice-Calling-Agent
    set -a; . ./.env; set +a

    mkdir -p ~/.config/ngrok
    cat > ~/.config/ngrok/ngrok.yml <<EOF
    version: 3
    agent:
      authtoken: <YOUR_AUTHTOKEN>
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

    Expect `Session Status online`.

40. Start a `tmux` session so the long build survives a Cloud Shell timeout:

    ```bash
    tmux new -s deploy
    ```

41. Build and start everything:

    ```bash
    cd ~/AI-Voice-Calling-Agent
    D="docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml"
    $D up -d --build
    ```

    First build: **15–30 minutes** (CPU torch, pipecat, Next.js). If Cloud Shell
    disconnects, reconnect (steps 23–27), then `tmux attach -t deploy` — the
    build keeps running.

42. When it returns, check status:

    ```bash
    $D ps
    ```

    `api` may show `starting`/`unhealthy` for up to ~3 minutes while Alembic
    migrates the database. `ui` waits for `api`; `nginx` waits for both.

43. Verify:

    ```bash
    curl -s  localhost:8000/api/v1/health
    curl -sI localhost:3000 | head -1
    curl -sI localhost:8080 | head -1
    curl -fsS "${PUBLIC_URL}/api/v1/health"
    ```

44. Reboot once to prove everything comes back by itself:

    ```bash
    sudo reboot
    ```

    Reconnect after ~1 minute and run:

    ```bash
    cd ~/AI-Voice-Calling-Agent
    docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml ps
    systemctl status ngrok --no-pager
    ```

    All containers should be `Up`, ngrok `online`, with no manual steps.

---

## Phase 7 — First use (browser)

45. Open **`https://<your-domain>`**.
46. Free ngrok shows a **"You are about to visit…"** warning page once — click
    **Visit Site**. (Telephony webhooks are not affected.)
47. **Sign up** to create the first local account (stored on your VM).
48. Open **Model Configurations** and add your LLM / STT / TTS keys.
49. Open an agent → **Web Call** → allow the microphone. This proves HTTPS +
    WebRTC + TURN.
50. Upload a document and play back a recording to prove the `/voice-audio/`
    route.
51. For Vobiz / Twilio / Cloudonix, set the webhook to `https://<your-domain>`.
52. Optional: call the number from a phone on **mobile data** — that is the
    honest test for TURN audio.

---

## Phase 8 — Day-2 operations (all in the portal)

**Stop billing when idle**
VM → **Overview → Stop**. This *deallocates* the VM (compute billing stops; the
disk and static IP keep billing). **Restart** brings the stack back on its own.
A VM that is only "Stopped" still bills compute — always use **Stop**.

**See logs without SSH**
VM → **Operations → Run command → RunShellScript**:

```bash
cd /home/azureuser/AI-Voice-Calling-Agent && docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml logs --tail=100 api
```

**Recover from a broken firewall / lost SSH**
VM → **Help → Serial console**, or **Operations → Run command**.

**Backups**
- VM → **Operations → Backup** → create a Recovery Services vault → apply the
  default daily policy. This snapshots the OS disk (Postgres + MinIO live there).
- Also keep an off-VM `pg_dump` (see [azure_vm_deployment.md](azure_vm_deployment.md) §11).

**Alerts**
VM → **Monitoring → Alerts → + Create alert rule** → signal **Percentage CPU**
and **OS disk free space** (requires the Azure Monitor agent) or **Disk Used
Percentage**.

**Update the app**
Connect again (steps 23–27), then:

```bash
cd ~/AI-Voice-Calling-Agent
git pull
docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml up -d --build
docker image prune -f
```

---

## Quick reference — values used

| Setting | Value |
|---|---|
| Resource group | `rg-dograh` |
| Region | `Central India` |
| NSG | `dograh-nsg` |
| Inbound rules | 22 (your IP), 3478 any, 49152-49200 UDP |
| VM name | `dograh` |
| Image | Ubuntu Server 24.04 LTS x64 Gen2 |
| Size | `Standard_D4s_v5` (dev: `Standard_B4ms`) |
| Login user | `azureuser` |
| SSH key | `dograh-key.pem` (downloaded once) |
| OS disk | 128 GiB Premium SSD |
| Public IP | `dograh-ip`, Standard SKU, **Static** |
| Root `.env` | `PUBLIC_URL`, `PUBLIC_IP`, `PRIVATE_IP`, `TURN_SECRET` |
| Compose command | `docker compose -f docker-compose-ecs.yaml -f docker-compose.ngrok.yaml …` |

## If something goes wrong

| Symptom | Fix |
|---|---|
| VM creation fails with `OperationNotAllowed` | No vCPU quota in that region: Subscription → **Usage + quotas** → request an increase, or pick `B4ms` / another region |
| SSH `Permission denied (publickey)` | User is `azureuser`; key must be `dograh-key.pem` with `chmod 600` |
| `docker: command not found` | Cloud-init did not finish: `sudo tail -100 /var/log/cloud-init-output.log`, then `sudo bash ~/cloud-init.sh` |
| Site not reachable | `systemctl status ngrok`; confirm the domain in `.env` matches step 31 exactly |
| Microphone blocked | You are on `http://` — use the `https://` ngrok URL |
| Calls connect, no audio | NSG missing 3478 or the UDP relay range; check `turnserver.conf` has `external-ip=PUBLIC/PRIVATE` |
| `no space left on device` | `docker builder prune -f`; OS disk must be ≥128 GiB |
| No recording/transcript after a call | The `shared-tmp` volume is missing on `api`/`arq-worker` — use both `-f` files |
