# RuriSkry — Deployment Runbook

Everything needed to go from zero to a fully live system.

---

## Architecture Overview

RuriSkry is **two deployable units** — a FastAPI backend and a React dashboard.
All agents (governance + operational) run in-process inside the backend container.
No separate agent services exist.

```
React dashboard  →  Azure Static Web Apps   (dashboard/)
FastAPI backend  →  Azure Container Apps    (src/)
LLM / Search / Cosmos / Key Vault  →  already provisioned by Terraform
```

---

## What Terraform Provisions

`infrastructure/terraform-core/` manages all Azure resources in one apply:

| Resource | Name pattern | Purpose |
|----------|-------------|---------|
| Resource Group | `ruriskry-rg` | Container for all resources |
| Log Analytics | `ruriskry-log-<suffix>` | Container + infra logs |
| Key Vault | `ruriskry-kv-<suffix>` | Runtime secrets (API keys) |
| Azure AI Foundry | `ruriskry-foundry-<suffix>` | GPT-4.1 LLM |
| Azure AI Search | `ruriskry-search-<suffix>` | Historical incident BM25 |
| Cosmos DB | `ruriskry-cosmos-<suffix>` | Audit trail + agent registry |
| Container Registry | `ruriskry<suffix>` | Docker image store |
| Container Apps Env | `ruriskry-env-<suffix>` | Managed runtime environment |
| Container App | `ruriskry-backend-<suffix>` | FastAPI + all agents |
| Static Web App | `ruriskry-dashboard-<suffix>` | React dashboard (global CDN) |

---

## Prerequisites

- Azure CLI — `az login` completed
- Terraform 1.5+
- Docker Desktop running
- Node.js 18+ (for dashboard build)
- Python 3.11+ (for seeding + local dev)
- Register the Container Apps provider (one-time per subscription):

```bash
az provider register --namespace Microsoft.App --wait
```

---

## First-Time Deploy

### 1. Configure tfvars

```bash
cd infrastructure/terraform-core
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars` — mandatory fields:

```hcl
subscription_id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
suffix          = "yourname"   # globally unique — used in all resource names
```

Optional but recommended before first apply:

```hcl
iac_github_repo    = "owner/repo"                  # for Execution Gateway PR creation
iac_terraform_path = "infrastructure/terraform-prod"
dashboard_url      = ""                            # fill in after SWA deploy (see step 5)
```

### 2. Apply infrastructure

```bash
terraform init
terraform validate
terraform apply
```

Terraform prints a `next_steps` output with real URLs and names after apply completes.

### 3. Store GitHub PAT in Key Vault

Required for the Execution Gateway (Terraform PR creation). Skip if not using it.

```bash
az keyvault secret set \
  --vault-name ruriskry-kv-<suffix> \
  --name github-pat \
  --value "github_pat_xxx..."
```

Then in `terraform.tfvars` set `use_github_pat = true` and re-apply:

```bash
terraform apply
```

### 4. Seed the AI Search index

Required for `HistoricalPatternAgent` to find incidents in live mode.
Run from the repo root:

```bash
cd ../..
python scripts/seed_data.py
```

Expected output: `Uploaded 7/7 incidents`

### 5. Build and push the backend Docker image

Run from the repo root (where `Dockerfile` lives):

```bash
az acr login --name ruriskry<suffix>
docker build -t ruriskry<suffix>.azurecr.io/ruriskry-backend:latest .
docker push ruriskry<suffix>.azurecr.io/ruriskry-backend:latest
```

The Container App will pull the new image automatically on its next revision.
Force an immediate update:

```bash
az containerapp update \
  --name ruriskry-backend-<suffix> \
  --resource-group ruriskry-rg \
  --image ruriskry<suffix>.azurecr.io/ruriskry-backend:latest
```

Verify the backend is live:

```bash
curl https://ruriskry-backend-<suffix>.<region>.azurecontainerapps.io/health
# → {"status": "ok"}
```

