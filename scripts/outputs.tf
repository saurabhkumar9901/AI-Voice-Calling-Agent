output "instance_id" {
  description = "OCID of the A1 instance, once it exists."
  value       = oci_core_instance.generated_oci_core_instance.id
}

output "instance_name" {
  description = "Display name the capacity hunter looks for when it re-adopts an instance."
  value       = oci_core_instance.generated_oci_core_instance.display_name
}

output "availability_domain" {
  description = "Availability domain the instance landed in."
  value       = oci_core_instance.generated_oci_core_instance.availability_domain
}

output "public_ip_hint" {
  description = "Terraform does not expose the VNIC's public IP directly; read it with the OCI CLI instead."
  value       = "oci compute instance list-vnics --instance-id ${oci_core_instance.generated_oci_core_instance.id} --query 'data[0].\"public-ip\"' --raw-output"
}
