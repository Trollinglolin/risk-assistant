#!/usr/bin/env bash
# Deploy the API + dashboard (one container) to Azure Container Apps.
#
#   az login && infra/azure/deploy.sh            # from the repo root; re-run to update
#
# Creates (idempotent): resource group, container registry (Basic), Container Apps
# environment (with Log Analytics) and one external Container App that scales to zero.
# Secrets (GEMINI_API_KEY, HKRISK_API_KEY) are read from .env and stored as Container Apps
# secrets; they are never printed, baked into the image or set as plain env vars.
set -euo pipefail

LOC=${LOC:-francecentral}            # Azure for Students allows only a few EU regions
ENV_LOC=${ENV_LOC:-germanywestcentral}  # students: max 1 Container Apps environment per region
RG=${RG:-rg-hkrisk}
ENV_NAME=${ENV_NAME:-hkrisk-env}
APP=${APP:-hkrisk}
SUB_HASH=$(az account show --query id -o tsv | shasum | cut -c1-6)
ACR=${ACR:-hkrisk${SUB_HASH}}
TAG=${TAG:-$(git rev-parse --short HEAD)$(git diff --quiet || echo -dirty)}
IMAGE="$ACR.azurecr.io/hkrisk-api:$TAG"

envval() {  # read a value from .env without echoing it
  python3 -c "from dotenv import dotenv_values; print(dotenv_values('.env').get('$1') or '')" 2>/dev/null \
    || uv run python -c "from dotenv import dotenv_values; print(dotenv_values('.env').get('$1') or '')"
}
GEMINI_KEY=$(envval GEMINI_API_KEY)
AGENT_KEY=$(envval HKRISK_API_KEY)
[ -n "$GEMINI_KEY" ] || { echo "GEMINI_API_KEY missing in .env"; exit 1; }
[ ${#AGENT_KEY} -ge 24 ] || { echo "HKRISK_API_KEY in .env must be >= 24 chars"; exit 1; }

echo "== resource group $RG ($LOC)"
az group create -n "$RG" -l "$LOC" -o none

echo "== registry $ACR"
az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null \
  || az acr create -n "$ACR" -g "$RG" -l "$LOC" --sku Basic --admin-enabled false -o none

echo "== image $IMAGE (linux/amd64)"
# BUILD=cloud (ACR Tasks; blocked on Azure for Students), BUILD=local (buildx + amd64
# emulation, needs `docker run --privileged --rm tonistiigi/binfmt:qemu-v9.2.2 --install amd64` once),
# or SKIP_BUILD=1 with TAG=<existing tag> to redeploy an image already in the registry.
if [ "${SKIP_BUILD:-0}" = 1 ]; then
  az acr repository show -n "$ACR" --image "hkrisk-api:$TAG" -o none
  echo "reusing existing image"
elif [ "${BUILD:-cloud}" = cloud ] && az acr build -r "$ACR" -t "hkrisk-api:$TAG" \
     --target api --platform linux/amd64 . -o none; then
  echo "built in ACR"
else
  echo "ACR build unavailable; building locally (amd64 emulation) and pushing"
  docker buildx build --platform linux/amd64 --target api -t "$IMAGE" --load .
  az acr login -n "$ACR"
  docker push "$IMAGE"
fi

# Azure for Students allows ONE Container Apps environment per subscription. To share an
# existing one, set ENV_ID to its resource id (the app stays in $RG and is isolated).
if [ -n "${ENV_ID:-}" ]; then
  echo "== using existing environment ${ENV_ID##*/}"
  ENV_REF=$ENV_ID
else
  echo "== container apps environment $ENV_NAME"
  az containerapp env show -n "$ENV_NAME" -g "$RG" -o none 2>/dev/null \
    || az containerapp env create -n "$ENV_NAME" -g "$RG" -l "$ENV_LOC" -o none \
         --environment-mode WorkloadProfiles  # Express mode cannot pull from ACR by identity
  ENV_REF=$ENV_NAME
fi

ENVVARS=(GEMINI_API_KEY=secretref:gemini-key HKRISK_API_KEY=secretref:agent-key
         LLM_PROVIDER=gemini LLM_MODEL=gemini-3.5-flash-lite LLM_RPM=15 LLM_TPM=250000
         LLM_RPD=500 HKRISK_TRUST_PROXY=1 HKRISK_DOCS=0)

if az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  echo "== update $APP"
  # (re)grant AcrPull to the app identity: needed after the registry was deleted to save
  # credit (hosting.sh off --delete-registry) and recreated above
  az containerapp registry set -n "$APP" -g "$RG" --server "$ACR.azurecr.io" \
    --identity system -o none
  az containerapp secret set -n "$APP" -g "$RG" \
    --secrets gemini-key="$GEMINI_KEY" agent-key="$AGENT_KEY" -o none
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" \
    --set-env-vars "${ENVVARS[@]}" -o none
else
  echo "== create $APP (system identity pulls from ACR; no registry passwords)"
  az containerapp create -n "$APP" -g "$RG" --environment "$ENV_REF" \
    --image "$IMAGE" --registry-server "$ACR.azurecr.io" --registry-identity system \
    --ingress external --target-port 8080 --transport auto \
    --cpu 1.0 --memory 2.0Gi --min-replicas 0 --max-replicas 2 \
    --scale-rule-name http --scale-rule-type http --scale-rule-http-concurrency 20 \
    --secrets gemini-key="$GEMINI_KEY" agent-key="$AGENT_KEY" \
    --env-vars "${ENVVARS[@]}" -o none
fi

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
STATUS=$(az containerapp show -n "$APP" -g "$RG" --query properties.runningStatus -o tsv)
echo "== deployed to https://$FQDN (app is $STATUS; start it with infra/azure/hosting.sh on)"