### 6. Build and deploy the React dashboard

```bash
# Get the backend URL
cd infrastructure/terraform-core
terraform output backend_url

# Create dashboard/.env.production with the real backend URL
echo "VITE_API_URL=https://ruriskry-backend-<suffix>.<region>.azurecontainerapps.io" \
  > ../../dashboard/.env.production

# Build
cd ../../dashboard
npm install
npm run build

# Get deployment token
cd ../infrastructure/terraform-core
terraform output -raw dashboard_deployment_token

# Deploy
cd ../../dashboard
npx @azure/static-web-apps-cli deploy ./dist --deployment-token <token>
```

Dashboard is live at the URL printed by `terraform output dashboard_url`.

### 7. Wire the dashboard URL back

Once you have the Static Web App URL, add it to `terraform.tfvars`:

```hcl
dashboard_url = "https://ruriskry-dashboard-<suffix>.azurestaticapps.net"
```

Then re-apply so the Container App picks it up for Teams notification cards:

```bash
cd infrastructure/terraform-core
terraform apply
```

### 8. Generate local .env (for local development)

```bash
cd ../..
bash scripts/setup_env.sh
```

This writes endpoints and Key Vault secret names to `.env` from Terraform outputs.

---

## Redeploy Workflows

### Backend code changed

```bash
# From repo root
docker build -t ruriskry<suffix>.azurecr.io/ruriskry-backend:latest .
docker push ruriskry<suffix>.azurecr.io/ruriskry-backend:latest

az containerapp update \
  --name ruriskry-backend-<suffix> \
  --resource-group ruriskry-rg \
  --image ruriskry<suffix>.azurecr.io/ruriskry-backend:latest
```

### Dashboard changed

```bash
cd dashboard
npm run build
npx @azure/static-web-apps-cli deploy ./dist \
  --deployment-token $(cd ../infrastructure/terraform-core && terraform output -raw dashboard_deployment_token)
```

### Infrastructure changed (tfvars / main.tf)

```bash
cd infrastructure/terraform-core
terraform validate
terraform plan
terraform apply
```

---

## Validation Checklist

After a fresh deploy, verify each layer:

```bash
# 1. Terraform state is clean
cd infrastructure/terraform-core
terraform state list
terraform output

# 2. Key Vault secrets are accessible
KV=ruriskry-kv-<suffix>
az keyvault secret show --vault-name $KV --name foundry-primary-key --query id -o tsv
az keyvault secret show --vault-name $KV --name search-primary-key  --query id -o tsv
az keyvault secret show --vault-name $KV --name cosmos-primary-key  --query id -o tsv

# 3. Backend health
curl https://ruriskry-backend-<suffix>.<region>.azurecontainerapps.io/health

# 4. Container App logs (if something looks wrong)
az containerapp logs show \
  --name ruriskry-backend-<suffix> \
  --resource-group ruriskry-rg \
  --follow

# 5. Search index seeded
python scripts/seed_data.py

# 6. Run test suite locally
pytest tests/ -v
```

---

## Teardown

Deletes all Terraform-managed resources. Use after a demo to stop charges.

```bash
cd infrastructure/terraform-core
terraform destroy
```

The mini prod environment (`infrastructure/terraform-prod/`) has its own teardown:

```bash
cd infrastructure/terraform-prod
terraform destroy
```

---

## Cost Notes

Resources that incur cost while running:

| Resource | Approximate cost |
|----------|-----------------|
| Container App (1 replica, 1 vCPU / 2 GiB) | ~$35/month |
| Azure AI Foundry (GPT-4.1 GlobalStandard) | Pay-per-token |
| Azure AI Search (free tier) | $0 |
| Cosmos DB (free tier) | $0 |
| Static Web App (free tier) | $0 |
| Container Registry (Basic) | ~$5/month |

Set `backend_min_replicas = 0` in `terraform.tfvars` + re-apply to scale to zero
between demos (cold start ~10–15 s on first request).
