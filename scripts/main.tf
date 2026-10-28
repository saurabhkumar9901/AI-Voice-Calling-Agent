###############################################################################
### Oracle Cloud Always Free — Ampere A1 instance (ap-mumbai-1)
###
### This file is the source of truth *after* the instance exists. Getting the
### instance created in the first place is done by scripts/hunt-a1.sh, which
### retries the launch until OCI has A1 capacity. Once it wins, import the
### instance so this state matches reality:
###
###   terraform init
###   terraform import oci_core_instance.generated_oci_core_instance <instance-ocid>
###   terraform plan     # should be a no-op, or close to it
###
### Keep the resource address as-is; renaming it would break that import.
###############################################################################

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0"
    }
  }
}

provider "oci" {
  region = var.region
}

resource "oci_core_instance" "generated_oci_core_instance" {
  availability_domain = var.availability_domain
  compartment_id      = var.compartment_id
  display_name        = var.display_name
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.ocpus
    memory_in_gbs = var.memory_in_gbs
  }

  # The per-plugin list that the console generates is deliberately omitted.
  # Nothing here needs it, and a plugin name that does not exist in a region
  # rejects the whole launch with InvalidParameter — an error that looks like
  # a deployment failure rather than a capacity problem, and one that the
  # hunter would (correctly) refuse to retry.
  agent_config {
    is_management_disabled = false
    is_monitoring_disabled = false
  }

  availability_config {
    recovery_action = "RESTORE_INSTANCE"
  }

  create_vnic_details {
    subnet_id                 = var.subnet_id
    nsg_ids                   = var.nsg_ids
    assign_public_ip          = true
    assign_private_dns_record = true
    display_name              = "dograh-vnic"
  }

  source_details {
    source_type = "image"
    source_id   = var.source_image_id

    boot_volume_size_in_gbs = var.boot_volume_size_in_gbs
    # 10 VPUs/GB is the "Balanced" default; omitting it is equivalent.
    boot_volume_vpus_per_gb = 10
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
  }

  instance_options {
    are_legacy_imds_endpoints_disabled = true
  }

  is_pv_encryption_in_transit_enabled = true

  lifecycle {
    # This instance exists because capacity was scarce. It takes one stray
    # `terraform destroy` to lose it, and winning it back is not guaranteed.
    prevent_destroy = true
  }
}
