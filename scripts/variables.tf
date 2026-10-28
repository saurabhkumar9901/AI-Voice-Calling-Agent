###############################################################################
### Oracle Cloud Always Free — Ampere A1 instance
###
### Values mirror scripts/a1.env (used by the capacity hunter). If you change
### one, change both, or pass a terraform.tfvars to override.
###############################################################################

variable "region" {
  description = "OCI region. ap-mumbai-1 is the tenancy's home region, which is required for Always Free resources."
  type        = string
  default     = "ap-mumbai-1"
}

variable "availability_domain" {
  description = "Availability domain. ap-mumbai-1 has a single AD, so this is fixed."
  type        = string
  default     = "TlIq:AP-MUMBAI-1-AD-1"
}

variable "compartment_id" {
  description = "Compartment (or tenancy) OCID to create the instance in."
  type        = string
  default     = "ocid1.tenancy.oc1..aaaaaaaahwx5lp55gpy7votjzmoa5pfoyqjxcqf4sxpqr4yjxkdzxropm5ta"
}

variable "display_name" {
  description = "Stable instance name. Do not put a timestamp in it — the hunter uses this name when it re-adopts an instance."
  type        = string
  default     = "dograh-a1"
}

variable "source_image_id" {
  description = "Boot image OCID (aarch64). Deprecated images fail with InvalidParameter rather than OutOfHostCapacity."
  type        = string
  default     = "ocid1.image.oc1.ap-mumbai-1.aaaaaaaa2jurqb3jm7hlpqw3au35loaqjkcozbyh7znn4jnfu5zbrgfulwia"
}

variable "subnet_id" {
  description = "Subnet OCID for the primary VNIC."
  type        = string
  default     = "ocid1.subnet.oc1.ap-mumbai-1.aaaaaaaagzdxqmrcfk65wmhg74grgcgl4zu2cljuxfdjeqkdv4qpkh6qdwsq"
}

variable "nsg_ids" {
  description = "Network security groups to attach to the primary VNIC."
  type        = list(string)
  default = [
    "ocid1.networksecuritygroup.oc1.ap-mumbai-1.aaaaaaaa47jkrq42cckcxxymjrmox4ajl6z3k4jz3ygjkstti26fi5onnfba",
  ]
}

variable "ssh_public_key" {
  description = "Public key installed for the opc/ubuntu user. Never a private key. Mirrors SSH_PUBLIC_KEY in scripts/a1.env."
  type        = string
  default     = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDF8zW2c01r0dk4fEf5vZd6dWtBaQstHGFF9BCLP0TmP2N/TpLD8mFO1TXy1zHzUcYneesouGQml3CwIH3HmklMX+EuCQtfo08oVnsnZPx/Cdl26+4DfxbgpwKks1y7Fi4l92T81quXrL0fbEujLEYzi4NroPWa4J7yV3XTEUJiz5Jz+oFGCfyfGI9pGbETs3uMQENVW/Ckjp9ayAs3qJD9q3MTNBDIq2x4j/esL0PWWH9fSIiFTJyA4P1N/aPKxr0+c0Qhj4CiNAbQ2L/suXIC345NXeHE+vbf1cCfVhnry7CcImssRWqDmZJJaiUfySIiIgIfHdXBZPX25lrSoXn5 ssh-key-2026-10-28"
}

###############################################################################
### Shape
###
### Always Free A1 is 2 OCPU / 12 GB. Anything larger is billed, and on an
### Always Free tenancy it fails on the tenancy limit before capacity is even
### considered.
###############################################################################

variable "ocpus" {
  description = "OCPU count. 2 is the Always Free ceiling."
  type        = number
  default     = 2
}

variable "memory_in_gbs" {
  description = "Memory in GB. 12 is the Always Free ceiling."
  type        = number
  default     = 12
}

variable "boot_volume_size_in_gbs" {
  description = "Boot volume size. 50 GB is the default and leaves room inside the 200 GB free block storage allowance."
  type        = number
  default     = 50
}
