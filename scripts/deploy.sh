#!/usr/bin/env bash
# CNU 학사도우미 - AWS 배포 스크립트 (AWS CloudShell에서 실행)
#   사용법: bash scripts/deploy.sh
set -euo pipefail

# 스크립트가 출력하는 한글(동작 확인 결과)을 UTF-8로 처리
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

STACK_NAME="${STACK_NAME:-cnu-haksa-dev}"
REGION="${REGION:-ap-northeast-2}"
STAGE="${STAGE:-dev}"
# 근거 판단 기준값. sam deploy는 지정하지 않은 파라미터를 이전 값으로 유지하므로 매번 명시한다.
# (scripts/score_check.sh 측정: 관련 질문 최저 0.699, 무관 질문 최고 0.618)
MIN_SCORE="${MIN_SCORE:-0.65}"

cd "$(dirname "$0")/.."

echo "== 1/6 템플릿 검사 =="
sam validate --template-file template.yaml --region "$REGION"

echo "== 2/6 인프라 배포 (CloudFormation 스택: $STACK_NAME, 리전: $REGION) =="
sam deploy \
  --template-file template.yaml \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides "Stage=$STAGE" "MinScore=$MIN_SCORE" \
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
KB_ID="$(output KnowledgeBaseId)"
DS_ID="$(output DataSourceId)"

echo "== 3/6 웹 화면 업로드 (S3 → CloudFront) =="
printf 'window.APP_CONFIG = { apiUrl: "%s" };\n' "$API_URL" > frontend/config.js
aws s3 sync frontend/ "s3://$WEB_BUCKET/" --delete --region "$REGION"
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" \
  --query "Invalidation.Status" --output text

echo "== 4/6 문서 업로드 (raw/ 원본, processed/ 검색용 텍스트 + 메타데이터) =="
# 현재 문서는 이미 정제된 텍스트(.md)라서 그대로 processed/에 올린다. (HWP·PDF 변환은 전처리 Lambda 단계에서 추가)
aws s3 sync data/docs/ "s3://$DOCS_BUCKET/raw/" --delete --region "$REGION"
aws s3 sync data/docs/ "s3://$DOCS_BUCKET/processed/" --delete --region "$REGION"

echo "== 5/6 Knowledge Base 동기화 (분할 → 임베딩 → S3 Vectors 적재) =="
JOB_ID="$(aws bedrock-agent start-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
  --region "$REGION" --query "ingestionJob.ingestionJobId" --output text)"
echo "동기화 작업 ID: $JOB_ID"
STATUS="STARTING"
for _ in $(seq 1 60); do
  STATUS="$(aws bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
    --ingestion-job-id "$JOB_ID" --region "$REGION" --query "ingestionJob.status" --output text)"
  echo "  상태: $STATUS"
  case "$STATUS" in COMPLETE|FAILED|STOPPED) break ;; esac
  sleep 5
done
aws bedrock-agent get-ingestion-job --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
  --ingestion-job-id "$JOB_ID" --region "$REGION" \
  --query "ingestionJob.{status:status,statistics:statistics,failureReasons:failureReasons}" --output json
if [ "$STATUS" != "COMPLETE" ]; then
  echo "동기화가 완료되지 않았습니다 (상태: $STATUS). 위 failureReasons를 확인하세요." >&2
  exit 1
fi

echo "== 6/6 동작 확인 =="
echo "[GET /health]"
curl -sS "$API_URL/health" | python3 -m json.tool --no-ensure-ascii
echo "[POST /chat] 2024학번 · 컴퓨터융합학부 졸업요건 질문"
curl -sS -X POST "$API_URL/chat" -H "Content-Type: application/json" \
  -d '{"question":"졸업하려면 몇 학점을 들어야 해? 제 학번은 202412345입니다","admitYear":"2024","dept":"컴퓨터융합학부"}' \
  | python3 -m json.tool --no-ensure-ascii

cat <<EOF

배포 완료
  웹 화면   : $WEB_URL
  API       : $API_URL
  문서 버킷 : s3://$DOCS_BUCKET
  Knowledge Base ID: $KB_ID
EOF
