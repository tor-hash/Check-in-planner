#!/usr/bin/env bash
# One-time setup: lets GitHub Actions deploy Check-in Planner to Cloud Run.
# Run in Google Cloud Shell (https://shell.cloud.google.com) as a project owner:
#   bash scripts/setup-github-deploy.sh <PROJECT_ID>
# It prints three values to add as GitHub repository variables.
set -euo pipefail

PROJECT_ID="${1:?Usage: $0 <PROJECT_ID>}"
REPO="tor-hash/Check-in-planner"
SA_NAME="github-deployer"
POOL="github"
PROVIDER="github-repo"

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "==> Enabling APIs"
gcloud services enable iamcredentials.googleapis.com sts.googleapis.com cloudbuild.googleapis.com

echo "==> Creating deploy service account"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA_NAME" --display-name="GitHub Actions deployer"

echo "==> Granting roles to the deploy service account"
for ROLE in roles/cloudbuild.builds.editor roles/storage.admin roles/viewer roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA" --role="$ROLE" --condition=None >/dev/null
done
# Cloud Build runs steps as a build service account; the deployer must be
# allowed to "act as" it. Covers both the legacy and the newer default.
for BUILD_SA in "${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" "${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"; do
  gcloud iam service-accounts add-iam-policy-binding "$BUILD_SA" \
    --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser >/dev/null 2>&1 || true
done

echo "==> Creating Workload Identity pool + GitHub provider"
gcloud iam workload-identity-pools describe "$POOL" --location=global >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools create "$POOL" --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers describe "$PROVIDER" --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1 \
  || gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" \
       --location=global --workload-identity-pool="$POOL" \
       --issuer-uri="https://token.actions.githubusercontent.com" \
       --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
       --attribute-condition="assertion.repository=='${REPO}' && assertion.ref=='refs/heads/main'"

echo "==> Allowing only ${REPO} (main branch) to use the service account"
gcloud iam service-accounts add-iam-policy-binding "$SA" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" >/dev/null

cat <<OUT

Done. Add these under GitHub -> Settings -> Secrets and variables -> Actions -> Variables:

  GCP_PROJECT_ID    = ${PROJECT_ID}
  GCP_DEPLOY_SA     = ${SA}
  GCP_WIF_PROVIDER  = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}
OUT
