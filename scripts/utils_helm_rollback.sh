#!/usr/bin/env bash

# https://github.com/helm/helm/blob/1338ffe6083990ceefb74b9ab5559689de8d791d/pkg/release/status.go#L23-L41
helm_final_status=(
	"deployed"
	"failed"
)

helm_pending_status=(
	"uninstalling"
	"pending-install"
	"pending-upgrade"
	"pending-rollback"
)

# Get the current status of the deployment.
getDeploymentStatus() {
	local namespace=$1
	local deployment=$2
	helm status -n "$namespace" "$deployment" -o json 2>/dev/null | jq -r .info.status

	# We failed to get the status. It might be because the deployment does not exist,
	# or maybe Rancher is down.
	if [[ $? -ne 0 ]]; then
		log "[$deployment] Failed to check deployment for helm rollback. Returning."
		return
	fi
}

# Get latest stable deployed revision
getLatestStableRevision(){
	local namespace=$1
	local deployment=$2
	revision_to_rollback_to=$(helm history -n $namespace $deployment -o json 2>/dev/null | jq '[.[] | select(.status=="deployed" or .status=="superseded")][-2].revision')
	if [[ $? -ne 0 ]]; then
		log "[$deployment] Failed to check deployment for latest revision. Returning."
		exit 1
	else
		echo $revision_to_rollback_to
	fi
}

# Remove deployment
uninstallDeployment(){
	local namespace=$1
	local deployment=$2
	cmd="helm uninstall -n $namespace $deployment"
	log "[$deployment] Executing uninstall cmd: $cmd"
	log "Removing [$deployment]"
	eval $cmd
	log "Deployment removed successfully"
}

# Rollback revison
rollbackRevision(){
	local namespace=$1
	local deployment=$2
	local revision_to_rollback_to=$3
	cmd="helm rollback -n $namespace $deployment $revision_to_rollback_to"
	log "[$deployment] Executing rollback cmd: $cmd"
	eval $cmd
	deployment_history=$(helm history -n $namespace $deployment)
	log "Deployment history after rolling back: "
	echo "$deployment_history"
}

function checkReleaseAndRollbackIfRequired {
	local namespace=$1
	local deployment=$2

	log "[$deployment] Checking deployment $deployment for helm rollback."

	current_status=$(getDeploymentStatus "$namespace" "$deployment")

	# If it is successful or failed, no need for rollback.
	if [[ " ${helm_final_status[*]} " =~ " ${current_status} " ]]; then
		log "[$deployment] Deployment has status of $current_status. Returning."
		return
	fi

	# If it is pending, roll it back.
	if [[ " ${helm_pending_status[*]} " =~ " ${current_status} " ]]; then
		log "[$deployment] Deployment has status of $current_status. Rolling back."

		# Get latest revision to rollback to.
		revision_to_rollback_to=$(helm history -n $namespace $deployment -o json 2>/dev/null | jq -r 'last(.[] | select(.status=="deployed" or .status=="superseded") | .revision )')
		if [[ $? -ne 0 ]]; then
			log "[$deployment] Failed to check deployment for latest revision. Returning."
			return
		fi

		if [[ "$revision_to_rollback_to" -eq "" ]]; then
			log "[$deployment] Deployment latest successful revision does not exist. Uninstalling."
			uninstallDeployment $namespace $deployment
		else
			log "[$deployment] Deployment latest successful revision is $revision_to_rollback_to. Rolling back."
			rollbackRevision $namespace $deployment $revision_to_rollback_to
		fi
		return
	fi
}
