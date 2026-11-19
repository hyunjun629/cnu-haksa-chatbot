#!/usr/bin/env bash
# CNU 학사도우미 - AWS 배포 스크립트 (AWS CloudShell에서 실행)
#   사용법: bash scripts/deploy.sh
set -euo pipefail

# CloudShell 기본 언어 설정에서 템플릿의 한글 설명이 ??로 깨지지 않도록 UTF-8로 고정
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

STACK_NAME="${STACK_NAME:-cnu-haksa-dev}"
REGION="${REGION:-ap-northeast-2}"
STAGE="${STAGE:-dev}"

cd "$(dirname "$0")/.."

echo "== 1/5 템플릿 검사 =="
sam validate --template-file template.yaml --region "$REGION"

echo "== 2/5 인프라 배포 (CloudFormation 스택: $STACK_NAME, 리전: $REGION) =="
sam deploy \
  --template-file template.yaml \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "Stage=$STAGE" \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset

output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

API_URL="$(output ApiUrl)"
WEB_URL="$(output WebUrl)"
WEB_BUCKET="$(output WebBucketName)"
DOCS_BUCKET="$(output DocsBucketName)"
DIST_ID="$(output DistributionId)"

echo "== 3/5 웹 화면 업로드 (S3 → CloudFront) =="
printf 'window.APP_CONFIG = { apiUrl: "%s" };\n' "$API_URL" > frontend/config.js
aws s3 sync frontend/ "s3://$WEB_BUCKET/" --delete --region "$REGION"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" \
  --query "Invalidation.Status" --output text

echo "== 4/5 문서 저장소 폴더 구성 (raw/, processed/) + 샘플 문서 업로드 =="
aws s3api put-object --bucket "$DOCS_BUCKET" --key raw/ --region "$REGION" > /dev/null
aws s3api put-object --bucket "$DOCS_BUCKET" --key processed/ --region "$REGION" > /dev/null
aws s3 cp data/sample/ "s3://$DOCS_BUCKET/raw/" --recursive --region "$REGION"

echo "== 5/5 동작 확인 =="
echo "[GET /health]"
curl -sS "$API_URL/health"; echo
echo "[POST /chat]"
curl -sS -X POST "$API_URL/chat" -H "Content-Type: application/json" \
  -d '{"question":"휴학은 최대 몇 학기까지 할 수 있어? 제 학번은 202412345입니다","admitYear":"2024"}'
echo

cat <<EOF

배포 완료
  웹 화면 : $WEB_URL   (CloudFront 첫 배포는 몇 분 걸릴 수 있음)
  API     : $API_URL
  문서 버킷: s3://$DOCS_BUCKET
EOF
