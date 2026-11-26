"""Lambda 핸들러 단위 테스트 (AWS 호출은 가짜 객체로 대체).

실행: python -m pytest -q   (프로젝트 최상위 폴더에서)
"""

import json
import os
import sys
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest

os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-2")
os.environ.setdefault("AWS_REGION", "ap-northeast-2")
os.environ.setdefault("ALLOWED_ORIGIN", "https://example.cloudfront.net")
os.environ.setdefault("KB_ID", "KBTEST1234")
os.environ.setdefault("MIN_SCORE", "0.35")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import app  # noqa: E402

CTX = SimpleNamespace(aws_request_id="req-123", function_name="cnu-haksa-chat-dev")


def chunk(text, score, name, title, posted=20261120):
    return {
        "content": {"text": text},
        "score": score,
        "location": {"s3Location": {"uri": f"s3://docs/processed/{name}"}},
        "metadata": {"doc_title": title, "office": "학사 담당 부서", "posted": posted,
                     "source_url": f"https://example.com/{name}"},
    }


DEFAULT_CHUNKS = [
    chunk("정정 기간: 2027년 3월 2일 ~ 3월 8일", 0.62, "01.md", "수강신청 일정 안내"),
    chunk("정정 기간에는 과목을 취소하거나 추가할 수 있습니다.", 0.55, "01.md", "수강신청 일정 안내"),
    chunk("Q. 계절학기는 몇 학점까지?", 0.41, "08.md", "FAQ", 20261120.0),
    chunk("관련 없는 문장", 0.20, "09.md", "연락처"),
]


def converse_reply(text, with_reasoning=False):
    content = [{"text": text}]
    if with_reasoning:
        content.insert(0, {"reasoningContent": {"reasoningText": {"text": ""}}})
    return {"output": {"message": {"content": content}}, "usage": {"inputTokens": 900, "outputTokens": 80}}


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch):
    table, kb, llm = mock.MagicMock(), mock.MagicMock(), mock.MagicMock()
    kb.retrieve.return_value = {"retrievalResults": DEFAULT_CHUNKS}
    llm.converse.return_value = converse_reply("정정 기간은 2027년 3월 2일부터 3월 8일까지입니다 [1]. 계절학기는 [2]")
    monkeypatch.setattr(app, "_table", table)
    monkeypatch.setattr(app, "_kb", kb)
    monkeypatch.setattr(app, "_llm", llm)
    return SimpleNamespace(table=table, kb=kb, llm=llm)


def call(method, path, body=None):
    event = {"httpMethod": method, "resource": path}
    if body is not None:
        event["body"] = json.dumps(body, ensure_ascii=False)
    res = app.handler(event, CTX)
    return res["statusCode"], json.loads(res["body"]), res["headers"]


def assert_dynamodb_safe(item):
    """boto3 DynamoDB는 float를 받지 않으므로 float가 섞이면 실제 저장에서 실패한다."""
    def walk(v):
        assert not isinstance(v, float), f"float 값은 DynamoDB에 저장할 수 없음: {v}"
        if isinstance(v, dict):
            [walk(x) for x in v.values()]
        if isinstance(v, (list, tuple)):
            [walk(x) for x in v]
    walk(item)


def test_health():
    status, body, headers = call("GET", "/health")
    assert status == 200 and body["status"] == "ok" and body["knowledgeBase"] == "KBTEST1234"
    assert headers["Access-Control-Allow-Origin"] == "https://example.cloudfront.net"


def test_chat_answered_with_sources(fake_aws):
    status, body, _ = call("POST", "/chat", {"question": "정정 기간 언제야? 학번 202412345", "admitYear": "2024",
                                             "dept": "컴퓨터융합학부"})
    assert status == 200 and body["answered"] is True
    assert "[학번]" in body["question"]
    # 같은 문서의 청크 2개는 출처 1개로 묶이고, 기준 점수 미만 청크는 제외
    assert [s["title"] for s in body["sources"]] == ["수강신청 일정 안내", "FAQ"]
    assert body["sources"][0]["posted"] == "2026.11.20" and body["sources"][1]["posted"] == "2026.11.20"
    assert body["retrieval"] == {"topScore": 0.62, "minScore": 0.35, "found": 4, "used": 3}
    # 개인정보는 검색어와 프롬프트에 들어가지 않는다
    q = fake_aws.kb.retrieve.call_args.kwargs["retrievalQuery"]["text"]
    prompt = fake_aws.llm.converse.call_args.kwargs["messages"][0]["content"][0]["text"]
    assert "202412345" not in q and "202412345" not in prompt
    assert "[1] 문서명: 수강신청 일정 안내" in prompt and "2024학번 컴퓨터융합학부" in prompt
    assert fake_aws.llm.converse.call_args.kwargs["modelId"].startswith("global.anthropic.claude-haiku-4-5")
    assert "additionalModelRequestFields" not in fake_aws.llm.converse.call_args.kwargs
    item = fake_aws.table.put_item.call_args.kwargs["Item"]
    assert item["answered"] is True and item["reason"] == "answered"
    assert_dynamodb_safe(item)


