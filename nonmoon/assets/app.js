/* nonmoon textbook viewer: settings, math, navigation, popovers, ask-Claude. */
(function () {
  "use strict";

  const app = document.querySelector(".app");
  if (!app) return;
  const data = JSON.parse(document.getElementById("book-data").textContent);
  const PREFIX = "nonmoon:" + data.id + ":";

  /* ---------- storage (per viewer; may be unavailable) ---------- */
  function load(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw == null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }
  function save(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      /* private mode or blocked storage: settings just won't persist */
    }
  }

  /* ---------- math ---------- */
  const MACROS = { "\\R": "\\mathbb{R}" };
  function renderMath(root) {
    if (!window.katex) return;
    root.querySelectorAll("[data-tex]:not([data-done])").forEach(function (el) {
      try {
        window.katex.render(el.getAttribute("data-tex"), el, {
          displayMode: el.classList.contains("math-display"),
          throwOnError: false,
          strict: "ignore",
          trust: false,
          macros: MACROS,
        });
        el.setAttribute("data-done", "");
      } catch (e) {
        el.classList.add("math-error");
      }
    });
  }
  renderMath(document);

  /* ---------- settings ---------- */
  const SIZES = [15, 16, 17, 18, 19, 20, 22];
  const settings = Object.assign(
    { mode: "ko", notes: true, font: "serif", size: 17 },
    load("nonmoon:settings", {})
  );
  if (!data.translated) settings.mode = "ko";
  function applySettings() {
    app.dataset.mode = settings.mode;
    app.dataset.notes = settings.notes ? "on" : "off";
    app.dataset.font = settings.font;
    app.style.setProperty("--fs", settings.size + "px");
    document.querySelectorAll("[data-set-mode]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.setMode === settings.mode));
    });
    const notesBtn = document.querySelector('[data-act="notes"]');
    if (notesBtn) notesBtn.setAttribute("aria-pressed", String(settings.notes));
    const fontBtn = document.querySelector('[data-act="font"]');
    if (fontBtn) fontBtn.textContent = settings.font === "serif" ? "명조" : "고딕";
  }
  function setSetting(key, value) {
    settings[key] = value;
    applySettings();
    save("nonmoon:settings", settings);
  }
  applySettings();

  document.addEventListener("click", function (ev) {
    const modeBtn = ev.target.closest("[data-set-mode]");
    if (modeBtn) return setSetting("mode", modeBtn.dataset.setMode);
    const act = ev.target.closest("[data-act]");
    if (!act) return;
    const a = act.dataset.act;
    if (a === "notes") setSetting("notes", !settings.notes);
    else if (a === "font") setSetting("font", settings.font === "serif" ? "sans" : "serif");
    else if (a === "smaller" || a === "larger") {
      let i = SIZES.indexOf(settings.size);
      if (i < 0) i = 2;
      i = Math.max(0, Math.min(SIZES.length - 1, i + (a === "larger" ? 1 : -1)));
      setSetting("size", SIZES[i]);
    } else if (a === "print") window.print();
    else if (a === "toc") toggleToc();
    else if (a === "menu") app.classList.toggle("menu-open");
    else if (a === "orig") {
      const blk = act.closest(".blk");
      const open = blk.classList.toggle("show-orig");
      act.setAttribute("aria-pressed", String(open));
    }
  });

  /* ---------- table of contents ---------- */
  const toc = document.getElementById("toc");
  function toggleToc(force) {
    const open = force === undefined ? !app.classList.contains("toc-open") : force;
    app.classList.toggle("toc-open", open);
    const btn = document.querySelector('[data-act="toc"]');
    if (btn) btn.setAttribute("aria-expanded", String(open));
  }
  if (toc) {
    toc.addEventListener("click", function (ev) {
      if (ev.target.closest("a")) toggleToc(false);
    });
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      toggleToc(false);
      app.classList.remove("menu-open");
      hidePop();
    }
  });
  const tocLinks = Array.from(document.querySelectorAll(".toc a[href^='#']"));
  const chapters = tocLinks
    .map(function (a) {
      return document.getElementById(a.getAttribute("href").slice(1));
    })
    .filter(Boolean);
  if ("IntersectionObserver" in window && chapters.length) {
    const visible = new Map();
    const io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          visible.set(e.target.id, e.isIntersecting);
        });
        const current = chapters.find(function (c) {
          return visible.get(c.id);
        });
        if (current) {
          tocLinks.forEach(function (a) {
            a.classList.toggle("active", a.getAttribute("href") === "#" + current.id);
          });
        }
      },
      { rootMargin: "-20% 0px -70% 0px" }
    );
    chapters.forEach(function (c) {
      io.observe(c);
    });
  }

  /* ---------- reading progress ---------- */
  const bar = document.querySelector(".progress span");
  function onScroll() {
    if (!bar) return;
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    bar.style.transform = "scaleX(" + (max > 0 ? Math.min(1, h.scrollTop / max) : 0) + ")";
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------- popover: glossary terms and figure/equation previews ---------- */
  const pop = document.createElement("div");
  pop.className = "pop";
  pop.setAttribute("role", "tooltip");
  pop.hidden = true;
  document.body.appendChild(pop);
  let popFor = null;
  let hideTimer = null;

  function showPop(target, html) {
    clearTimeout(hideTimer);
    pop.innerHTML = html;
    renderMath(pop);
    pop.hidden = false;
    popFor = target;
    const r = target.getBoundingClientRect();
    const pw = Math.min(380, window.innerWidth - 24);
    pop.style.width = pw + "px";
    let left = r.left + r.width / 2 - pw / 2;
    left = Math.max(12, Math.min(window.innerWidth - pw - 12, left));
    pop.style.left = left + window.scrollX + "px";
    const ph = pop.offsetHeight;
    const below = r.bottom + 10 + ph < window.innerHeight;
    pop.style.top = (below ? r.bottom + 8 : r.top - ph - 8) + window.scrollY + "px";
  }
  function hidePop() {
    pop.hidden = true;
    popFor = null;
  }
  function popHtmlFor(el) {
    if (el.classList.contains("term")) {
      const g = data.glossary[Number(el.dataset.g)];
      if (!g) return null;
      return (
        '<div class="pop-head"><span class="pop-ko">' + esc(g.ko) + '</span><span class="pop-en">' +
        esc(g.en) + "</span></div><div class=\"pop-body\">" + g.def + "</div>"
      );
    }
    if (el.classList.contains("xref")) {
      const target = document.getElementById(el.getAttribute("href").slice(1));
      if (!target) return null;
      if (el.dataset.ref === "fig") {
        const img = target.querySelector("img");
        const cap = target.querySelector("figcaption .cap-main");
        return (
          (img ? '<img class="pop-img" alt="" src="' + img.getAttribute("src") + '">' : "") +
          (cap ? '<div class="pop-body small">' + cap.innerHTML + "</div>" : "")
        );
      }
      const math = target.querySelector(".eq-math");
      return math ? '<div class="pop-eq">' + math.innerHTML + "</div>" : null;
    }
    return null;
  }
  function onEnter(ev) {
    const el = ev.target.closest && ev.target.closest(".term, .xref");
    if (!el || el === popFor) return;
    const html = popHtmlFor(el);
    if (html) showPop(el, html);
  }
  document.addEventListener("mouseover", onEnter);
  document.addEventListener("focusin", onEnter);
  document.addEventListener("mouseout", function (ev) {
    const el = ev.target.closest && ev.target.closest(".term, .xref");
    if (el && el === popFor) hideTimer = setTimeout(hidePop, 180);
  });
  pop.addEventListener("mouseover", function () {
    clearTimeout(hideTimer);
  });
  pop.addEventListener("mouseout", function () {
    hideTimer = setTimeout(hidePop, 180);
  });
  document.addEventListener("click", function (ev) {
    const term = ev.target.closest(".term");
    if (term) {
      const html = popHtmlFor(term);
      if (html && popFor !== term) showPop(term, html);
      else hidePop();
      return;
    }
    if (!ev.target.closest(".pop")) hidePop();
  });
  window.addEventListener("scroll", function () {
    if (!pop.hidden && popFor && !popFor.matches(":hover")) hidePop();
  }, { passive: true });

  /* flash the target of in-page links */
  function flash(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }
  window.addEventListener("hashchange", function () {
    flash(location.hash.slice(1));
  });

  /* ---------- small markdown for Claude's answers ---------- */
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function mdInline(s) {
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(\S(?:.*?\S)?)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*\w])\*(\S[^*\n]*?)\*(?![*\w])/g, "$1<em>$2</em>");
  }
  function md(src) {
    const math = [];
    let s = String(src).replace(
      /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$(?!\s)([^$\n]+?)\$/g,
      function (m, d1, d2, i1, i2) {
        const display = d1 !== undefined || d2 !== undefined;
        math.push([(d1 || d2 || i1 || i2 || "").trim(), display]);
        return "\u0000" + (math.length - 1) + "\u0000";
      }
    );
    s = esc(s);
    const out = [];
    s.split(/\n\s*\n/).forEach(function (chunk) {
      let para = [];
      let items = [];
      let tag = "";
      function flushP() {
        if (para.length) out.push("<p>" + mdInline(para.join(" ")) + "</p>");
        para = [];
      }
      function flushL() {
        if (items.length) {
          out.push("<" + tag + ">" + items.map(function (i) { return "<li>" + mdInline(i) + "</li>"; }).join("") + "</" + tag + ">");
        }
        items = [];
        tag = "";
      }
      chunk.split("\n").forEach(function (line) {
        const ul = line.match(/^\s{0,3}[-*•]\s+/);
        const ol = line.match(/^\s{0,3}\d+[.)]\s+/);
        if (ul || ol) {
          flushP();
          const t = ul ? "ul" : "ol";
          if (tag && tag !== t) flushL();
          tag = t;
          items.push(line.slice((ul || ol)[0].length));
        } else if (/^#{1,4}\s/.test(line)) {
          flushP();
          flushL();
          out.push('<p class="md-h">' + mdInline(line.replace(/^#+\s/, "")) + "</p>");
        } else if (items.length && /^\s+\S/.test(line)) {
          items[items.length - 1] += " " + line.trim();
        } else {
          flushL();
          if (line.trim()) para.push(line.trim());
        }
      });
      flushP();
      flushL();
    });
    return out.join("").replace(/\u0000(\d+)\u0000/g, function (m, i) {
      const item = math[Number(i)];
      return (
        '<span class="' + (item[1] ? "math-display" : "math-inline") + '" data-tex="' + esc(item[0]) + '">' +
        esc(item[0]) + "</span>"
      );
    });
  }

  /* ---------- saved questions (per viewer) ---------- */
  function historyKey(blk) {
    return PREFIX + "qa:" + blk;
  }
  function addHistory(container, q, a, open) {
    const item = document.createElement("details");
    item.className = "qa";
    if (open) item.open = true;
    item.innerHTML =
      '<summary><span class="qa-q-label">질문</span> ' + esc(q) + '</summary><div class="qa-a">' + md(a) + "</div>";
    container.appendChild(item);
    renderMath(item);
    return item;
  }
  function historyBox(host) {
    let box = host.querySelector(":scope > .qa-history");
    if (!box) {
      box = document.createElement("div");
      box.className = "qa-history";
      const anchor = host.querySelector(":scope > .ask");
      host.insertBefore(box, anchor || null);
    }
    return box;
  }
  document.querySelectorAll("[data-blk]").forEach(function (host) {
    const saved = load(historyKey(host.dataset.blk), []);
    if (Array.isArray(saved) && saved.length) {
      const box = historyBox(host);
      saved.forEach(function (x) {
        addHistory(box, x.q, x.a, false);
      });
      host.hidden = false;
    }
  });

  /* ---------- ask Claude (only inside a Claude viewer with `sample`) ---------- */
  const ERRORS = {
    rate_limited: "질문이 너무 많아요. 잠시 뒤에 다시 물어봐 주세요.",
    session_expired: "로그인이 만료됐어요. 다시 로그인한 뒤 물어봐 주세요.",
    refused: "Claude가 이 질문에는 답하지 않았어요. 질문을 바꿔 보세요.",
    empty_completion: "답이 비어 있어요. 질문을 조금 바꿔 보세요.",
    prompt_too_large: "질문과 본문을 합친 내용이 너무 길어요. 질문을 줄여 보세요.",
    image_rejected: "그림을 보낼 수 없었어요. 그림 없이 다시 물어봐 주세요.",
  };
  const FATAL = ["not_granted", "sampling_disabled", "not_declared", "capability_disabled", "capability_removed"];

  function askContext(blk) {
    const ctx = data.ask.blocks[blk];
    if (!ctx) return "";
    const sec = data.ask.sections[ctx.sec] || {};
    return (
      "[현재 위치] " + (sec.title || "") + (sec.summary ? "\n이 절의 요지: " + sec.summary : "") +
      "\n\n[독자가 보고 있는 부분]\n" + ctx.text
    );
  }
  function firstTurn(context, question) {
    return (
      "당신은 물리학 논문을 함께 읽는 정확하고 친절한 튜터입니다.\n\n" +
      "[독자] " + data.ask.profile + "\n\n" +
      "[논문] " + data.ask.paper + "\n[한 줄 요약] " + data.ask.one_line + "\n\n" +
      context + "\n\n" +
      "[질문] " + question + "\n\n" +
      "답변 방법:\n" +
      "- 한국어로, 질문에 대한 답부터 바로 말하세요.\n" +
      "- 독자 수준에 맞춰 직관에서 수식 순서로 설명하고, 필요하면 간단한 수치 예를 드세요.\n" +
      "- 수식은 LaTeX로 $...$ 또는 $$...$$ 안에 쓰세요.\n" +
      "- 논문에 없는 내용은 일반적인 물리 지식이라고 밝히고, 확실하지 않으면 그렇다고 말하세요.\n" +
      "- 마크다운의 굵게와 목록만 쓰고 표와 HTML은 쓰지 마세요. 보통 2~4문단으로 답하세요."
    );
  }

  function dataUriToBlob(uri) {
    const m = /^data:([^;]+);base64,(.*)$/.exec(uri || "");
    if (!m) return null;
    const bin = atob(m[2]);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: m[1] });
  }

  function buildAskPanel(host, blk, sample, imageLimits) {
    const panel = document.createElement("div");
    panel.className = "ask";
    const isGlobal = blk === "global";
    const suggestions = isGlobal
      ? ["이 논문의 핵심 아이디어를 쉽게 설명해줘", "우리 실험실에서는 어디에 쓰일까?", "이 논문의 한계는 뭐야?"]
      : host.classList.contains("eq")
      ? ["이 식을 단계별로 유도해줘", "각 항의 물리적 의미는?", "극한을 넣어 확인해줘"]
      : host.classList.contains("fig")
      ? ["이 그림에서 무엇을 봐야 해?", "봉우리와 모양이 왜 이렇게 생겼어?"]
      : ["더 쉽게 다시 설명해줘", "왜 그런지 직관적으로 설명해줘", "실험에서는 어떻게 해?"];
    const ids = "ask-" + blk;
    panel.innerHTML =
      '<div class="ask-head">' + (isGlobal ? "논문 전체에 대해 질문하기" : "이 부분에 대해 질문하기") + "</div>" +
      '<div class="ask-log"></div>' +
      '<div class="ask-suggest">' +
      suggestions.map(function (s) { return '<button type="button" class="chip">' + esc(s) + "</button>"; }).join("") +
      "</div>" +
      '<form class="ask-form"><label class="sr" for="' + ids + '">질문</label>' +
      '<textarea id="' + ids + '" rows="2" placeholder="궁금한 점을 적어 주세요"></textarea>' +
      '<div class="ask-actions"><button type="submit" class="btn-primary">질문하기</button>' +
      '<button type="button" class="btn-stop" hidden>멈추기</button></div></form>' +
      '<p class="ask-note">답은 내 Claude 사용량으로 만들어집니다. 처음 한 번은 허용을 묻습니다.</p>';
    const log = panel.querySelector(".ask-log");
    const form = panel.querySelector("form");
    const box = panel.querySelector("textarea");
    const stop = panel.querySelector(".btn-stop");
    const submit = panel.querySelector(".btn-primary");
    let turns = [];
    let ctl = null;

    panel.querySelectorAll(".chip").forEach(function (c) {
      c.addEventListener("click", function () {
        box.value = c.textContent;
        form.requestSubmit();
      });
    });
    stop.addEventListener("click", function () {
      if (ctl) ctl.abort();
    });
    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      const q = box.value.trim();
      if (!q || ctl) return;
      const context = isGlobal ? "[논문 전체 개요]\n" + data.ask.global : askContext(blk);
      const nextTurns = turns.length
        ? turns.concat([{ role: "user", content: q }])
        : [{ role: "user", content: firstTurn(context, q) }];
      const item = document.createElement("div");
      item.className = "qa live";
      item.innerHTML = '<div class="qa-q"><span class="qa-q-label">질문</span> ' + esc(q) + '</div><div class="qa-a"><p class="thinking">생각하는 중…</p></div>';
      log.appendChild(item);
      const answer = item.querySelector(".qa-a");
      box.value = "";
      submit.disabled = true;
      stop.hidden = false;
      ctl = new AbortController();
      const opts = {
        signal: ctl.signal,
        cache: false,
        onText: function (u) {
          answer.innerHTML = md(u.text);
          renderMath(answer);
        },
      };
      if (!turns.length && imageLimits && host.classList.contains("fig")) {
        const img = host.querySelector("img");
        const blob = img ? dataUriToBlob(img.getAttribute("src")) : null;
        const fits = blob && blob.size <= imageLimits.maxInputBytes &&
          (!imageLimits.mediaTypes || imageLimits.mediaTypes.indexOf(blob.type) >= 0);
        if (fits) opts.images = [blob];
      }
      try {
        const res = await sample(nextTurns, opts);
        answer.innerHTML = md(res.text);
        renderMath(answer);
        if (res.truncated) answer.insertAdjacentHTML("beforeend", '<p class="ask-err">답이 길어서 중간에 끊겼어요. 범위를 좁혀 다시 물어봐 주세요.</p>');
        turns = nextTurns.concat([{ role: "assistant", content: res.text }]);
        if (turns.length > 12) turns = [turns[0]].concat(turns.slice(-9));
        const saved = load(historyKey(blk), []);
        saved.push({ q: q, a: res.text });
        save(historyKey(blk), saved.slice(-20));
      } catch (e) {
        const code = (e && e.code) || "upstream_error";
        if (code === "cancelled") {
          answer.innerHTML = e.text ? md(e.text) : '<p class="ask-err">멈췄어요.</p>';
          renderMath(answer);
        } else if (FATAL.indexOf(code) >= 0) {
          answer.innerHTML = '<p class="ask-err">이 화면에서는 질문 기능을 쓸 수 없어요.</p>';
          disableAsk();
        } else {
          answer.innerHTML = (e.text ? md(e.text) : "") + '<p class="ask-err">' + (ERRORS[code] || "연결 문제로 답을 받지 못했어요. 다시 물어봐 주세요.") + "</p>";
          renderMath(answer);
        }
      } finally {
        ctl = null;
        submit.disabled = false;
        stop.hidden = true;
        item.classList.remove("live");
      }
    });
    return panel;
  }

  function disableAsk() {
    app.classList.remove("can-ask");
    document.querySelectorAll(".ask").forEach(function (p) {
      p.remove();
    });
  }

  (async function initAsk() {
    if (!data.ask || !window.claude || typeof window.claude.use !== "function") return;
    let sample = null;
    try {
      sample = await window.claude.use("sample");
    } catch (e) {
      sample = null;
    }
    if (!sample) return;
    let imageLimits = null;
    try {
      const lim = await sample.limits();
      imageLimits = (lim && lim.images) || null;
    } catch (e) {
      imageLimits = null;
    }
    app.classList.add("can-ask");
    document.addEventListener("click", function (ev) {
      const btn = ev.target.closest('[data-act="ask"]');
      if (!btn) return;
      const host = btn.closest("[data-blk]");
      if (!host) return;
      let panel = host.querySelector(":scope > .ask");
      if (panel) {
        panel.remove();
        btn.setAttribute("aria-expanded", "false");
        return;
      }
      panel = buildAskPanel(host, host.dataset.blk, sample, imageLimits);
      host.appendChild(panel);
      btn.setAttribute("aria-expanded", "true");
      panel.querySelector("textarea").focus();
    });
    const globalHost = document.getElementById("ask-global");
    if (globalHost) {
      globalHost.hidden = false;
      globalHost.appendChild(buildAskPanel(globalHost, "global", sample, null));
    }
  })();
})();
