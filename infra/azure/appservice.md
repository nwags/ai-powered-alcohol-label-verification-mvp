# Azure App Service (Custom Linux Container)

This app is deployment-ready as a custom Linux container for Azure App Service.

## Required App Settings

Set these in the Web App configuration:

- `WEBSITES_PORT=8000`
- `HOST=0.0.0.0`
- `PORT=8000`
- `APP_ENV=production`
- `LOG_LEVEL=INFO`
- `STORAGE_DIR=/home/site/wwwroot/data`
- `ENABLE_OCR=true`
- `OCR_USE_GPU=false`
- `OCR_MAX_DIMENSION=2200`
- `OCR_MAX_VARIANTS=3`
- `OCR_ENABLE_DESKEW=false`

Notes:
- App Service routes traffic to the container port defined by `WEBSITES_PORT`.
- Keep `WEBSITES_PORT=8000` because this container listens on `0.0.0.0:8000`.
- Set health check path to `/healthz`.

## Health Check

Use App Service health checks against:

- `/healthz`

## Example Azure CLI Deployment

```bash
# 1) Variables
RG="alv-rg"
LOC="eastus"
PLAN="alv-plan"
APP="alv-prototype-app"
ACR="alvregistry"
IMAGE="alv-web:latest"

# 2) Resource group + Linux App Service plan
az group create -n "$RG" -l "$LOC"
az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku B1

# 3) Azure Container Registry
az acr create -g "$RG" -n "$ACR" --sku Basic
az acr build -r "$ACR" -t "$IMAGE" .

# 4) Create web app using custom container image
az webapp create \
  -g "$RG" \
  -p "$PLAN" \
  -n "$APP" \
  -i "${ACR}.azurecr.io/${IMAGE}"

# 5) Configure app settings and health check
az webapp config appsettings set \
  -g "$RG" \
  -n "$APP" \
  --settings WEBSITES_PORT=8000 HOST=0.0.0.0 PORT=8000 APP_ENV=production LOG_LEVEL=INFO STORAGE_DIR=/home/site/wwwroot/data ENABLE_OCR=true OCR_USE_GPU=false OCR_MAX_DIMENSION=2200 OCR_MAX_VARIANTS=3 OCR_ENABLE_DESKEW=false

az webapp config set \
  -g "$RG" \
  -n "$APP" \
  --health-check-path /healthz

# 6) Optional: show default hostname
az webapp show -g "$RG" -n "$APP" --query defaultHostName -o tsv
```

## Updating an Existing Deployment

```bash
az acr build -r "$ACR" -t "$IMAGE" .
az webapp config container set \
  -g "$RG" \
  -n "$APP" \
  --container-image-name "${ACR}.azurecr.io/${IMAGE}"
```
