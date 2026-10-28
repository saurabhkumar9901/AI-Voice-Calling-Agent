#!/usr/bin/env bash
###############################################################################
### OCI Always Free Ampere A1 — capacity hunter
###
### OCI has no "off-hours": A1 capacity in ap-mumbai-1 opens in windows of
### seconds to minutes at unpredictable times. So this script is not a
### scheduler, it is a poller. It retries the launch until OCI has capacity,
### then stops and reports where the instance landed.
###
### Usage:
###   DRY_RUN=1 bash scripts/hunt-a1.sh     # probe capacity, never launch
###   bash scripts/hunt-a1.sh               # hunt
###
### Tunables (env): MAX_ATTEMPTS, RETRY_SECONDS, JITTER_SECONDS
###
### Auth: standard OCI CLI env vars (OCI_CLI_USER, OCI_CLI_TENANCY,
### OCI_CLI_FINGERPRINT, OCI_CLI_KEY_FILE, OCI_CLI_REGION). No ~/.oci/config
### is required or written.
###############################################################################

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=/dev/null
source "$SCRIPT_DIR/a1.env"

MAX_ATTEMPTS="${MAX_ATTEMPTS:-5}"
RETRY_SECONDS="${RETRY_SECONDS:-60}"
JITTER_SECONDS="${JITTER_SECONDS:-30}"
DRY_RUN="${DRY_RUN:-0}"

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
NC=$'\033[0m'

log()  { printf '%s  %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }
ok()   { printf '%s  %s%s%s\n' "$(date -u +%H:%M:%SZ)" "$GREEN" "$*" "$NC"; }
warn() { printf '%s  %s%s%s\n' "$(date -u +%H:%M:%SZ)" "$YELLOW" "$*" "$NC"; }
err()  { printf '%s  %s%s%s\n' "$(date -u +%H:%M:%SZ)" "$RED" "$*" "$NC" >&2; }

summary() {
  [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] && printf '%s\n' "$*" >> "$GITHUB_STEP_SUMMARY"
  return 0
}

###############################################################################
### Notifications
###############################################################################

notify() {
  local title="$1" body="$2"

  summary "### $title" "" "$body" ""

  [[ -n "${GH_TOKEN:-}" && -n "${GITHUB_REPOSITORY:-}" ]] || return 0

  if ! command -v gh >/dev/null; then
    warn "gh is not installed; skipping the GitHub issue."
    return 0
  fi

  # Dedupe: a broken config fails every 10 minutes, and one issue per run is
  # spam. Comment on the open issue instead of opening a new one.
  local existing
  existing="$(gh issue list --repo "$GITHUB_REPOSITORY" --state open \
    --search "in:title \"$title\"" --json number --jq '.[0].number // empty' 2>/dev/null || true)"

  if [[ -n "$existing" ]]; then
    gh issue comment "$existing" --repo "$GITHUB_REPOSITORY" \
      --body "Still failing at $(date -u +%Y-%m-%dT%H:%M:%SZ)." >/dev/null \
      || warn "Could not comment on issue #$existing."
  else
    gh issue create --repo "$GITHUB_REPOSITORY" --title "$title" --body "$body" \
      || warn "Could not open a GitHub issue (continuing)."
  fi
}

# Once we own an instance, stop burning API calls and runner minutes.
disable_self() {
  if [[ -n "${GH_TOKEN:-}" && -n "${GITHUB_REPOSITORY:-}" ]]; then
    # The Actions API accepts the workflow file name in place of an ID.
    gh api -X PUT "repos/${GITHUB_REPOSITORY}/actions/workflows/a1-hunter.yml/disable" >/dev/null \
      || warn "Could not disable the workflow; disable it manually."
    ok "Workflow a1-hunter.yml disabled."
  else
    warn "Not running in GitHub Actions; disable the schedule manually."
  fi
}

###############################################################################
### OCI helpers
###############################################################################

# Any A1 instance with our display name that is not on its way out. Prints an
# OCID or nothing.
#
# Scoped by name on purpose: a different A1 instance in the tenancy must not be
# mistaken for a win. If one exists, the launch fails on the tenancy limit and
# the run stops with an explanation instead of pretending to be done.
#
# The guard is also what makes repeated runs idempotent: a launch that succeeds
# while the CLI times out would otherwise create a second instance.
existing_instance() {
  local id
  id="$(oci compute instance list \
    --compartment-id "$COMPARTMENT_ID" \
    --all \
    --query "data[?\"shape\"=='VM.Standard.A1.Flex' && \"display-name\"=='${DISPLAY_NAME}' && \"lifecycle-state\"!='TERMINATED' && \"lifecycle-state\"!='TERMINATING'] | [0].id" \
    --raw-output 2>/dev/null || true)"

  [[ "$id" == "null" ]] && id=""
  printf '%s' "$id"
}

