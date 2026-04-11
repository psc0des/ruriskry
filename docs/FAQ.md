# RuriSkry — Frequently Asked Questions

Common questions that come up after a fresh deployment.

---

## Deployment

**Q: The dashboard shows "Congratulations on your new site!" instead of RuriSkry.**

`deploy.sh` provisions the Static Web App but the dashboard build/deploy step hasn't
finished yet. Wait for the script to complete — the React build takes 2–3 minutes after
infrastructure apply. If the script exited early, run the dashboard deploy manually:

```bash
BACKEND_URL="https://ruriskry-core-backend-<suffix>.<hash>.eastus2.azurecontainerapps.io"
echo "VITE_API_URL=$BACKEND_URL" > dashboard/.env.production
cd dashboard && npm ci && npm run build && cd ..

cd infrastructure/terraform-core
DEPLOY_TOKEN=$(terraform output -raw dashboard_deployment_token)
cd ../../dashboard
npx @azure/static-web-apps-cli deploy ./dist \
  --deployment-token "$DEPLOY_TOKEN" \
  --env production
```

---

**Q: `deploy.sh` exited silently partway through — no error, just returned to the prompt.**

A known issue fixed in `d8adc59`. Pull the latest and re-run. If you're already past the
infrastructure stage, use `--stage2` to skip the Docker build and Terraform apply:

```bash
git pull
bash scripts/deploy.sh --stage2
```

---

**Q: I got a `FlagMustBeSetForRestore` or `409 Conflict` error on a retry deploy.**

Azure soft-deletes Cognitive Services accounts and Key Vaults when a resource group is
deleted. A retry deploy can't recreate them until they're purged. `deploy.sh` handles
this automatically in the pre-flight step — if you see this error, run the cleanup
script first:

```bash
bash scripts/cleanup.sh      # deletes RG + purges soft-deleted resources
bash scripts/deploy.sh       # fresh deploy
```

---

**Q: How do I do a completely clean re-deploy?**

```bash
bash scripts/cleanup.sh        # keeps tfstate storage (faster re-deploy)
bash scripts/cleanup.sh --all  # full wipe including tfstate (use if changing suffix)
bash scripts/deploy.sh
```

---

## After Deploy

**Q: The Connected Agents page says "No agents registered yet."**

Expected on a fresh deployment. Agents self-register in Cosmos DB the first time a scan
runs — they are not separate processes that need to be started manually. Go to the
**Scans** tab and trigger any scan. After it completes, the Connected Agents page will
show all three agents.

`python examples/demo_a2a.py` is a local development script — it is not needed or relevant in a
live cloud deployment.

---

**Q: The Alerts tab is empty but Azure Monitor alerts are firing and I'm getting emails.**

The email alerts go through a different action group. The RuriSkry Action Group was
created by Terraform but no alert rules point to it yet.

`deploy.sh` Step 9 handles this automatically — it sweeps your `target_subscription_id`
for all existing alert rules and offers to add the RuriSkry Action Group. If you skipped
that step, wire them manually:

```bash
ACTION_GROUP_ID=$(cd infrastructure/terraform-core && terraform output -raw alert_action_group_id)

# List your alert rules first
az monitor metrics alert list \
  --subscription <target-subscription-id> -o table

# Wire each rule
az monitor metrics alert update \
  --name "<rule-name>" \
  --resource-group "<rg>" \
  --subscription "<target-subscription-id>" \
  --add-action "$ACTION_GROUP_ID"
```

Note: alert rules live in your **target** (workload) subscription, not the subscription
where RuriSkry is deployed.

---

## Scoring

**Q: The Historical score is 0 on my first scan. Is something broken?**

No — this is correct. The SRI:Historical dimension (25% of the composite score) searches
for similar past incidents. On a fresh deployment there are none, so the score is 0.

This does **not** cause wrong decisions. A score of 0 means "no historical evidence of
risk" — which lowers the composite slightly (more permissive). The system self-corrects
through two mechanisms:

1. **Governance history boost** (automatic) — after a few scans, RuriSkry checks its own
   past decisions in Cosmos DB. If the same action type has been escalated before, it adds
   a deterministic +25 boost. No setup needed — this starts working after your first scan.

2. **Incident data** — `data/seed_incidents.json` contains 7 demo incidents for local
   development. Skip seeding in production — the governance history boost is the real
   production signal. If you later integrate a real incident system (PagerDuty, ServiceNow),
   upload those incidents to Azure AI Search instead.

---

**Q: Why does the same resource get a different score on different scans?**

Three sources of variance are expected and intentional:

1. **LLM adjustments** — each governance agent calls the LLM to adjust the baseline score
   by ±30 points. LLMs are non-deterministic — the same input can produce slightly different
   reasoning each run.
2. **Azure AI Search BM25** — the relevance ranking of historical incidents can vary
   slightly across queries.
3. **Live infrastructure state** — metrics, tags, and topology change between scans.

The governance history boost in `HistoricalPatternAgent` is deliberately deterministic to
keep scores stable across runs despite the above variance.

---

**Q: An action was APPROVED but it looks risky. How do I make RuriSkry stricter?**

Lower the approval threshold in `terraform.tfvars` (or `.env`):

```
# Default: actions with SRI < 25 are auto-approved
# Set lower to make fewer actions auto-approve:
SRI_AUTO_APPROVE_THRESHOLD=15   # environment variable
```

Or tighten the human-review threshold (currently 60) to force more escalations instead
of auto-denials:

```
SRI_HUMAN_REVIEW_THRESHOLD=50
```

For persistent risky actions, add a policy to `data/policies.json` — the PolicyAgent
enforces these as hard rules with optional LLM override control.

---

## Infrastructure

**Q: Azure AI Search provisioning failed with "InsufficientResourcesAvailable".**

The free-tier AI Search capacity in `eastus2` is frequently exhausted. The `search_location`
variable defaults to `"eastus"` (separate from the main `location = "eastus2"`) to avoid
this. If `eastus` is also unavailable, set an alternative in `terraform.tfvars`:

```hcl
search_location = "westus2"    # or: westeurope, canadacentral
```

---

**Q: The Foundry quota check says my quota is 0 but I can see the model in the Azure portal.**

Azure uses different key names for quota lookup vs deployment names. For `gpt-4.x` models
the quota key drops the hyphen before the version digit:
- Deployment name: `gpt-4.1-mini`
- Quota key: `gpt4.1-mini` (no hyphen before `4`)

`deploy.sh` handles this automatically with a fallback key lookup. If you're checking
manually:

```bash
az cognitiveservices usage list --location eastus2 \
  --subscription <sub-id> \
  --query "[?contains(name.value,'gpt4')].{key:name.value,limit:limit}" \
  -o table
```

---

**Q: How do I upgrade from gpt-4.1-mini to gpt-5-mini?**

`gpt-5-mini` on GlobalStandard requires a manual quota request on new subscriptions:

1. Go to `https://ai.azure.com/quota` → select your region → find `gpt-5-mini GlobalStandard`
2. Request increase → enter `3` (= 30,000 TPM minimum)
3. Once approved, update `terraform.tfvars`:

```hcl
foundry_model           = "gpt-5-mini"
foundry_model_version   = "2025-08-07"
foundry_deployment_name = "gpt-5-mini"
foundry_scale_type      = "GlobalStandard"
foundry_capacity        = 30
```

4. Apply: `terraform -chdir=infrastructure/terraform-core apply`
