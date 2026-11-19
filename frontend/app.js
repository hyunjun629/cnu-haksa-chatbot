(function () {
  "use strict";

  var config = window.APP_CONFIG || {};
  var apiUrl = (config.apiUrl || "").replace(/\/+$/, "");
  var lastRequestId = null;

  var $ = function (id) { return document.getElementById(id); };

  // 입학년도 선택지 (최근 8년)
  var thisYear = new Date().getFullYear();
  for (var y = thisYear; y > thisYear - 8; y--) {
    var opt = document.createElement("option");
    opt.value = String(y);
    opt.textContent = y + "학번";
    $("admitYear").appendChild(opt);
  }

  function setStatus(text, cls) {
    var el = $("status");
    el.textContent = text;
    el.className = "status " + (cls || "");
  }

  function addDetail(dl, key, value) {
    var dt = document.createElement("dt");
    dt.textContent = key;
    var dd = document.createElement("dd");
    dd.textContent = value;
    dl.appendChild(dt);
    dl.appendChild(dd);
  }

  async function callApi(path, options) {
    var res = await fetch(apiUrl + path, options);
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      throw new Error(data.error || ("HTTP " + res.status));
    }
    return data;
  }

  async function checkHealth() {
    if (!apiUrl) {
      setStatus("API 주소가 설정되지 않았습니다 (config.js)", "bad");
      return;
    }
    try {
      var h = await callApi("/health");
      setStatus("API 정상 · " + h.region + " · " + h.time, "ok");
    } catch (e) {
      setStatus("API 연결 실패: " + e.message, "bad");
    }
  }

  async function sendQuestion() {
    var question = $("question").value.trim();
    if (!question) { $("question").focus(); return; }

    var btn = $("send");
    btn.disabled = true;
    btn.textContent = "응답 기다리는 중…";
    $("result").classList.remove("hidden");
    $("answer").textContent = "";
    $("details").innerHTML = "";
    $("fbMsg").classList.add("hidden");

    try {
      var data = await callApi("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question,
          admitYear: $("admitYear").value,
          dept: $("dept").value.trim()
        })
      });
      lastRequestId = data.requestId;
      $("answer").textContent = data.answer;

      var emb = (data.checks || {}).bedrockEmbedding || {};
      var log = (data.checks || {}).dynamodbLog || {};
      var dl = $("details");
      addDetail(dl, "요청 ID", data.requestId);
      addDetail(dl, "기록된 질문", data.question);
      addDetail(dl, "Bedrock 임베딩", emb.ok
        ? "정상 (" + emb.model + ", " + emb.dimension + "차원)"
        : "실패 (" + (emb.error || "알 수 없음") + ")");
      addDetail(dl, "DynamoDB 기록", log.ok ? "정상" : "실패");
      addDetail(dl, "처리 시간", data.latencyMs + " ms");
    } catch (e) {
      $("answer").innerHTML = "";
      var p = document.createElement("p");
      p.className = "err";
      p.textContent = "오류: " + e.message;
      $("answer").appendChild(p);
    } finally {
      btn.disabled = false;
      btn.textContent = "질문 보내기";
    }
  }

  async function sendFeedback(helpful) {
    if (!lastRequestId) return;
    var msg = $("fbMsg");
    try {
      await callApi("/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requestId: lastRequestId, helpful: helpful })
      });
      msg.textContent = "피드백이 기록되었습니다.";
      msg.className = "";
    } catch (e) {
      msg.textContent = "피드백 기록 실패: " + e.message;
      msg.className = "err";
    }
  }

  $("send").addEventListener("click", sendQuestion);
  $("question").addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendQuestion();
  });
  Array.prototype.forEach.call(document.querySelectorAll("#chips button"), function (b) {
    b.addEventListener("click", function () { $("question").value = b.textContent; });
  });
  Array.prototype.forEach.call(document.querySelectorAll("#fb button"), function (b) {
    b.addEventListener("click", function () { sendFeedback(b.dataset.helpful === "true"); });
  });

  checkHealth();
})();
