#!/usr/bin/env bash

function getArrayHelmValueFiles {
	local root_dir=$1
	local service=$2
	local instance=$3
	local env=$4

	local helm_values="$root_dir/helm/values.yaml"
	local base_values="$root_dir/helm_values/base.yaml"
	local base_env_values="$root_dir/helm_values/base-$env.yaml"

	local service_base_values="$root_dir/helm_values/$service-base.yaml"
	local service_env_base_values="$root_dir/helm_values/$service-$env-base.yaml"
	local service_instance_values="$root_dir/helm_values/$service-$instance.yaml"
	local service_env_instance_values="$root_dir/helm_values/$service-$env-$instance.yaml"

	local service_dir_base_values="$root_dir/helm_values/$service/base.yaml"
	local service_dir_base_env_values="$root_dir/helm_values/$service/base-$env.yaml"
	local service_dir_instance_values="$root_dir/helm_values/$service/$instance.yaml"
	local service_dir_instance_env_values="$root_dir/helm_values/$service/$instance-$env.yaml"

	local service_dir_env_dir_base_values="$root_dir/helm_values/$service/$env/base.yaml"
	local service_dir_env_dir_instance_values="$root_dir/helm_values/$service/$env/$instance.yaml"

	local service_dir_instance_dir_base_values="$root_dir/helm_values/$service/$instance/base.yaml"
	local service_dir_instance_dir_env_values="$root_dir/helm_values/$service/$instance/$env.yaml"

	local env_dir_base_values="$root_dir/helm_values/$env/base.yaml"
	local env_dir_instance_values="$root_dir/helm_values/$env/$instance.yaml"

	# The order of the file matters here.
	# The latter ones will override values define in previous files.

	array_file_values+=()
	[[ -f "$base_values" ]] && array_file_values+=("$base_values") || true
	[[ -f "$base_env_values" ]] && array_file_values+=("$base_env_values") || true

	[[ -f "$service_base_values" ]] && array_file_values+=("$service_base_values") || true
	[[ -f "$service_env_base_values" ]] && array_file_values+=("$service_env_base_values") || true
	[[ -f "$service_instance_values" ]] && array_file_values+=("$service_instance_values") || true
	[[ -f "$service_env_instance_values" ]] && array_file_values+=("$service_env_instance_values") || true

	[[ -f "$service_dir_base_values" ]] && array_file_values+=("$service_dir_base_values") || true
	[[ -f "$service_dir_base_env_values" ]] && array_file_values+=("$service_dir_base_env_values") || true
	[[ -f "$service_dir_instance_values" ]] && array_file_values+=("$service_dir_instance_values") || true
	[[ -f "$service_dir_instance_env_values" ]] && array_file_values+=("$service_dir_instance_env_values") || true

	[[ -f "$service_dir_env_dir_base_values" ]] && array_file_values+=("$service_dir_env_dir_base_values") || true
	[[ -f "$service_dir_env_dir_instance_values" ]] && array_file_values+=("$service_dir_env_dir_instance_values") || true

	[[ -f "$service_dir_instance_dir_base_values" ]] && array_file_values+=("$service_dir_instance_dir_base_values") || true
	[[ -f "$service_dir_instance_dir_env_values" ]] && array_file_values+=("$service_dir_instance_dir_env_values") || true

	[[ -f "$env_dir_base_values" ]] && array_file_values+=("$env_dir_base_values") || true
	[[ -f "$env_dir_instance_values" ]] && array_file_values+=("$env_dir_instance_values") || true
}

function getVersion {
	grep appVersion helm/Chart.yaml | cut -d ':' -f 2 | tr -d '[:space:]' | tr -d '["'']'
}
