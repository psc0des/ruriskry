# =============================================================================
# RuriSkry - Azure Infrastructure (Foundry Only)
# =============================================================================
# This configuration manages Foundry (AIServices) as the only LLM platform.
# =============================================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.58"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

data "azurerm_client_config" "current" {}

locals {
  name_suffix = var.suffix

  common_tags = {
    project     = "ruriskry"
    environment = var.env
    managed_by  = "terraform"
  }

  default_foundry_name = "ruriskry-foundry-${local.name_suffix}"
  foundry_account_name = var.foundry_account_name != "" ? var.foundry_account_name : local.default_foundry_name
  foundry_subdomain    = var.foundry_custom_subdomain_name != "" ? var.foundry_custom_subdomain_name : local.foundry_account_name
}

# =============================================================================
# 1. Resource Group
# =============================================================================

resource "azurerm_resource_group" "ruriskry" {
  name     = var.resource_group_name
  location = var.location
  tags     = local.common_tags
}

# =============================================================================
# 2. Log Analytics Workspace
# =============================================================================

resource "azurerm_log_analytics_workspace" "ruriskry" {
  name                = "ruriskry-log-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.ruriskry.name
  location            = azurerm_resource_group.ruriskry.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.common_tags
}

# =============================================================================
# 3. Azure Key Vault
# =============================================================================

resource "azurerm_key_vault" "ruriskry" {
  name                = "ruriskry-kv-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.ruriskry.name
  location            = azurerm_resource_group.ruriskry.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    secret_permissions = [
      "Backup", "Delete", "Get", "List", "Purge", "Recover", "Restore", "Set"
    ]
  }

  tags = local.common_tags
}

resource "azurerm_key_vault_access_policy" "managed_identity_readers" {
  for_each = toset(var.managed_identity_principal_ids)

  key_vault_id = azurerm_key_vault.ruriskry.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = each.value

  secret_permissions = ["Get", "List"]
}

# =============================================================================
# 4. Foundry (AIServices)
# =============================================================================

resource "azurerm_ai_services" "foundry" {
  name                               = local.foundry_account_name
  custom_subdomain_name              = local.foundry_subdomain
  resource_group_name                = azurerm_resource_group.ruriskry.name
  location                           = var.foundry_location
  sku_name                           = "S0"
  local_authentication_enabled       = true
  public_network_access              = "Enabled"
  outbound_network_access_restricted = false
  tags                               = local.common_tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_account_project" "foundry" {
  count                = var.create_foundry_project ? 1 : 0
  name                 = var.foundry_project_name
  location             = var.foundry_location
  cognitive_account_id = azurerm_ai_services.foundry.id
  tags                 = local.common_tags

  identity {
    type = "SystemAssigned"
  }
}

resource "azurerm_cognitive_deployment" "foundry_primary" {
  count                = var.create_foundry_deployment ? 1 : 0
  name                 = var.foundry_deployment_name
  cognitive_account_id = azurerm_ai_services.foundry.id

  model {
    format  = "OpenAI"
    name    = var.foundry_model
    version = var.foundry_model_version != "" ? var.foundry_model_version : null
  }

  sku {
    name     = var.foundry_scale_type
    capacity = var.foundry_capacity
  }
}

# =============================================================================
# 5. Azure AI Search
# =============================================================================

resource "azurerm_search_service" "ruriskry" {
  name                = "ruriskry-search-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.ruriskry.name
  location            = azurerm_resource_group.ruriskry.location
  sku                 = var.search_sku

  replica_count   = var.search_sku == "free" ? null : 1
  partition_count = var.search_sku == "free" ? null : 1

  tags = local.common_tags
}

# =============================================================================
# 6. Cosmos DB (SQL API)
# =============================================================================

resource "azurerm_cosmosdb_account" "ruriskry" {
  name                = "ruriskry-cosmos-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.ruriskry.name
  location            = var.cosmos_location
  offer_type          = "Standard"
  kind                = "GlobalDocumentDB"

  consistency_policy {
    consistency_level = "Session"
  }

  geo_location {
    location          = var.cosmos_location
    failover_priority = 0
    zone_redundant    = false
  }

  free_tier_enabled = var.cosmos_free_tier
  tags              = local.common_tags
}

resource "azurerm_cosmosdb_sql_database" "ruriskry" {
  name                = "ruriskry"
  resource_group_name = azurerm_resource_group.ruriskry.name
  account_name        = azurerm_cosmosdb_account.ruriskry.name
}

