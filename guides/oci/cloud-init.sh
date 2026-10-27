#!/bin/bash
# Dograh on OCI - first-boot host preparation.
#
# Paste this file's contents into the OCI Console "Initialization script"
# (cloud-init user data) field when launching the instance, or run it manually
# with sudo on a fresh Oracle Linux 9 / Ubuntu 22.04+ instance.
#
# It installs Docker Engine + Compose v2, adds a 4 GB swap file, opens the
# Dograh ports in the OS firewall, and creates the install directory.
#
# Progress/errors: /var/log/cloud-init-output.log

set -euxo pipefail

# ---------------------------------------------------------------- Docker ----
# Uses Docker's official convenience script because it handles the Oracle
# Linux 9 / podman-runc package conflicts reliably. If your security policy
# forbids curl | sh, install docker-ce + docker-compose-plugin from Docker's
# repository for your distro instead.
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# The default login user on OCI images is `opc` (Oracle Linux) or `ubuntu`.
TARGET_USER="$(getent passwd opc >/dev/null 2>&1 && echo opc || echo ubuntu)"
usermod -aG docker "${TARGET_USER}"

# ------------------------------------------------------------------ Swap ----
# Table insurance for the API image (torch + local models). Skipped if swap
# already exists.
if ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

# -------------------------------------------------------- OS-level firewall --
# Oracle Linux ships firewalld enabled; Ubuntu images on OCI usually have no
# active host firewall. The VCN security list / NSG is the real gate, but keep
# the host firewall consistent with it (and remember that Docker inserts its
# own iptables rules, so published ports are not protected by firewalld alone).
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld; then
  firewall-cmd --permanent --add-service=http
  firewall-cmd --permanent --add-service=https
  firewall-cmd --permanent --add-port=3478/tcp    # TURN
  firewall-cmd --permanent --add-port=3478/udp    # TURN
  firewall-cmd --permanent --add-port=5349/tcp    # TURN over TLS (optional)
  firewall-cmd --permanent --add-port=5349/udp
  firewall-cmd --permanent --add-port=49152-49200/udp  # TURN relay range
  firewall-cmd --reload
elif command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw allow 3478/tcp
  ufw allow 3478/udp
  ufw allow 5349/tcp
  ufw allow 5349/udp
  ufw allow 49152:49200/udp
fi

# ------------------------------------------------------------- Install dir ---
install -d -o "${TARGET_USER}" -g "${TARGET_USER}" "/home/${TARGET_USER}/dograh"

docker --version
docker compose version

echo "Host preparation complete. Next: deploy the stack as ${TARGET_USER}."
