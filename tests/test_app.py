"""Lambda 핸들러 단위 테스트 (AWS 호출은 가짜 객체로 대체).

실행: python -m pytest -q   (프로젝트 최상위 폴더에서)
"""

import io
import json
import os
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-2")
os.environ.setdefault("AWS_REGION", "ap-northeast-2")
os.environ.setdefault("ALLOWED_ORIGIN", "https://example.cloudfront.net")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app  # noqa: E402

CTX = SimpleNamespace(aws_request_id="req-123", function_name="cnu-haksa-chat-dev")


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch):
    table = mock.MagicMock()
    bedrock = mock.MagicMock()
    bedrock.invoke_model.return_value = {
        "body": io.BytesIO(json.dumps({"embedding": [0.0] * 1024, "inputTextTokenCount": 12}).encode())
    }
    monkeypatch.setattr(app, "_table", table)
    monkeypatch.setattr(app, "_bedrock", bedrock)
    return SimpleNamespace(table=table, bedrock=bedrock)


def call(method, path, body=None):
    event = {"httpMethod": method, "resource": path}
    if body is not None:
        event["body"] = json.dumps(body, ensure_ascii=False)
    res = app.handler(event, CTX)
    return res["statusCode"], json.loads(res["body"]), res["headers"]


def test_health():
    status, body, headers = call("GET", "/health")
    assert status == 200 and body["status"] == "ok"
    assert headers["Access-Control-Allow-Origin"] == "https://example.cloudfront.net"


def test_chat_masks_and_logs(fake_aws):
    status, body, _ = call("POST", "/chat", {"question": "학번 202412345, 전화 010-1234-5678 휴학 질문"})
    assert status == 200
    assert "[학번]" in body["question"] and "[전화번호]" in body["question"]
    assert "202412345" not in body["question"]
    assert body["checks"]["bedrockEmbedding"] == {
        "ok": True, "model": app.EMBED_MODEL_ID, "dimension": 1024, "inputTokens": 12}
    item = fake_aws.table.put_item.call_args.kwargs["Item"]
    assert item["requestId"] == "req-123" and "202412345" not in item["question"]
    sent = json.loads(fake_aws.bedrock.invoke_model.call_args.kwargs["body"])
    assert "202412345" not in sent["inputText"]


def test_chat_validation():
    assert call("POST", "/chat", {"question": "  "})[0] == 400
    assert call("POST", "/chat", {"question": "가" * 501})[0] == 400
    res = app.handler({"httpMethod": "POST", "resource": "/chat", "body": "not json"}, CTX)
    assert res["statusCode"] == 400


def test_chat_bedrock_failure_still_answers(fake_aws):
    from botocore.exceptions import ClientError

    fake_aws.bedrock.invoke_model.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "InvokeModel")
    status, body, _ = call("POST", "/chat", {"question": "테스트"})
    assert status == 200
    assert body["checks"]["bedrockEmbedding"]["ok"] is False
    assert body["checks"]["bedrockEmbedding"]["error"] == "AccessDeniedException"


def test_feedback(fake_aws):
    status, body, _ = call("POST", "/feedback", {"requestId": "req-123", "helpful": True})
    assert status == 200 and body["feedbackId"] == "fb-req-123"
    assert call("POST", "/feedback", {"requestId": "req-123", "helpful": "yes"})[0] == 400


def test_unknown_route():
    assert call("GET", "/nope")[0] == 404
