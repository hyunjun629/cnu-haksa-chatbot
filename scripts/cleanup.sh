#!/usr/bin/env bash
# CNU 학사도우미 - 만든 AWS 리소스 전체 삭제 (과제 확인이 끝난 뒤 실행)
#   사용법: bash scripts/cleanup.sh
set -euo pipefail

STACK_NAME="${STACK_NAME:-cnu-haksa-dev}"
REGION="${REGION:-ap-northeast-2}"

read -r -p "스택 $STACK_NAME 과 버킷 안의 파일을 모두 삭제합니다. 계속할까요? (yes 입력) " answer
[ "$answer" = "yes" ] || { echo "취소했습니다."; exit 0; }

output() {
  aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

# 버킷이 비어 있어야 스택 삭제가 성공한다. 문서 버킷은 버전 관리가 켜져 있어 이전 버전까지 지운다.
for key in WebBucketName DocsBucketName; do
  bucket="$(output "$key")"
  echo "버킷 비우는 중: $bucket"
  python3 - "$bucket" <<'PY'
import sys, boto3
boto3.resource("s3").Bucket(sys.argv[1]).object_versions.delete()
PY
done

sam delete --stack-name "$STACK_NAME" --region "$REGION" --no-prompts
echo "삭제 완료"