instance_state() {
  oci compute instance get --instance-id "$1" \
    --query 'data."lifecycle-state"' --raw-output 2>/dev/null || echo "UNKNOWN"
}

public_ip_of() {
  oci compute instance list-vnics --instance-id "$1" \
    --query 'data[0]."public-ip"' --raw-output 2>/dev/null || echo "unknown"
}

# Capacity report is telemetry, not a reservation: it can say AVAILABLE and
# the launch can still lose the race a second later. Useful for the logs and
# for fault-domain visibility, never as a gate.
#
# Failures are reported inline instead of being swallowed: an UNKNOWN on every
# single run usually means the user lacks COMPUTE_CAPACITY_REPORT_* permission
# or the shape is not reportable in that region, and that is worth seeing.
probe_capacity() {
  local output
  if output="$(oci compute compute-capacity-report create \
      --compartment-id "$COMPARTMENT_ID" \
      --availability-domain "$AVAILABILITY_DOMAIN" \
      --shape-availabilities "[{\"instanceShape\":\"VM.Standard.A1.Flex\",\"instanceShapeConfig\":{\"ocpus\":${OCPUS},\"memoryInGBs\":${MEMORY_GBS}}}]" \
      --query 'data."shape-availabilities"[0]."availability-status"' \
      --raw-output 2>&1)"; then
    if [[ -n "$output" && "$output" != "null" ]]; then
      printf '%s' "$output"
      return 0
    fi
    printf 'UNKNOWN (empty response)'
    return 0
  fi

  printf 'UNKNOWN (%s)' "$(printf '%s' "$output" \
    | sed -e 's/\x1b\[[0-9;]*m//g' \
    | tr '\n' ' ' | tr -s ' ' | cut -c1-220)"
}

launch_instance() {
  local nsg_json metadata_json
  # No jq dependency: NSG OCIDs and SSH keys contain no characters that need
  # escaping in JSON (base64 plus a comment).
  nsg_json="$(printf '"%s",' "${NSG_IDS[@]}")"
  nsg_json="[${nsg_json%,}]"
  metadata_json="$(printf '{"ssh_authorized_keys":"%s"}' "$SSH_PUBLIC_KEY")"

  local extra=()
  if [[ -n "${USER_DATA_FILE:-}" ]]; then
    local user_data="$REPO_ROOT/$USER_DATA_FILE"
    if [[ -f "$user_data" ]]; then
      extra+=(--user-data-file "$user_data")
    else
      warn "USER_DATA_FILE $USER_DATA_FILE not found; launching without cloud-init."
    fi
  fi

  oci compute instance launch \
    --availability-domain "$AVAILABILITY_DOMAIN" \
    --compartment-id "$COMPARTMENT_ID" \
    --shape "VM.Standard.A1.Flex" \
    --shape-config "{\"ocpus\":${OCPUS},\"memoryInGBs\":${MEMORY_GBS}}" \
    --image-id "$IMAGE_ID" \
    --subnet-id "$SUBNET_ID" \
    --nsg-ids "$nsg_json" \
    --assign-public-ip true \
    --assign-private-dns-record true \
    --display-name "$DISPLAY_NAME" \
    --hostname-label "$DISPLAY_NAME" \
    --boot-volume-size-in-gbs "$BOOT_VOLUME_GBS" \
    --metadata "$metadata_json" \
    ${extra[@]+"${extra[@]}"} \
    --is-pv-encryption-in-transit-enabled true \
    --instance-options '{"areLegacyImdsEndpointsDisabled":true}' \
    --availability-config '{"recoveryAction":"RESTORE_INSTANCE"}' \
    --wait-for-state RUNNING \
    --wait-interval-seconds 15 \
    --max-wait-seconds 180 \
    --query 'data.id' --raw-output 2>&1
}

###############################################################################
### Error classification
###
### Only capacity errors are worth retrying. Everything else is a
### misconfiguration (bad image OCID, missing IAM policy, tenancy limit) and
### retrying it silently for a week is how this kind of automation fails
### without anyone noticing.
###############################################################################

classify_error() {
  local msg="$1"
  shopt -s nocasematch

  local verdict="unknown"
  if   [[ "$msg" =~ out\ of\ host\ capacity|outofhostcapacity ]]; then verdict="capacity"
  elif [[ "$msg" =~ too\ many\ requests|429 ]];                   then verdict="throttle"
  elif [[ "$msg" =~ limitexceeded|limit\ exceeded ]];             then verdict="limit"
  elif [[ "$msg" =~ notauthorized|notauthenticated|401|403 ]];     then verdict="auth"
  elif [[ "$msg" =~ invalidparameter|invalid\ parameter ]];       then verdict="invalid"
  fi

  shopt -u nocasematch
  printf '%s' "$verdict"
}

###############################################################################
### Main
###############################################################################

wait_with_jitter() {
  local base="$1" delay
  delay=$(( base + RANDOM % (JITTER_SECONDS + 1) ))
  log "Sleeping ${delay}s before the next attempt."
  sleep "$delay"
}

report_success() {
  local id="$1" state ip
  state="$(instance_state "$id")"
  ip="$(public_ip_of "$id")"

  ok "Instance is up."
  log "  ocid:  $id"
  log "  state: $state"
  log "  ip:    $ip"

  notify "A1 capacity won — ${DISPLAY_NAME} (${OCPUS} OCPU / ${MEMORY_GBS} GB)" \
"The Always Free Ampere A1 instance was created in ${AVAILABILITY_DOMAIN}.

\`\`\`
ocid:  $id
state: $state
ip:    $ip
\`\`\`

The hunter has disabled itself. Adopt the instance into Terraform:

\`\`\`sh
cd scripts && terraform init
terraform import oci_core_instance.generated_oci_core_instance $id
terraform plan
\`\`\`

Do not run \`terraform destroy\` — losing this instance means re-entering the capacity lottery."

  disable_self
  summary "Instance IP: \`$ip\`"
}

adopt_if_present() {
  local id
  id="$(existing_instance)"
  if [[ -n "$id" ]]; then
    # The launch may have succeeded while the CLI reported a timeout.
    warn "An A1 instance already exists; adopting it instead of launching another."
    report_success "$id"
    return 0
  fi
  return 1
}

main() {
  command -v oci >/dev/null || { err "The OCI CLI is required (pip install oci-cli)."; exit 1; }

  log "Region ${REGION} / ${AVAILABILITY_DOMAIN} / ${OCPUS} OCPU ${MEMORY_GBS} GB"

  # Guard first. A previous run may have won already.
  if adopt_if_present; then
    exit 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY_RUN=1 — capacity report only, nothing will be launched."
    log "Capacity status: $(probe_capacity)"
    summary "DRY_RUN: capacity status is \`$(probe_capacity)\`."
    exit 0
  fi

  local attempt id output verdict
  for (( attempt = 1; attempt <= MAX_ATTEMPTS; attempt++ )); do
    log "Attempt ${attempt}/${MAX_ATTEMPTS} — capacity status: $(probe_capacity)"

    if output="$(launch_instance)"; then
      # Keep only the OCID; any CLI chatter on stderr shares this stream.
      id="$(printf '%s\n' "$output" | grep -E '^ocid1\.instance\.' | tail -n1)"
      report_success "${id:-$output}"
      exit 0
    fi

    log "Launch did not return a running instance."

    # The error may be a wait timeout on an instance that actually exists.
    if adopt_if_present; then
      exit 0
    fi

    verdict="$(classify_error "$output")"
    case "$verdict" in
      capacity)
        warn "Out of host capacity — will retry."
        ;;
      throttle)
        warn "Rate limited by OCI. Ending this run instead of sleeping — the next"
        warn "scheduled run in ~10 minutes is the backoff."
        summary "Rate limited; backing off until the next scheduled run."
        exit 0
        ;;
      limit)
        err "Tenancy limit exceeded. That is not a capacity problem:"
        err "$output"
        notify "A1 hunter stopped — tenancy limit exceeded" \
"The launch failed on a tenancy limit, not on capacity. Check that the shape is within the Always Free allowance (${OCPUS} OCPU / ${MEMORY_GBS} GB) and that no other A1 instance is running.

\`\`\`
$output
\`\`\`"
        exit 1
        ;;
      auth)
        err "Authentication/authorisation failure — the API key or IAM policy is wrong:"
        err "$output"
        notify "A1 hunter stopped — OCI auth failure" \
"The OCI CLI could not authenticate. Rotate/repair the API key or the IAM policy.

\`\`\`
$output
\`\`\`"
        exit 1
        ;;
      invalid)
        err "Invalid parameter — usually a deprecated image OCID or a shape option:"
        err "$output"
        notify "A1 hunter stopped — invalid parameter" \
"The launch was rejected as invalid. Most common cause is a deprecated boot image OCID in scripts/a1.env.

\`\`\`
$output
\`\`\`"
        exit 1
        ;;
      *)
        err "Unexpected error — stopping rather than retrying blind:"
        err "$output"
        notify "A1 hunter stopped — unexpected error" \
"\`\`\`
$output
\`\`\`"
        exit 1
        ;;
    esac

    if [[ "$attempt" -lt "$MAX_ATTEMPTS" ]]; then
      wait_with_jitter "$RETRY_SECONDS"
    fi
  done

  warn "No capacity in ${MAX_ATTEMPTS} attempts. The schedule will try again."
  summary "No capacity after ${MAX_ATTEMPTS} attempts."
  exit 0
}

main "$@"
