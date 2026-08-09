#!/usr/bin/env bash
# Deploy the demo: one Lambda behind a Function URL, one S3 static site.
#
# Run it in AWS CloudShell. Credentials are already there, which is the point:
# no access key and no database password ever land in the repository, and the
# password reaches the function as an environment variable set from a shell
# whose history is not committed.
#
#   export CRDB_URL='postgresql://...'      # copied from the CockroachDB console
#   git clone https://github.com/Outsider33/Hackathon-Cockroach-DB-x-AWS.git
#   cd Hackathon-Cockroach-DB-x-AWS
#   bash deploy/deploy.sh
#
# Idempotent: run it again after editing api/handler.py or web/index.html and it
# updates in place. It prints the two URLs at the end.

set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"     # same region as the cluster, so the
                                      # database round trip stays inside it
FUNCTION="agentmem-api"
ROLE="agentmem-lambda-role"
BUCKET="${BUCKET:-agentmem-demo-$(aws sts get-caller-identity --query Account --output text)}"

: "${CRDB_URL:?CRDB_URL is not set. Copy it from the CockroachDB console.}"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# ---------------------------------------------------------------- package ---
say "building the package"
pip install --quiet --upgrade pip >/dev/null
python3 deploy/build_lambda.py

# ------------------------------------------------------------------- role ---
say "IAM role"
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-role --role-name "$ROLE" \
    --assume-role-policy-document '{
      "Version":"2012-10-17",
      "Statement":[{"Effect":"Allow",
                    "Principal":{"Service":"lambda.amazonaws.com"},
                    "Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name "$ROLE" \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  echo "created, waiting for propagation"
  sleep 12
fi
ROLE_ARN=$(aws iam get-role --role-name "$ROLE" --query Role.Arn --output text)

# --------------------------------------------------------------- function ---
say "Lambda"
if aws lambda get-function --function-name "$FUNCTION" --region "$REGION" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$FUNCTION" --region "$REGION" \
    --zip-file fileb://dist/function.zip --query LastUpdateStatus --output text
  aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"
  aws lambda update-function-configuration --function-name "$FUNCTION" --region "$REGION" \
    --environment "Variables={CRDB_URL=$CRDB_URL,EMBED_BACKEND=${EMBED_BACKEND:-precomputed}}" \
    --timeout 20 --memory-size 512 --query LastUpdateStatus --output text
else
  aws lambda create-function --function-name "$FUNCTION" --region "$REGION" \
    --runtime python3.12 --handler handler.lambda_handler --role "$ROLE_ARN" \
    --zip-file fileb://dist/function.zip \
    --environment "Variables={CRDB_URL=$CRDB_URL,EMBED_BACKEND=${EMBED_BACKEND:-precomputed}}" \
    --timeout 20 --memory-size 512 --query FunctionArn --output text
fi
aws lambda wait function-updated --function-name "$FUNCTION" --region "$REGION"

# The page is a different origin from the function, so CORS is not optional.
# It is deliberately NOT configured on the function URL: when it is, Lambda adds
# its own headers on top of the ones the handler returns, and two
# Access-Control-Allow-Origin headers make a browser reject the response. One
# source of truth, and it is the handler.
# Creating the URL and making it public are two calls, and a run that dies
# between them leaves a function URL that answers 403 for ever after -- because
# the obvious "create it only if absent" guard then skips the second call on
# every later run. Measured on 2026-08-09. So the two settings are asserted
# every time instead of being guarded by the existence of the first one.
if ! aws lambda get-function-url-config --function-name "$FUNCTION" --region "$REGION" >/dev/null 2>&1; then
  aws lambda create-function-url-config --function-name "$FUNCTION" --region "$REGION" \
    --auth-type NONE >/dev/null
else
  aws lambda update-function-url-config --function-name "$FUNCTION" --region "$REGION" \
    --auth-type NONE >/dev/null
fi
# Already there is a success, not an error: the statement id makes it unique.
aws lambda add-permission --function-name "$FUNCTION" --region "$REGION" \
  --statement-id public-url --action lambda:InvokeFunctionUrl \
  --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
API=$(aws lambda get-function-url-config --function-name "$FUNCTION" --region "$REGION" \
      --query FunctionUrl --output text)
API="${API%/}"

# ------------------------------------------------------------------ site ---
say "S3 site"
if ! aws s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$BUCKET" \
    --public-access-block-configuration \
    "BlockPublicAcls=false,IgnorePublicAcls=false,BlockPublicPolicy=false,RestrictPublicBuckets=false"
  aws s3api put-bucket-policy --bucket "$BUCKET" --policy "{
    \"Version\":\"2012-10-17\",
    \"Statement\":[{\"Sid\":\"PublicRead\",\"Effect\":\"Allow\",\"Principal\":\"*\",
                    \"Action\":\"s3:GetObject\",
                    \"Resource\":\"arn:aws:s3:::$BUCKET/*\"}]}"
  aws s3 website "s3://$BUCKET/" --index-document index.html --error-document index.html
fi

# The only build step the page has: point it at the function that just deployed.
printf '// written by deploy/deploy.sh\nwindow.API_BASE = "%s";\n' "$API" > web/config.js
aws s3 sync web/ "s3://$BUCKET/" --delete \
  --cache-control "public,max-age=60" --only-show-errors
git checkout -- web/config.js 2>/dev/null || true

SITE="http://$BUCKET.s3-website-$REGION.amazonaws.com"

# ------------------------------------------------------------------ check ---
# The addresses are printed before the check, not after: a run that fails here
# has still deployed something, and the operator needs to know where it is in
# order to look at it. Under set -e the old order lost them both.
say "deployed"
echo "  demo   $SITE"
echo "  api    $API/?view=health"

say "checking, from outside"
api_code=$(curl -sS -o /tmp/agentmem-health -w '%{http_code}' "$API/?view=health" || echo 000)
site_code=$(curl -sS -o /dev/null -w '%{http_code}' "$SITE/" || echo 000)
echo "  api  $api_code"
echo "  site $site_code"
head -c 300 /tmp/agentmem-health 2>/dev/null; echo

# This is the only line that decides whether the demo exists. Both ends have to
# answer from outside, unauthenticated, the way a judge will meet them.
if [ "$api_code" != "200" ] || [ "$site_code" != "200" ]; then
  echo
  echo "NOT DEPLOYED. The addresses above exist but do not serve."
  echo "  api 403   -> the function URL is not public; see the add-permission call above"
  echo "  api 500   -> the function runs and the database does not answer; check CRDB_URL"
  echo "  site 403  -> the bucket policy or the public access block was not applied"
  exit 1
fi
say "done"
