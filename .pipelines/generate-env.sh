#!/usr/bin/env bash
set -e

echo "BITBUCKET_BUILD_NUMBER: $BITBUCKET_BUILD_NUMBER"
echo "BITBUCKET_BRANCH: $BITBUCKET_BRANCH"
echo "BITBUCKET_COMMIT: $BITBUCKET_COMMIT"

# Expected secrets as Bitbucket variables
#  * AWS_ACCESS_KEY_ID_CI
#  * AWS_SECRET_ACCESS_KEY_CI
#  * RANCHER_KUBE_CONFIG_CI
#    This is expected to be the base64 encoded full kubeconfig.

APP_NAME="trade-booking"

ENVIRONMENT=""
ENVIRONMENTS=""
IMAGE_NAME="templates/trade-booking"

# Leave it empty if you want the default "docker build" command to be used.
IMAGE_PLATFORMS="linux/amd64"
# if you want arm in=mage to build for rust
#IMAGE_PLATFORMS="linux/amd64"
DOCKER_BUILDX_LOCAL_CACHE_ENABLE=false
DOCKER_BUILDX_LOCAL_CACHE="/tmp/cache/buildx"
# Remote ECR cache + ECR login. Required when the pipeline runs
# *dockerBuildAndPublish so package_and_publish_docker.sh actually
# logs into ECR before pushing (see login_in_docker_registry()).
# Requires AWS_ACCESS_KEY_ID_CI / AWS_SECRET_ACCESS_KEY_CI / AWS_ECR_URL_NEA
# Bitbucket repo variables to be populated.
DOCKER_BUILDX_REMOTE_CACHE_ENABLE=true
DOCKER_LOGIN_FORCE=true

KUBE_CLUSTER_NAME=""
KUBE_CLUSTER_CONFIG=""

VERSION_BASE=$(find helm -type f -name Chart.yaml  | xargs grep -E "^appVersion.*:" | cut -d ':' -f 2 | tr -d '([:space:]|"'')')

if [[ "$BITBUCKET_BRANCH" == "master" || "$BITBUCKET_BRANCH" == "main" ]]; then
  APP_NAME="${APP_NAME}-prod"

  VERSION=$VERSION_BASE
  VERSION_PYPI=$VERSION_BASE

  # Single cluster setup
  ENVIRONMENT="prod"
  KUBE_CLUSTER_NAME="sg-rancher"
  KUBE_CLUSTER_CONFIG=$RANCHER_KUBE_CONFIG_SG_CLUSTER

  # For multi cluster deployment use the following setup.
  # ENVIRONMENT=""
  # ENVIRONMENTS="prod-nea-1,prod-euw-1"

  KUBE_CLUSTER_NAME_prod_nea_1="jp-rancher"
  KUBE_CLUSTER_CONFIG_prod_nea_1=$$RANCHER_KUBE_CONFIG_JP_CLUSTER

  KUBE_CLUSTER_NAME_prod_euw_1="eu-rancher"
  KUBE_CLUSTER_CONFIG_prod_euw_1=$$RANCHER_KUBE_CONFIG_EU_CLUSTER

elif [ "$BITBUCKET_BRANCH" == "uat" ]; then
  APP_NAME="${APP_NAME}-uat"
  ENVIRONMENT="uat"

  VERSION="$VERSION_BASE-uat"
  VERSION_PYPI="$VERSION_BASE.rc1"

  KUBE_CLUSTER_NAME="test-rancher"
  KUBE_CLUSTER_CONFIG=$RANCHER_KUBE_CONFIG_TEST_JP_CLUSTER

else
  git_latest_commit=${BITBUCKET_COMMIT:0:8}
  git_branch=$(echo "$BITBUCKET_BRANCH" | sed 's/[^a-zA-Z0-9]/_/g')

  APP_NAME="${APP_NAME}-${git_branch:0:20}"
  ENVIRONMENT="dev"

  VERSION="$VERSION_BASE-dev-$BITBUCKET_BUILD_NUMBER-$git_latest_commit"
  VERSION_PYPI="$VERSION_BASE.dev$BITBUCKET_BUILD_NUMBER"

  KUBE_CLUSTER_NAME="non-applicable"
  KUBE_CLUSTER_CONFIG="non-applicable"
fi

cat <<EOF >> setup_env.sh
#!/usr/bin/env bash

set -o xtrace

export APP_NAME=$APP_NAME

export ENVIRONMENT=$ENVIRONMENT
export ENVIRONMENTS=$ENVIRONMENTS
export VERSION=$VERSION
export VERSION_PYPI=$VERSION_PYPI

export IMAGE_NAME=$IMAGE_NAME
export IMAGE_PLATFORMS=$IMAGE_PLATFORMS

export DOCKER_BUILDX_LOCAL_CACHE_ENABLE=$DOCKER_BUILDX_LOCAL_CACHE_ENABLE
export DOCKER_BUILDX_LOCAL_CACHE=$DOCKER_BUILDX_LOCAL_CACHE
export DOCKER_BUILDX_REMOTE_CACHE_ENABLE=$DOCKER_BUILDX_REMOTE_CACHE_ENABLE
export DOCKER_LOGIN_FORCE=$DOCKER_LOGIN_FORCE

export KUBE_CLUSTER_NAME=$KUBE_CLUSTER_NAME
export KUBE_CLUSTER_CONFIG=$KUBE_CLUSTER_CONFIG

export KUBE_CLUSTER_NAME_prod_nea_1=$KUBE_CLUSTER_NAME_prod_nea_1
export KUBE_CLUSTER_CONFIG_prod_nea_1=$KUBE_CLUSTER_CONFIG_prod_nea_1

export KUBE_CLUSTER_NAME_prod_euw_1=$KUBE_CLUSTER_NAME_prod_euw_1
export KUBE_CLUSTER_CONFIG_prod_euw_1=$KUBE_CLUSTER_CONFIG_prod_euw_1

set +o xtrace
EOF
