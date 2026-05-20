#!/usr/bin/env bash
set -e

mkdir -p ~/.kube/
rm -f ~/.kube/config

echo "$KUBE_CLUSTER_CONFIG" | base64 -d > ~/.kube/config
chmod 600 ~/.kube/config

kubectl config use-context $KUBE_CLUSTER_NAME