resource "azurerm_cosmosdb_sql_container" "governance_decisions" {
  name                = "governance-decisions"
  resource_group_name = azurerm_resource_group.ruriskry.name
  account_name        = azurerm_cosmosdb_account.ruriskry.name
  database_name       = azurerm_cosmosdb_sql_database.ruriskry.name

  partition_key_paths   = ["/resource_id"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

resource "azurerm_cosmosdb_sql_container" "governance_agents" {
  name                = "governance-agents"
  resource_group_name = azurerm_resource_group.ruriskry.name
  account_name        = azurerm_cosmosdb_account.ruriskry.name
  database_name       = azurerm_cosmosdb_sql_database.ruriskry.name

  partition_key_paths   = ["/name"]
  partition_key_version = 2

  indexing_policy {
    indexing_mode = "consistent"

    included_path {
      path = "/*"
    }
  }
}

# =============================================================================
# 7. Key Vault secrets (service credentials)
# =============================================================================
# (existing Key Vault secrets below — see section 8+ for new resources)
# =============================================================================

resource "azurerm_key_vault_secret" "foundry_primary_key" {
  name         = var.keyvault_secret_name_foundry_key
  value        = azurerm_ai_services.foundry.primary_access_key
  key_vault_id = azurerm_key_vault.ruriskry.id

  depends_on = [azurerm_key_vault_access_policy.managed_identity_readers]
}

resource "azurerm_key_vault_secret" "search_primary_key" {
  name         = var.keyvault_secret_name_search_key
  value        = azurerm_search_service.ruriskry.primary_key
  key_vault_id = azurerm_key_vault.ruriskry.id

  depends_on = [azurerm_key_vault_access_policy.managed_identity_readers]
}

resource "azurerm_key_vault_secret" "cosmos_primary_key" {
  name         = var.keyvault_secret_name_cosmos_key
  value        = azurerm_cosmosdb_account.ruriskry.primary_key
  key_vault_id = azurerm_key_vault.ruriskry.id

  depends_on = [azurerm_key_vault_access_policy.managed_identity_readers]
}

# GitHub PAT is stored manually in Key Vault — Terraform never touches the value.
# Run this once before setting use_github_pat = true in tfvars:
#   az keyvault secret set \
#     --vault-name ruriskry-kv-<suffix> \
#     --name github-pat \
#     --value "github_pat_xxx..."
# The Container App picks it up via its Managed Identity — no Terraform resource needed.

# =============================================================================
# 8. Azure Container Registry (ACR)
# =============================================================================
# Stores the Docker image for the FastAPI backend.
# Basic SKU is sufficient for a single-team / hackathon workload.
# Admin access is enabled so the Container App can pull without an external
# service principal — the admin password is passed as a Container App secret.

resource "azurerm_container_registry" "ruriskry" {
  name                = "ruriskry${local.name_suffix}"
  resource_group_name = azurerm_resource_group.ruriskry.name
  location            = azurerm_resource_group.ruriskry.location
  sku                 = "Basic"
  admin_enabled       = true
  tags                = local.common_tags
}

# =============================================================================
# 9. Container Apps Environment
# =============================================================================
# Shared managed environment for all Container Apps.
# Wired to the Log Analytics workspace so container logs appear in Azure Monitor.

resource "azurerm_container_app_environment" "ruriskry" {
  name                       = "ruriskry-env-${local.name_suffix}"
  resource_group_name        = azurerm_resource_group.ruriskry.name
  location                   = azurerm_resource_group.ruriskry.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.ruriskry.id
  tags                       = local.common_tags
}

# =============================================================================
# 10. Container App — FastAPI Backend
# =============================================================================
# Hosts the FastAPI app (src/api/dashboard_api.py) with ALL governance agents
# and operational agents running in-process.  No separate agent services.
#
# Key design:
#   - SystemAssigned managed identity → Key Vault Get/List access granted below
#   - Non-secret env vars set inline (endpoints, flags, timeouts)
#   - Secrets (ACR password) passed via Container App secret mechanism
#   - AZURE_KEYVAULT_URL env var lets secrets.py resolve API keys at runtime
#     using DefaultAzureCredential (Managed Identity in Azure, az login locally)
#
# Before first deploy, build and push the image:
#   docker build -t <acr_login_server>/ruriskry-backend:latest .
#   az acr login --name <acr_name>
#   docker push <acr_login_server>/ruriskry-backend:latest

resource "azurerm_container_app" "backend" {
  name                         = "ruriskry-backend-${local.name_suffix}"
  resource_group_name          = azurerm_resource_group.ruriskry.name
  container_app_environment_id = azurerm_container_app_environment.ruriskry.id
  revision_mode                = "Single"
  tags                         = local.common_tags

  identity {
    type = "SystemAssigned"
  }

  registry {
    server               = azurerm_container_registry.ruriskry.login_server
    username             = azurerm_container_registry.ruriskry.admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = azurerm_container_registry.ruriskry.admin_password
  }

  # GitHub PAT — read from Key Vault by URI via the Container App's Managed Identity.
  # The secret must be stored manually before setting use_github_pat = true.
  # Key Vault URI format: <vault_uri>secrets/<secret-name> (no trailing slash on vault_uri).
  dynamic "secret" {
    for_each = var.use_github_pat ? [1] : []
    content {
      name                = "github-pat"
      key_vault_secret_id = "${azurerm_key_vault.ruriskry.vault_uri}secrets/github-pat"
      identity            = "System"
    }
  }

  template {
    min_replicas = var.backend_min_replicas
    max_replicas = var.backend_max_replicas

    container {
      name   = "backend"
      image  = "${azurerm_container_registry.ruriskry.login_server}/${var.backend_image}"
      cpu    = var.backend_cpu
      memory = var.backend_memory

      # ── Core mode flags ──────────────────────────────────────────────────────
      env {
        name  = "USE_LOCAL_MOCKS"
        value = "false"
      }
      env {
        name  = "USE_LIVE_TOPOLOGY"
        value = "true"
      }

      # ── Azure service endpoints ───────────────────────────────────────────
      env {
        name  = "AZURE_KEYVAULT_URL"
        value = azurerm_key_vault.ruriskry.vault_uri
      }
      env {
        name  = "AZURE_OPENAI_ENDPOINT"
        value = azurerm_ai_services.foundry.endpoint
      }
      env {
        name  = "AZURE_OPENAI_DEPLOYMENT"
        value = var.foundry_deployment_name
      }
      env {
        name  = "COSMOS_ENDPOINT"
        value = azurerm_cosmosdb_account.ruriskry.endpoint
      }
      env {
        name  = "AZURE_SEARCH_ENDPOINT"
        value = "https://${azurerm_search_service.ruriskry.name}.search.windows.net"
      }
      env {
        name  = "AZURE_SUBSCRIPTION_ID"
        value = var.subscription_id
      }

      # ── LLM tuning ────────────────────────────────────────────────────────
      env {
        name  = "LLM_TIMEOUT"
        value = tostring(var.llm_timeout)
      }
      env {
        name  = "LLM_CONCURRENCY_LIMIT"
        value = tostring(var.llm_concurrency_limit)
      }

      # ── Execution gateway ─────────────────────────────────────────────────
      env {
        name  = "EXECUTION_GATEWAY_ENABLED"
        value = tostring(var.execution_gateway_enabled)
      }

      # ── Teams notifications ───────────────────────────────────────────────
      env {
        name  = "TEAMS_WEBHOOK_URL"
        value = var.teams_webhook_url
      }
      env {
        name  = "DASHBOARD_URL"
        value = var.dashboard_url
      }

      # ── Org context (risk triage) ─────────────────────────────────────────
      env {
        name  = "ORG_NAME"
        value = var.org_name
      }
      env {
        name  = "ORG_COMPLIANCE_FRAMEWORKS"
        value = var.org_compliance_frameworks
      }
      env {
        name  = "ORG_RISK_TOLERANCE"
        value = var.org_risk_tolerance
      }

      # ── Execution Gateway — IaC repo ──────────────────────────────────────
      env {
        name  = "IAC_GITHUB_REPO"
        value = var.iac_github_repo
      }
      env {
        name  = "IAC_TERRAFORM_PATH"
        value = var.iac_terraform_path
      }

      # ── GitHub PAT — injected from Key Vault secret (not a plain value) ────
      dynamic "env" {
        for_each = var.use_github_pat ? [1] : []
        content {
          name        = "GITHUB_TOKEN"
          secret_name = "github-pat"
        }
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

# Give the Container App's managed identity read access to Key Vault secrets.
# This allows DefaultAzureCredential (via Managed Identity) to resolve
# API keys at runtime — no secrets in env vars, no .env file in the container.

resource "azurerm_key_vault_access_policy" "backend_identity" {
  key_vault_id = azurerm_key_vault.ruriskry.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_container_app.backend.identity[0].principal_id

  secret_permissions = ["Get", "List"]

  depends_on = [azurerm_container_app.backend]
}

# =============================================================================
# 11. Static Web App — React Dashboard
# =============================================================================
# Hosts the compiled React dashboard (dashboard/dist/).
# Free tier: 100 GB bandwidth/month, custom domain, global CDN — sufficient
# for demos and light production use.
#
# Deployment: push to GitHub and use the deployment_token in a GitHub Actions
# workflow, OR deploy manually:
#   npm run build   (inside dashboard/)
#   npx @azure/static-web-apps-cli deploy ./dist \
#     --deployment-token $(terraform output -raw dashboard_deployment_token)

resource "azurerm_static_web_app" "dashboard" {
  name                = "ruriskry-dashboard-${local.name_suffix}"
  resource_group_name = azurerm_resource_group.ruriskry.name
  location            = var.static_web_app_location
  sku_tier            = "Free"
  sku_size            = "Free"
  tags                = local.common_tags
}
