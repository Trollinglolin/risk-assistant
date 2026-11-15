#!/usr/bin/env bash
# Turn the hosted app on or off to save Azure credit.
#
#   infra/azure/hosting.sh status   # running state, replicas, URL
#   infra/azure/hosting.sh off      # stop the app: no replicas, no compute charges, site offline
#   infra/azure/hosting.sh off --delete-registry
#                                   # also delete the container registry (the only remaining
#                                   # cost, ~USD 0.17/day); bring it back with deploy.sh
#   infra/azure/hosting.sh on       # start it again (first request then takes ~30-60 s)
#
# "off" stops the Container App itself (REST stop action), so nothing, not even a visitor,
# can wake it. The container registry (Basic, about USD 0.17/day) keeps the image so "on" is
# instant; delete it only if you also want that cost gone (redeploy with deploy.sh after).
set -euo pipefail

RG=${RG:-rg-hkrisk}
APP=${APP:-hkrisk}
SUB_HASH=$(az account show --query id -o tsv | shasum | cut -c1-6)
ACR=${ACR:-hkrisk${SUB_HASH}}
API=2024-03-01
ID=$(az containerapp show -n "$APP" -g "$RG" --query id -o tsv)
URL="https://$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)"

state() {
  az containerapp show -n "$APP" -g "$RG" --query properties.runningStatus -o tsv
}

wait_for() {  # wait until runningStatus matches $1
  for _ in $(seq 1 60); do
    [ "$(state)" = "$1" ] && return 0
    sleep 5
  done
  echo "timed out waiting for $1 (now: $(state))" >&2
  return 1
}

case "${1:-status}" in
  off)
    az rest --method post --url "https://management.azure.com$ID/stop?api-version=$API" -o none
    wait_for Stopped
    echo "OFF: $APP is stopped. No compute charges; $URL is offline."
    if [ "${2:-}" = "--delete-registry" ]; then
      if az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null; then
        az acr delete -n "$ACR" -g "$RG" --yes -o none
        echo "registry $ACR deleted: nothing in $RG is billing now."
        echo "to come back: colima start, then infra/azure/deploy.sh (rebuilds), then hosting.sh on"
      else
        echo "registry $ACR already deleted"
      fi
    fi
    ;;
  on)
    if ! az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null; then
      echo "the container registry was deleted (off --delete-registry), so there is no image." >&2
      echo "run: colima start && infra/azure/deploy.sh   (rebuilds and pushes), then: $0 on" >&2
      exit 1
    fi
    az rest --method post --url "https://management.azure.com$ID/start?api-version=$API" -o none
    wait_for Running
    echo "ON: $APP is running. Waking it up (scale from zero)..."
    for _ in $(seq 1 24); do
      code=$(curl -s -o /dev/null -m 30 -w '%{http_code}' "$URL/health" || true)
      [ "$code" = 200 ] && { echo "live: $URL"; exit 0; }
      sleep 5
    done
    echo "started, but $URL/health is not answering yet; try again in a minute"
    ;;
  status)
    az containerapp show -n "$APP" -g "$RG" -o table --query \
      "{app:name, status:properties.runningStatus, minReplicas:properties.template.scale.minReplicas, maxReplicas:properties.template.scale.maxReplicas}"
    az containerapp replica list -n "$APP" -g "$RG" --query "length(@)" -o tsv 2>/dev/null \
      | xargs -I{} echo "active replicas: {}"
    echo "url: $URL"
    az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null \
      && echo "registry: $ACR (exists, ~USD 0.17/day)" \
      || echo "registry: deleted (run deploy.sh before 'on')"
    ;;
  *)
    echo "usage: $0 on|off|status" >&2
    exit 2
    ;;
esac
