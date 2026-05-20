#!/usr/bin/env bash
# This script is intented only for use by Bitbucket pipelines.
# It is just an intermediary between the pipeline and the base
# deploy scripts.
#
set -e
mode=${1:-deploy}

echo "Executing `basename "$0"`"

if [[ -z ${ENVIRONMENT+x} || -z ${ENVIRONMENT} ]]; then
  for e in ${ENVIRONMENTS//,/ }; do
    env=${e//-/_}

    KUBE_CLUSTER_NAME_var=KUBE_CLUSTER_NAME_${env}
    KUBE_CLUSTER_CONFIG_var=KUBE_CLUSTER_CONFIG_${env}

    KUBE_CLUSTER_NAME=${!KUBE_CLUSTER_NAME_var}
    KUBE_CLUSTER_CONFIG=${!KUBE_CLUSTER_CONFIG_var}
    ENVIRONMENT=$e

    echo "Deploying to $ENVIRONMENT environment."

    source ./.pipelines/prepare-kubectl.sh
    source ./scripts/deploy_k8s-${ENVIRONMENT}.sh $mode

    sleep 1
  done

else
  echo "Deploying to $ENVIRONMENT environment."

  source ./.pipelines/prepare-kubectl.sh
  source ./scripts/deploy_k8s-${ENVIRONMENT}.sh $mode
fi

echo "Successfuly finished."
