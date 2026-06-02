#!/usr/bin/env bash
#
# We are supporting multi arch builds here. See the following guide:
# https://aws.amazon.com/blogs/containers/introducing-multi-architecture-container-images-for-amazon-ecr
#
set -e
set -o pipefail

log () {
	echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

AWS_ECR_URL=${AWS_ECR_URL_NEA:-942117878223.dkr.ecr.ap-northeast-1.amazonaws.com}
AWS_REGION=${AWS_DEFAULT_REGION_CI:-ap-northeast-1}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID_CI:-""}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY_CI:-""}

DOCKER_FILE=${DOCKER_FILE:-"docker/Dockerfile"}
DOCKER_BUILDX_CONFIGURE=${DOCKER_BUILDX_CONFIGURE:-""}
DOCKER_BUILDX_LOCAL_CACHE_ENABLE=${DOCKER_BUILDX_LOCAL_CACHE_ENABLE:-false}
DOCKER_BUILDX_LOCAL_CACHE=${DOCKER_BUILDX_LOCAL_CACHE:-"/tmp/cache/buildx"}
DOCKER_BUILDX_REMOTE_CACHE_ENABLE=${DOCKER_BUILDX_REMOTE_CACHE_ENABLE:-false}
DOCKER_LOGIN_FORCE=${DOCKER_LOGIN_FORCE:-false}

IMAGE_NAME=${IMAGE_NAME:-unknown_image_name}
IMAGE_PLATFORMS=${IMAGE_PLATFORMS:-""}
IMAGE_BUILD_ARGS=${IMAGE_BUILD_ARGS:-""}

VERSION=${VERSION:-unknown_image_version}
TRIVY_ENABLED=${TRIVY_ENABLED:-true}
TRIVY_SEVERITY=${TRIVY_SEVERITY:-"CRITICAL"}
TRIVY_EXIT_CODE=${TRIVY_EXIT_CODE:-1}

function run_trivy_scan () {
	local image="$1"
	if [[ "$TRIVY_ENABLED" != "true" ]]; then
		log "Trivy scan is disabled. Skipping."
		return
	fi

	log "Running Trivy vulnerability scan on ${image}"
	if ! command -v trivy &> /dev/null; then
		log "Trivy not found. Installing..."
		curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh -s -- -b /usr/local/bin
	fi
	trivy image --scanners vuln --severity "$TRIVY_SEVERITY" --exit-code "$TRIVY_EXIT_CODE" --ignore-unfixed "$image"
	log "Trivy scan completed for ${image}"
}

# Push the image, unless its tag already exists in the (immutable) ECR
# repository. ECR rejects an overwrite of an existing tag, which would
# fail the whole step; a commit to main that doesn't bump the chart
# version (refdata syncs, online edits) would otherwise red the pipeline.
# Reuses docker's existing registry auth (same auth `docker push` uses),
# so it needs no extra aws profile. If the inspect fails for any reason
# other than a missing tag, we fall through to push — no worse than before.
function publish_or_skip () {
	local ref="${AWS_ECR_URL}/${IMAGE_NAME}:${VERSION}"
	if docker manifest inspect "${ref}" > /dev/null 2>&1; then
		log "Tag ${VERSION} already exists in ${IMAGE_NAME} (immutable repo) — skipping push. Bump the chart version to publish new content."
		return 0
	fi
	log "Publishing docker ${IMAGE_NAME}:${VERSION}"
	docker push "${ref}"
}

function package_and_publish_docker () {
	log "Packaging docker ${IMAGE_NAME}:${VERSION}"
	IMAGE_BUILD_ARGS_FINAL="${IMAGE_BUILD_ARGS}"

	docker build \
		-f "${DOCKER_FILE}" \
		-t "${AWS_ECR_URL}/${IMAGE_NAME}:${VERSION}" \
		--progress plain \
		$IMAGE_BUILD_ARGS_FINAL \
		.

	run_trivy_scan "${AWS_ECR_URL}/${IMAGE_NAME}:${VERSION}"

	publish_or_skip

	log "Finished packaging and publishing docker ${IMAGE_NAME}:${VERSION}"
}

