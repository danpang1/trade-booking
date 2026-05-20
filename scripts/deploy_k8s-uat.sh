#!/usr/bin/env bash
set -e

log () {
  echo "[`date '+%Y-%m-%d %H:%M:%S (%z)'`] $@"
}

mode=${1:-deploy}
env=uat

log "Executing `basename "$0"`."

# Here add the instances, you want them deployed in this environment, using the following format and example.
#
# ./scripts/run_helm.sh namespace service instance [env=test] [mode=deploy] [chart_location=./helm]
#
# E.g.
#  The following will deploy an application with name `<namespace>-<application>-<instance>-<environment>`.
#
# ./scripts/run_helm.sh namespace application instance $env $mode
#
#  It will pick up values from the ./helm_values/ folder based on the ./scripts/utils.sh rules. For a
#  simple configuration, it will pick up the following files:
#    * ./helm_values/base.yaml
#    * ./helm_values/base-<env>.yaml
#    * ./helm_values/<application>/base.yaml
#    * ./helm_values/<application>/base-<environment>.yaml
#    * ./helm_values/<application>/<instance>.yaml
#    * ./helm_values/<application>/<instance>-<environment>.yaml
#
# Remove this. This is an example...
./scripts/run_helm.sh example-namespace example-app example-instance $env $mode

log "Successfully finished."
