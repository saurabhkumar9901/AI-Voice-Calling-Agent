#!/bin/bash
# Dograh on an Azure Virtual Machine - first-boot host preparation.
#
# Paste this file's contents into the Azure Portal "Custom data" field when
# creating the VM, or run it with sudo on a fresh Ubuntu 22.04/24.04 instance.
#
# It installs Docker Engine + Compose v2, adds a 4 GB swap file, aligns the host
# firewall with the NSG (only if ufw is enabled - Azure images ship it inactive),
# and creates the install directory.
#
# Azure's default login user is `azureuser`; OCI/GCP images use `opc`/`ubuntu`.
#
# Progress/errors: /var/log/cloud-init-output.log
#
# Differences from guides/oci/cloud-init.sh:
#   - detects `azureuser` (the Azure Ubuntu default) as well as opc/ubuntu
#   - no firewalld branch (Azure images are Ubuntu/Debian only)
#   - installs tmux, used later to run the ngrok agent

set -euxo pipefail

# --------------------------------------------------------------- Login user --
TARGET_USER=""
for candidate in azureuser opc ubuntu; do
  if getent passwd "${candidate}" >/dev/null 2>&1; then
    TARGET_USER="${candidate}"
    break
  fi
done
# Fallback: first non-root human account (uid >= 1000).
if [ -z "${TARGET_USER}" ]; then
  TARGET_USER="$(awk -F: '$3 >= 1000 && $3 < 65534 {print $1; exit}' /etc/passwd)"
fi
[ -n "${TARGET_USER}" ] || { echo "No login user found" >&2; exit 1; }
echo "Preparing host for user: ${TARGET_USER}"

# ------------------------------------------------------------------ Packages --
export DEBIAN_FRONTEND=noninteractive

# Azure images often run unattended-upgrades on first boot and hold the dpkg
# lock. Retry instead of failing the whole init script.
for attempt in $(seq 1 30); do
  apt-get update -y && apt-get install -y ca-certificates curl tmux jq && break
  echo "apt is busy, retrying in 10s (${attempt}/30)"
  sleep 10
done

# ------------------------------------------------------------------- Docker --
# Docker's official convenience script. If your security policy forbids
# curl | sh, install docker-ce + docker-compose-plugin from Docker's apt repo.
for attempt in $(seq 1 30); do
  curl -fsSL https://get.docker.com | sh && break
  echo "docker install failed, retrying in 10s (${attempt}/30)"
  sleep 10
done
command -v docker >/dev/null || { echo "Docker install failed; see /var/log/cloud-init-output.log" >&2; exit 1; }
systemctl enable --now docker
usermod -aG docker "${TARGET_USER}"

# --------------------------------------------------------------------- Swap --
# Insurance for the API image (torch + pipecat + local sentiment model).
# Skipped if swap already exists.
if ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# -------------------------------------------------------- OS-level firewall --
# The Azure NSG is the real gate. Azure Ubuntu images ship ufw installed but
# inactive, and Docker publishes ports past ufw anyway, so only align the rules
# when ufw is already enabled (never enable it here - a wrong rule locks you
# out of SSH).
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 3478/tcp
  ufw allow 3478/udp
  ufw allow 49152:49200/udp
fi

# ------------------------------------------------------------- Install dir ---
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" "/home/${TARGET_USER}/dograh"

# ---------------------------------------------------------- Data disk (opt) --
# Azure OS disks are small on cheap SKUs. To put Docker's image store on a
# separate data disk, attach one (LUN 0) and uncomment:
#
# DISK=/dev/disk/azure/scsi1/lun0
# if [ -b "${DISK}" ] && ! blkid "${DISK}" >/dev/null 2>&1; then
#   mkfs.ext4 -m 1 "${DISK}"
#   mkdir -p /var/lib/docker
#   echo "UUID=$(blkid -s UUID -o value "${DISK}") /var/lib/docker ext4 defaults,nofail 0 2" >>/etc/fstab
#   mount -a
#   systemctl restart docker
# fi

# ------------------------------------------------------------------- Report --
docker --version
docker compose version
swapon --show
df -h /
nproc && free -h

echo "Host preparation complete. Next: deploy the stack as ${TARGET_USER}."
