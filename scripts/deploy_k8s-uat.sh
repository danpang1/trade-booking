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
# One Helm release per workload, all under namespace `middle-office`:
#
#   trade-booking-server-<env>    (Deployment + Service + Ingress)
#   cron-counterparties-<env>     (1 CronJob)
#   cron-portfolios-<env>         (1 CronJob)
#   cron-tokens-<env>             (1 CronJob)
#   cron-users-<env>              (1 CronJob)
#
# Per-instance values come from helm_values/<service>/<instance>.yaml,
# auto-discovered by scripts/utils.sh.
./scripts/run_helm.sh middle-office trade-booking server         $env $mode

./scripts/run_helm.sh middle-office cron          counterparties $env $mode
./scripts/run_helm.sh middle-office cron          portfolios     $env $mode
./scripts/run_helm.sh middle-office cron          tokens         $env $mode
./scripts/run_helm.sh middle-office cron          users          $env $mode
./scripts/run_helm.sh middle-office cron          venue-snapshots $env $mode
./scripts/run_helm.sh middle-office cron          bitstamp-snapshots $env $mode
# UAT only — the 8041 recon board that consumes the LP rows lives in UAT.
# Deliberately absent from deploy_k8s-prod.sh.
./scripts/run_helm.sh middle-office cron          uniswap-lp-snapshots $env $mode

log "Successfully finished."
