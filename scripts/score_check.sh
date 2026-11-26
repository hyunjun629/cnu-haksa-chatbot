#!/usr/bin/env bash
# 근거 판단 기준값(MinScore)을 정하기 위해, 문서와 관련 있는 질문과 관련 없는 질문의 최고 검색 점수를 비교한다.
#   사용법: bash scripts/score_check.sh
set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONIOENCODING=utf-8

STACK_NAME="${STACK_NAME:-cnu-haksa-dev}"
REGION="${REGION:-ap-northeast-2}"
API_URL="$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)"

python3 - "$API_URL" <<'PY'
import json, sys, time, urllib.request

api = sys.argv[1]
cases = [
    ("관련", "수강신청 정정 기간은 언제야?"),
    ("관련", "휴학은 최대 몇 학기까지 할 수 있어?"),
    ("관련", "복수전공 신청 자격이 뭐야?"),
    ("관련", "교내 장학금 종류 알려줘"),
    ("관련", "근로장학금 신청 기간이 언제야?"),
    ("관련", "성적 이의신청은 언제 할 수 있어?"),
    ("관련", "학사 담당 부서 전화번호 알려줘"),
    ("관련", "졸업하려면 몇 학점 들어야 해?"),
    ("무관", "학식 메뉴 알려줘"),
    ("무관", "기숙사 신청은 어떻게 해?"),
    ("무관", "도서관 운영 시간이 어떻게 돼?"),
    ("무관", "오늘 대전 날씨 어때?"),
    ("무관", "교내 주차 등록 방법 알려줘"),
    ("무관", "동아리 가입하려면 어떻게 해?"),
]
rows = []
for kind, q in cases:
    req = urllib.request.Request(api + "/chat", data=json.dumps({"question": q}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    rows.append((kind, d["retrieval"]["topScore"], d["answered"], q))
    time.sleep(0.3)  # API Gateway 요청 제한(초당 5건) 안에서 실행

print(f"{'구분':<4} {'최고점수':>8}  {'답변':<5} 질문")
for kind, score, answered, q in sorted(rows, key=lambda x: -x[1]):
    print(f"{kind:<4} {score:>8.3f}  {'예' if answered else '아니오':<5} {q}")
rel = [s for k, s, _, _ in rows if k == "관련"]
irr = [s for k, s, _, _ in rows if k == "무관"]
print(f"\n관련 질문 최저 점수: {min(rel):.3f} / 무관 질문 최고 점수: {max(irr):.3f}")
PY