def test_filter_shapes():
    f = app.build_filter(2024, "컴퓨터융합학부")
    keys = json.dumps(f, ensure_ascii=False)
    assert "andAll" in f and len(f["andAll"]) == 4
    assert '"admit_from"' in keys and '"admit_to"' in keys and '"전체"' in keys
    only_expiry = app.build_filter(None, "")
    assert list(only_expiry) == ["greaterThanOrEquals"] and only_expiry["greaterThanOrEquals"]["key"] == "expires"


def test_low_score_skips_model(fake_aws):
    fake_aws.kb.retrieve.return_value = {"retrievalResults": [chunk("무관", 0.12, "09.md", "연락처")]}
    status, body, _ = call("POST", "/chat", {"question": "학식 메뉴 알려줘"})
    assert status == 200 and body["answered"] is False and body["sources"] == []
    assert body["contacts"] and "확인되지 않는" in body["answer"]
    fake_aws.llm.converse.assert_not_called()
    assert fake_aws.table.put_item.call_args.kwargs["Item"]["reason"] == "low_score"


def test_model_no_answer(fake_aws):
    fake_aws.llm.converse.return_value = converse_reply("NO_ANSWER")
    status, body, _ = call("POST", "/chat", {"question": "기숙사 신청은?"})
    assert body["answered"] is False and body["sources"] == []
    assert fake_aws.table.put_item.call_args.kwargs["Item"]["reason"] == "model_no_answer"


def test_reasoning_block_before_text(fake_aws):
    fake_aws.llm.converse.return_value = converse_reply("답변입니다 [1].", with_reasoning=True)
    _, body, _ = call("POST", "/chat", {"question": "정정 기간"})
    assert body["answer"] == "답변입니다 [1]." and len(body["sources"]) == 1


def test_uncited_answer_keeps_all_sources(fake_aws):
    fake_aws.llm.converse.return_value = converse_reply("정정 기간은 3월 2일부터입니다.")
    _, body, _ = call("POST", "/chat", {"question": "정정 기간"})
    assert len(body["sources"]) == 2


def test_retrieve_error_returns_502(fake_aws):
    from botocore.exceptions import ClientError

    fake_aws.kb.retrieve.side_effect = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "Retrieve")
    status, body, _ = call("POST", "/chat", {"question": "테스트"})
    assert status == 502 and body["code"] == "AccessDeniedException"


def test_generate_error_returns_502(fake_aws):
    from botocore.exceptions import ClientError

    fake_aws.llm.converse.side_effect = ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "x"}}, "Converse")
    status, body, _ = call("POST", "/chat", {"question": "정정 기간"})
    assert status == 502 and body["code"] == "ResourceNotFoundException"


def test_chat_validation():
    assert call("POST", "/chat", {"question": "  "})[0] == 400
    assert call("POST", "/chat", {"question": "가" * 501})[0] == 400
    res = app.handler({"httpMethod": "POST", "resource": "/chat", "body": "not json"}, CTX)
    assert res["statusCode"] == 400


def test_feedback(fake_aws):
    status, body, _ = call("POST", "/feedback", {"requestId": "req-123", "helpful": True})
    assert status == 200 and body["feedbackId"] == "fb-req-123"
    assert call("POST", "/feedback", {"requestId": "req-123", "helpful": "yes"})[0] == 400


def test_model_extra_fields(fake_aws, monkeypatch):
    monkeypatch.setattr(app, "MODEL_EXTRA_FIELDS", {"thinking": {"type": "disabled"}})
    call("POST", "/chat", {"question": "정정 기간"})
    assert fake_aws.llm.converse.call_args.kwargs["additionalModelRequestFields"] == {"thinking": {"type": "disabled"}}


def test_answer_markdown_removed(fake_aws):
    fake_aws.llm.converse.return_value = converse_reply("2022학번은 **총 140학점 이상**을 이수해야 합니다 [1].\n- 전공 72학점 [1]")
    _, body, _ = call("POST", "/chat", {"question": "졸업 학점"})
    assert body["answer"] == "2022학번은 총 140학점 이상을 이수해야 합니다 [1].\n전공 72학점 [1]"


def test_snippet_hides_markdown():
    raw = "## 2. 수강신청 정정 기간\n- 정정 기간: 3월 2일 ~ 3월 8일\n| 부서 | 전화 |"
    assert app.clean_snippet(raw) == "2. 수강신청 정정 기간 정정 기간: 3월 2일 ~ 3월 8일 부서 전화"


def test_unknown_route():
    assert call("GET", "/nope")[0] == 404
