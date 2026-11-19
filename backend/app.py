"""CNU 학사도우미 - 개발 환경 테스트 API.

GET  /health   : 서비스 상태 확인
POST /chat     : 질문을 받아 검증·마스킹 → Bedrock 임베딩 호출(연결 확인) → DynamoDB 기록
POST /feedback : 답변 피드백(도움됨/도움 안 됨) 기록

문서 검색(Knowledge Bases)과 답변 생성(Claude)은 다음 단계에서 /chat 안에 연결한다.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["TABLE_NAME"]
EMBED_MODEL_ID = os.environ.get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")
LOG_TTL_DAYS = int(os.environ.get("LOG_TTL_DAYS", "90"))
MAX_QUESTION_LEN = 500
MAX_COMMENT_LEN = 300

_table = boto3.resource("dynamodb").Table(TABLE_NAME)
_bedrock = boto3.client("bedrock-runtime")

# 학번(9~10자리 숫자)과 전화번호 패턴은 저장·모델 호출 전에 가린다.
_STUDENT_ID = re.compile(r"(?<!\d)\d{9,10}(?!\d)")
_PHONE = re.compile(r"(?<!\d)0\d{1,2}-?\d{3,4}-?\d{4}(?!\d)")


def mask_personal_info(text: str) -> str:
    text = _PHONE.sub("[전화번호]", text)
    return _STUDENT_ID.sub("[학번]", text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _expires_at() -> int:
    return int(time.time()) + LOG_TTL_DAYS * 24 * 3600


def _response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
            "Vary": "Origin",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSON 객체 형식이어야 합니다.")
    return data


def check_embedding(text: str) -> dict:
    """Bedrock 임베딩 모델을 한 번 호출해 연결과 권한을 확인한다."""
    try:
        resp = _bedrock.invoke_model(
            modelId=EMBED_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps({"inputText": text, "dimensions": 1024, "normalize": True}),
        )
        result = json.loads(resp["body"].read())
        return {
            "ok": True,
            "model": EMBED_MODEL_ID,
            "dimension": len(result.get("embedding", [])),
            "inputTokens": result.get("inputTextTokenCount"),
        }
    except (ClientError, BotoCoreError) as err:
        code = getattr(err, "response", {}).get("Error", {}).get("Code", type(err).__name__)
        logger.warning("bedrock embedding check failed: %s", code)
        return {"ok": False, "model": EMBED_MODEL_ID, "error": code}


def health(context) -> dict:
    return _response(
        200,
        {
            "status": "ok",
            "service": "cnu-haksa-chatbot",
            "region": os.environ.get("AWS_REGION"),
            "function": getattr(context, "function_name", None),
            "time": _now_iso(),
        },
    )


def chat(event: dict, context) -> dict:
    started = time.time()
    try:
        data = _parse_body(event)
    except (ValueError, json.JSONDecodeError):
        return _response(400, {"error": "요청 본문이 올바른 JSON이 아닙니다."})

    question = str(data.get("question", "")).strip()
    if not question:
        return _response(400, {"error": "question 값을 입력해 주세요."})
    if len(question) > MAX_QUESTION_LEN:
        return _response(400, {"error": f"질문은 {MAX_QUESTION_LEN}자 이내로 입력해 주세요."})

    masked = mask_personal_info(question)
    embedding = check_embedding(masked)
    latency_ms = int((time.time() - started) * 1000)
    request_id = getattr(context, "aws_request_id", "local")

    answer = (
        "개발 환경 테스트 응답입니다. 질문을 정상적으로 받았고, "
        "문서 검색과 답변 생성은 다음 단계에서 연결합니다."
    )

    log_ok = True
    try:
        _table.put_item(
            Item={
                "requestId": request_id,
                "type": "chat",
                "question": masked,
                "admitYear": str(data.get("admitYear", ""))[:4],
                "dept": str(data.get("dept", ""))[:50],
                "embeddingOk": embedding["ok"],
                "latencyMs": latency_ms,
                "createdAt": _now_iso(),
                "expiresAt": _expires_at(),
            }
        )
    except (ClientError, BotoCoreError) as err:
        log_ok = False
        logger.error("dynamodb put_item failed: %s", err)

    logger.info(
        json.dumps(
            {"route": "/chat", "requestId": request_id, "latencyMs": latency_ms,
             "embeddingOk": embedding["ok"], "logOk": log_ok},
            ensure_ascii=False,
        )
    )

    return _response(
        200,
        {
            "requestId": request_id,
            "question": masked,
            "answer": answer,
            "sources": [],
            "checks": {"bedrockEmbedding": embedding, "dynamodbLog": {"ok": log_ok}},
            "latencyMs": latency_ms,
        },
    )


def feedback(event: dict, context) -> dict:
    try:
        data = _parse_body(event)
    except (ValueError, json.JSONDecodeError):
        return _response(400, {"error": "요청 본문이 올바른 JSON이 아닙니다."})

    target = str(data.get("requestId", "")).strip()[:100]
    helpful = data.get("helpful")
    if not target or not isinstance(helpful, bool):
        return _response(400, {"error": "requestId와 helpful(true/false)이 필요합니다."})

    comment = mask_personal_info(str(data.get("comment", ""))[:MAX_COMMENT_LEN])
    feedback_id = f"fb-{getattr(context, 'aws_request_id', 'local')}"
    try:
        _table.put_item(
            Item={
                "requestId": feedback_id,
                "type": "feedback",
                "targetRequestId": target,
                "helpful": helpful,
                "comment": comment,
                "createdAt": _now_iso(),
                "expiresAt": _expires_at(),
            }
        )
    except (ClientError, BotoCoreError) as err:
        logger.error("dynamodb put_item failed: %s", err)
        return _response(500, {"error": "피드백을 저장하지 못했습니다."})

    return _response(200, {"ok": True, "feedbackId": feedback_id})


def handler(event, context):
    method = event.get("httpMethod", "")
    path = event.get("resource") or event.get("path") or ""

    if method == "GET" and path.endswith("/health"):
        return health(context)
    if method == "POST" and path.endswith("/chat"):
        return chat(event, context)
    if method == "POST" and path.endswith("/feedback"):
        return feedback(event, context)
    return _response(404, {"error": f"지원하지 않는 경로입니다: {method} {path}"})
