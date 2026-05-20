#!/usr/bin/env bash
# This script is intented only for use by Bitbucket pipelines.
# It is just an intermediary between the pipeline and the base
# deploy scripts.
#
set -e

echo "Executing `basename "$0"`"
source ./.pipelines/deploy.sh rollback

echo "Successfully finished."
