#!/usr/bin/env bash
set -e

log () {
	echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

usage="./run_helm.sh namespace service instance [env=test] [mode=deploy] [chart_location=./helm/]"

namespace=${1}
service=${2}
instance=${3}
env=${4:-test}
mode=${5:-deploy}
chart_location=${6:-"./helm"}

if [[ -z "$service" || -z "$instance" ]]; then
	log "Service or instance is not defined." >&2
	echo "Usage: $usage"
	exit 1
fi

. ./scripts/utils.sh
. ./scripts/utils_helm_rollback.sh

root_dir=`pwd`
build_dir="$root_dir/build"
debug_dir="$build_dir/debug/$service/$env"
chart_dir="$(cd "$(dirname "$chart_location")"; pwd)/$(basename "$chart_location")"

declare -a array_file_values
getArrayHelmValueFiles $root_dir $service $instance $env

release_name="$service-$instance-$env"
release_name=$(echo -n ${release_name} | tr '[:upper:]' '[:lower:]' | tr -s -c '[:alnum:]' '-')

values_args=""
for f in ${array_file_values[@]}; do
	if [ -f "$f" ]; then
		values_args="$values_args --values $f"
	fi
done

helm_cmd=""
extra_args=""
final_args=""
if [ ${mode} = "debug" ]; then
	helm_cmd="template"
	extra_args="$extra_args --debug"
	final_args="$final_args >> \"$debug_dir/$release_name-template.yaml\""

	# Cleanup existing template.
	rm -f "$debug_dir/$release_name-template.yaml"
elif [ ${mode} = "deploy" ]; then
	helm_cmd="upgrade"
	extra_args="$extra_args --install --atomic --cleanup-on-fail --wait"
	final_args="$final_args"
elif [ ${mode} = "dry-run" ]; then
	helm_cmd="upgrade"
	extra_args="$extra_args --install --debug --dry-run --output table"
	final_args="$final_args >> \"$debug_dir/$release_name-cluster_$kube_cluster-dry-run.out\""
elif [ ${mode} = "uninstall" ]; then
	helm_cmd="uninstall"
	chart_dir=""
	values_args=""
elif [ ${mode} = "rollback" ]; then
	revision_to_rollback_to=$(getLatestStableRevision $namespace $release_name)
	log "Revision to rollback to: [$revision_to_rollback_to]"
	if [ -z "$revision_to_rollback_to" ]; then
		helm_cmd="uninstall"
		chart_dir=""
		values_args=""
	else
		helm_cmd="rollback"
		chart_dir=""
		values_args=""
		extra_args="$extra_args $revision_to_rollback_to"
	fi
	final_args="$final_args >> \"$debug_dir/$release_name-cluster_$kube_cluster-rollback.out\""
else
	log "Unrecognized mode: $mode."
	exit 1
fi

log "[$release_name] Service: $service, instance: $instance, env: $env, mode: $mode, chart_location: $chart_location."
log "[$release_name] Release: $release_name, helm values files: $values_args."

mkdir -p $debug_dir

if [ ${mode} = "deploy" ]; then
	log "[$release_name] Checking if a rollback is necessary."
	checkReleaseAndRollbackIfRequired $namespace $release_name
fi

cmd="
	helm
	$helm_cmd
	--namespace $namespace
	$release_name
	$chart_dir
	$values_args
	$extra_args
	$final_args
"

log "[$release_name] Executing main cmd: $cmd"
eval $cmd
