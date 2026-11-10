#!/usr/bin/env bash
#
# Edge Delta API: create base pipeline and update with pipelines/edgedelta/*.yaml
# API ref: https://api.edgedelta.com/swagger/index.html
# Docs: https://docs.edgedelta.com/api-example/
#
# Prerequisites: ED_ORG_ID, ED_API_TOKEN, and (for update) PIPELINE_ID or use the ID
# returned from the create-base step.
#
# Auth: a static API token (Admin > API Tokens) goes in ED_API_TOKEN and is sent
# as X-ED-API-Token. An OAuth access token (a JWT, as produced by `edx auth
# login --oauth`) is sent as Authorization: Bearer instead — the API rejects
# JWTs in X-ED-API-Token. Set ED_API_TOKEN_CMD to a command that prints a token
# and it is re-evaluated per request, so a long run survives token expiry.
#

set -eo pipefail

CONFIG_FILE=$2
API_BASE="https://api.edgedelta.com"

# Retry failed calls a few times before giving up.
# --http1.1: a 57 s deploy on 10 Nov 2026 ended in curl exit 92, an HTTP/2 stream
# reset, after the body had arrived. --retry-all-errors: curl otherwise retries
# only transient HTTP codes and timeouts, so that reset was never retried. The
# calls here are safe to repeat: the same version deploys the same way.
CURL_RETRY=(--http1.1 --retry 3 --retry-delay 5 --retry-connrefused --retry-all-errors)

# ed_token prints the token to use for this request.
ed_token() {
  if [[ -n "${ED_API_TOKEN_CMD:-}" ]]; then
    eval "$ED_API_TOKEN_CMD"
  else
    printf '%s' "${ED_API_TOKEN:-}"
  fi
}

# auth_header picks the header scheme the token type requires.
auth_header() {
  local token
  token=$(ed_token)
  if [[ "$token" == eyJ* ]]; then
    printf 'Authorization: Bearer %s' "$token"
  else
    printf 'X-ED-API-Token: %s' "$token"
  fi
}

if [[ -f "pipeline_id.txt" ]]; then
  PIPELINE_ID=$(cat pipeline_id.txt)
fi

if [[ -n "${CONFIG_FILE}" ]]; then
  # YAML as JSON string for request bodies (content field)
  CONTENT_JSON=$(jq -Rs '.' < "$CONFIG_FILE")
fi

