# Azure Deployment (Canonical)

This is the canonical deployment guide for running the MVP on **Azure App Service (Linux custom container)**.

## 1) Deployment Target

- Azure App Service (Linux)
- Custom container image built from this repo
- Health endpoint: `/healthz`

## 2) Container Expectations

- Container listens on `0.0.0.0:8000`
- App Service setting must include: `WEBSITES_PORT=8000`

## 3) Recommended App Settings

Set in App Service configuration:

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

## 4) Storage and Runtime Notes

- App Service container filesystem outside persisted mount points can be ephemeral.
- Keep runtime artifacts under configured `STORAGE_DIR`.
- Large OCR workloads are CPU-sensitive; choose App Service SKU accordingly.

## 5) Practical CLI Flow (Example)

```bash
RG="alv-rg"
LOC="eastus"
PLAN="alv-plan"
APP="alv-prototype-app"
ACR="alvregistry"
IMAGE="alv-web:latest"

az group create -n "$RG" -l "$LOC"
az appservice plan create -g "$RG" -n "$PLAN" --is-linux --sku B1

az acr create -g "$RG" -n "$ACR" --sku Basic
az acr build -r "$ACR" -t "$IMAGE" .

az webapp create -g "$RG" -p "$PLAN" -n "$APP" -i "${ACR}.azurecr.io/${IMAGE}"

az webapp config appsettings set -g "$RG" -n "$APP" --settings \
  WEBSITES_PORT=8000 HOST=0.0.0.0 PORT=8000 APP_ENV=production LOG_LEVEL=INFO \
  STORAGE_DIR=/home/site/wwwroot/data ENABLE_OCR=true OCR_USE_GPU=false \
  OCR_MAX_DIMENSION=2200 OCR_MAX_VARIANTS=3 OCR_ENABLE_DESKEW=false

az webapp config set -g "$RG" -n "$APP" --health-check-path /healthz
```

## 6) Local vs Azure Differences

- Local Docker is the primary dev/test environment.
- Azure introduces resource throttling/SKU effects and persistent-storage configuration concerns.
- Keep expectations conservative: this remains an MVP deployment path, not a production hardening guide.

## 7) Related Files

- `infra/azure/appservice.md` (pointer/supplement)