function package_and_publish_dockerx () {
	log "Performing a multi-platform build."

	IMAGE_BUILD_ARGS_FINAL="${IMAGE_BUILD_ARGS}"

	if [[ "$DOCKER_BUILDX_LOCAL_CACHE_ENABLE" == "true" ]]; then
		mkdir -p $DOCKER_BUILDX_LOCAL_CACHE
		IMAGE_BUILD_ARGS_FINAL="${IMAGE_BUILD_ARGS_FINAL} --cache-from \"type=local,src=${DOCKER_BUILDX_LOCAL_CACHE}\" "
		IMAGE_BUILD_ARGS_FINAL="${IMAGE_BUILD_ARGS_FINAL} --cache-to   \"type=local,dest=${DOCKER_BUILDX_LOCAL_CACHE}\" "
	fi

	if [[ "$DOCKER_BUILDX_REMOTE_CACHE_ENABLE" == "true" ]]; then
		IMAGE_BUILD_ARGS_FINAL="${IMAGE_BUILD_ARGS_FINAL} --cache-from \"type=registry,ref=${AWS_ECR_URL}/build-cache/${IMAGE_NAME}:cache\" "
		IMAGE_BUILD_ARGS_FINAL="${IMAGE_BUILD_ARGS_FINAL} --cache-to   \"mode=max,image-manifest=true,oci-mediatypes=true,type=registry,ref=${AWS_ECR_URL}/build-cache/${IMAGE_NAME}:cache\" "
	fi

	if [[ -f "$DOCKER_BUILDX_CONFIGURE" ]]; then
		log "Executing $DOCKER_BUILDX_CONFIGURE."
		$DOCKER_BUILDX_CONFIGURE
	fi

	log "Packaging $IMAGE_PLATFORMS platform for ${IMAGE_NAME}:${VERSION}."
	cmd="docker buildx build
		--platform   $IMAGE_PLATFORMS
		-f           $DOCKER_FILE
		-t           ${AWS_ECR_URL}/${IMAGE_NAME}:${VERSION}
		--progress   plain
		$IMAGE_BUILD_ARGS_FINAL
		--load
		."

	log "Running command: $cmd"
	eval $cmd

	run_trivy_scan "${AWS_ECR_URL}/${IMAGE_NAME}:${VERSION}"

	publish_or_skip

	log "Finished packaging and publishing docker ${IMAGE_NAME}:${VERSION}"
}

function configure_dockerx () {
	if [[ -f "$DOCKER_BUILDX_CONFIGURE" ]]; then
		log "Executing $DOCKER_BUILDX_CONFIGURE."
		$DOCKER_BUILDX_CONFIGURE
	fi
}

function login_in_docker_registry () {
	log "Logging into aws and docker against $AWS_ECR_URL."

	if [[ $DOCKER_LOGIN_FORCE == false && $DOCKER_BUILDX_REMOTE_CACHE_ENABLE == false ]]; then
		log "Both DOCKER_LOGIN_FORCE and DOCKER_BUILDX_REMOTE_CACHE_ENABLE variables are set to false. Skipping."
		return
	fi

	HISTCONTROL_BAK=$HISTCONTROL
	HISTCONTROL=ignoreboth
	printf "%s\n%s\n$AWS_REGION\njson" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" | aws configure --profile tmp-profile
	aws ecr get-login-password --profile tmp-profile
	docker login $AWS_ECR_URL --username AWS --password $(aws ecr get-login-password --profile tmp-profile)
	HISTCONTROL=$HISTCONTROL_BAK
}


login_in_docker_registry

log "Started packaging and publishing docker images."

IMAGE_BUILD_ARGS="${IMAGE_BUILD_ARGS} --build-arg APP_NAME=${APP_NAME:-''} "

if [[ -z ${IMAGE_PLATFORMS+x} || -z ${IMAGE_PLATFORMS} ]]; then
	log "No IMAGE_PLATFORMS has been defined. Using simple docker build."
	package_and_publish_docker
else
	configure_dockerx
	package_and_publish_dockerx
fi

log "Finished packaging and publishing docker images."
