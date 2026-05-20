#!/usr/bin/env bash
set -e

log () {
  echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

AWS_ECR_URL=${AWS_ECR_URL_NEA:-942117878223.dkr.ecr.ap-northeast-1.amazonaws.com}
AWS_REGION=${AWS_DEFAULT_REGION_CI:-ap-northeast-1}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID_CI:-""}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY_CI:-""}

log "Logging into aws and docker against $AWS_ECR_URL."

HISTCONTROL_BAK=$HISTCONTROL
HISTCONTROL=ignoreboth

printf "%s\n%s\n$AWS_REGION\njson" "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" | aws configure --profile tmp-profile
aws ecr get-login-password --profile tmp-profile
docker login $AWS_ECR_URL --username AWS --password $(aws ecr get-login-password --profile tmp-profile)

HISTCONTROL=$HISTCONTROL_BAK
