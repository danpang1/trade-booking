#!/usr/bin/env bash
#
# Build (and optionally push) the tokka-mo plugin image,
# ${AWS_ECR_URL}/middle-office/tokka-mo-plugin:<plugin version>.
#
#   ./scripts/publish_plugin_image.sh           # build only (PRs, local)
#   ./scripts/publish_plugin_image.sh publish   # build + push (main)
#
# ECR tags are immutable, so publish skips the push when this version is
# already in ECR: an unchanged plugin never fails the main pipeline. A
# plugin change must bump plugin/.claude-plugin/plugin.json (and the
# marketplace.json metadata version) to be published.
set -e
set -o pipefail

log () {
	echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

mode=${1:-build}

AWS_ECR_URL=${AWS_ECR_URL_NEA:-942117878223.dkr.ecr.ap-northeast-1.amazonaws.com}
AWS_REGION=${AWS_DEFAULT_REGION_CI:-ap-northeast-1}
PLUGIN_IMAGE_NAME=${PLUGIN_IMAGE_NAME:-middle-office/tokka-mo-plugin}

plugin_version=$(python3 -c "import json; print(json.load(open('plugin/.claude-plugin/plugin.json'))['version'])")
marketplace_version=$(python3 -c "import json; print(json.load(open('.claude-plugin/marketplace.json'))['metadata']['version'])")

if [[ "$plugin_version" != "$marketplace_version" ]]; then
	log "plugin.json version ($plugin_version) != marketplace.json version ($marketplace_version)." >&2
	exit 1
fi

image="$AWS_ECR_URL/$PLUGIN_IMAGE_NAME:$plugin_version"

if [[ "$mode" == "publish" ]]; then
	source ./.pipelines/docker-login.sh

	if aws ecr describe-images --profile tmp-profile --region "$AWS_REGION" \
		--repository-name "$PLUGIN_IMAGE_NAME" --image-ids imageTag="$plugin_version" >/dev/null 2>&1; then
		log "$image already exists in ECR. Nothing to publish."
		exit 0
	fi
fi

log "Building $image."
# linux/amd64 like every other tokka image: a FROM of this image in an amd64
# build fails with "no match for platform" if it was built for arm64.
docker build \
	--platform linux/amd64 \
	-f docker/Dockerfile.plugin \
	-t "$image" \
	--progress plain \
	.

if [[ "$mode" == "publish" ]]; then
	log "Pushing $image."
	docker push "$image"
fi

log "Finished ($mode) $image."