# -----------------------------------------------------------------------------
# 1. Create a base pipeline (optional – use when you want a new pipeline)
#    POST /v1/orgs/{ED_ORG_ID}/pipelines/base
#    Body: BaseConfCreateRequest (environment_type, fleet_subtype, etc.)
# -----------------------------------------------------------------------------
create_base_pipeline() {
  echo "Creating base pipeline..."
  PIPELINE_ID=$(curl -fsS "${CURL_RETRY[@]}" -X POST \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/pipelines/base" \
    -H "$(auth_header)" \
    -H "Content-Type: application/json" \
    -d "$(jq -n \
      --arg tag "http-benchmark" \
      --arg env "Linux" \
      --arg desc "HTTP benchmark pipeline" \
      '{tag: $tag, environment: $env, description: $desc}')" | jq -r '.id')
  [[ -n "$PIPELINE_ID" && "$PIPELINE_ID" != null ]] || { echo "Pipeline creation returned no ID" >&2; exit 1; }
  if [[ "${GITHUB_ACTIONS:-}" == true ]]; then echo "::add-mask::$PIPELINE_ID"; fi
  echo "Base pipeline created successfully"
  echo "$PIPELINE_ID" > pipeline_id.txt
  # Response includes pipeline id – capture it and set PIPELINE_ID for the next step.
}

# -----------------------------------------------------------------------------
# 2. Validate configuration (run before save)
#    POST /v1/orgs/{ED_ORG_ID}/confs/validate
# -----------------------------------------------------------------------------
validate_config() {
  echo "Validating configuration..."
  VALID=$(curl -fsS "${CURL_RETRY[@]}" -X POST \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/confs/validate" \
    -H "$(auth_header)" \
    -H "Content-Type: application/json" \
    -d "{\"content\": ${CONTENT_JSON}}" | jq -r '.valid')
  echo "Validation result: $VALID"
  if [[ "$VALID" != "true" ]]; then
    echo "Validation failed. Errors:"
    curl -fsS "${CURL_RETRY[@]}" -X POST \
      "${API_BASE}/v1/orgs/${ED_ORG_ID}/confs/validate" \
      -H "$(auth_header)" \
      -H "Content-Type: application/json" \
      -d "{\"content\": ${CONTENT_JSON}}" | jq .
    exit 1
  fi
}

# -----------------------------------------------------------------------------
# 3. Update pipeline with values from pipelines/edgedelta.yaml
#    POST /v1/orgs/{ED_ORG_ID}/pipelines/{conf_id}/save
# -----------------------------------------------------------------------------
update_pipeline() {
  if [[ -z "${PIPELINE_ID:-}" ]]; then
    echo "PIPELINE_ID is not set. Create a base pipeline first or set PIPELINE_ID (e.g. from pipeline URL in UI)."
    exit 1
  fi
  echo "Saving pipeline ${PIPELINE_ID} with content from edgedelta.yaml..."
  curl -fsS "${CURL_RETRY[@]}" -X POST \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/pipelines/${PIPELINE_ID}/save" \
    -H "$(auth_header)" \
    -H "Content-Type: application/json" \
    -d "{\"content\": ${CONTENT_JSON}}" | jq .
}

# -----------------------------------------------------------------------------
# 4. Get version history (to get version ID for deploy)
#    GET /v1/orgs/{ED_ORG_ID}/pipelines/{conf_id}/history
# ------------------------------------------------------------------------------
get_history() {
  if [[ -z "${PIPELINE_ID:-}" ]]; then
    echo "PIPELINE_ID is not set."
    exit 1
  fi
  curl -fsS "${CURL_RETRY[@]}" -X GET \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/pipelines/${PIPELINE_ID}/history" \
    -H "$(auth_header)" | jq .
  # Use .[0].timestamp as VERSION_ID for deploy.
}

# -----------------------------------------------------------------------------
# 5. Deploy a version (agents pick up the new config)
#    POST /v1/orgs/{ED_ORG_ID}/pipelines/{conf_id}/deploy/{version}
# -----------------------------------------------------------------------------
deploy_version() {
  local version_id="${1:?Usage: deploy_version VERSION_ID}"
  if [[ -z "${PIPELINE_ID:-}" ]]; then
    echo "PIPELINE_ID is not set."
    exit 1
  fi
  echo "Deploying version ${version_id}..."
  curl -fsS "${CURL_RETRY[@]}" -X POST \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/pipelines/${PIPELINE_ID}/deploy/${version_id}" \
    -H "$(auth_header)" \
    -H "Content-Type: application/json" | jq .
}

# -----------------------------------------------------------------------------
# One-shot: validate → save → get latest version → deploy
# -----------------------------------------------------------------------------
validate_save_deploy() {
  validate_config
  update_pipeline
  echo "Fetching history for deploy..."
  version_id=$(curl -fsS "${CURL_RETRY[@]}" -X GET \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/pipelines/${PIPELINE_ID}/history?only_latest=true" \
    -H "$(auth_header)" | jq -r '.[0].timestamp')
  if [[ -z "$version_id" || "$version_id" == "null" ]]; then
    echo "Could not get version ID from history."
    exit 1
  fi
  deploy_version "$version_id"
}

delete_pipeline() {
  if [[ -z "${PIPELINE_ID:-}" ]]; then
    echo "PIPELINE_ID is not set."
    exit 1
  fi
  echo "Deleting pipeline ${PIPELINE_ID}..."
  curl -fsS "${CURL_RETRY[@]}" -X DELETE \
    "${API_BASE}/v1/orgs/${ED_ORG_ID}/confs/${PIPELINE_ID}" \
    -H "$(auth_header)" | jq .
}

# --- Main: show usage or run command ---
case "${1:-}" in
  create-base)  create_base_pipeline ;;
  validate)     validate_config ;;
  update)       update_pipeline ;;
  history)      get_history ;;
  deploy)       deploy_version "${2:?Usage: deploy VERSION_ID}" ;;
  full)         validate_save_deploy ;;
  delete)       delete_pipeline ;;
  *)
    echo "Usage: $0 {create-base|validate|update|history|deploy VERSION_ID|full}"
    echo ""
    echo "  create-base  Create a new base pipeline (returns pipeline id)."
    echo "  validate      Validate pipelines/edgedelta.yaml."
    echo "  update       Save pipeline with content from pipelines/edgedelta.yaml (requires PIPELINE_ID)."
    echo "  history      Get version history (requires PIPELINE_ID)."
    echo "  deploy ID    Deploy version by timestamp from history."
    echo "  full         Validate, save, then deploy latest version (requires PIPELINE_ID)."
    echo ""
    echo "Env: ED_ORG_ID, ED_API_TOKEN; for update/history/deploy/full set PIPELINE_ID."
    exit 0
    ;;
esac
