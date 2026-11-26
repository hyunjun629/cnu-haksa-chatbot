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

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function setStatus(text, cls) {
    var s = $("status");
    s.textContent = text;
    s.className = "status " + (cls || "");
  }

  async function callApi(path, options) {
    var res = await fetch(apiUrl + path, options);
    var data = await res.json().catch(function () { return {}; });
    if (!res.ok) {
      var msg = data.error || ("HTTP " + res.status);
      if (data.code) msg += " (" + data.code + ")";
      throw new Error(msg);
    }
    return data;
  }

  async function checkHealth() {
    if (!apiUrl) { setStatus("API 주소가 설정되지 않았습니다 (config.js)", "bad"); return; }
    try {
      var h = await callApi("/health");
      setStatus("API 정상 · " + h.region, "ok");
    } catch (e) {
      setStatus("API 연결 실패: " + e.message, "bad");
    }
  }

  // 답변 속 [1] 같은 인용 번호를 위첨자로 바꿔 표시 (텍스트 노드만 사용해 HTML 주입 방지)
  function renderAnswer(container, text) {
    container.innerHTML = "";
    var parts = text.split(/(\[\d{1,2}\])/);
    parts.forEach(function (p) {
      var m = p.match(/^\[(\d{1,2})\]$/);
      if (m) container.appendChild(el("sup", null, "[" + m[1] + "]"));
      else container.appendChild(document.createTextNode(p));
    });
  }

  function renderSources(list) {
    var box = $("sources");
    box.innerHTML = "";
    list.forEach(function (s) {
      var card = el("div", "src");
      var head = el("div", "head");
      head.appendChild(el("span", "num", String(s.id)));
      head.appendChild(el("span", "title", s.title));
      card.appendChild(head);
      var meta = [s.posted && ("게시·개정 " + s.posted), s.office && ("담당 " + s.office), "관련도 " + s.score]
        .filter(Boolean).join(" · ");
      card.appendChild(el("div", "meta", meta));
      if (s.snippet) card.appendChild(el("div", "snip", s.snippet));
      if (s.url) {
        var a = el("a", null, "원문 보기 ↗");
        a.href = s.url; a.target = "_blank"; a.rel = "noopener";
        card.appendChild(a);
      }
      box.appendChild(card);
    });
    $("sourcesWrap").classList.toggle("hidden", list.length === 0);
  }

  function renderNoBasis(container, data) {
    container.innerHTML = "";
    var box = el("div", "nobasis");
    box.appendChild(el("div", null, data.answer));
    var ul = el("ul", "contacts");
    (data.contacts || []).forEach(function (c) {
      ul.appendChild(el("li", null, c.office + " (" + c.topics + ") · 전화 " + c.phone));
    });
    box.appendChild(ul);
    container.appendChild(box);
  }

  async function sendQuestion() {
    var question = $("question").value.trim();
    if (!question) { $("question").focus(); return; }
    var btn = $("send");
    btn.disabled = true;
    btn.textContent = "자료를 찾고 답변을 만드는 중…";
    $("result").classList.remove("hidden");
    $("echo").textContent = "";
    $("answer").textContent = "";
    $("stats").textContent = "";
    $("sourcesWrap").classList.add("hidden");
    $("fbMsg").classList.add("hidden");

    try {
      var data = await callApi("/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, admitYear: $("admitYear").value, dept: $("dept").value })
      });
      lastRequestId = data.requestId;
      var f = data.filters || {};
      var who = [f.admitYear && (f.admitYear + "학번"), f.dept].filter(Boolean).join(" · ");
      $("echo").textContent = "질문: " + data.question + (who ? "  (" + who + " 기준)" : "");
      if (data.answered) {
        renderAnswer($("answer"), data.answer);
        renderSources(data.sources || []);
      } else {
        renderNoBasis($("answer"), data);
      }
      var r = data.retrieval || {};
      $("stats").textContent = "검색 " + r.found + "건 중 기준 점수(" + r.minScore + ") 이상 " + r.used +
        "건 · 최고 점수 " + r.topScore + " · 처리 " + data.latencyMs + "ms";
    } catch (e) {
      $("answer").innerHTML = "";
      $("answer").appendChild(el("p", "err", "오류: " + e.message));
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
      msg.textContent = "피드백이 기록되었습니다. 감사합니다.";
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
    b.addEventListener("click", function () { $("question").value = b.textContent; sendQuestion(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll("#fb button"), function (b) {
    b.addEventListener("click", function () { sendFeedback(b.dataset.helpful === "true"); });
  });

  checkHealth();
})();
