/* 읽기 화면.
 *
 * 페이지네이션은 CSS 다단에 맡긴다 (계획서 6번의 "방법 B"). 브라우저가 텍스트를
 * 단에 흘려주고, 우리는 단 하나를 한 페이지로 보고 좌우로 이동시킨다.
 *
 * 페이지 번호는 어디에도 저장하지 않는다. 글자 크기나 창 크기가 바뀌면 단이 다시
 * 흐르고 페이지 수가 달라진다 (실측: 15px→34쪽, 26px→60쪽). 위치는 항상 블록 id 로
 * 기억한다 (SCHEMA.md 1번).
 */

const App = {
  slug: null,
  paper: null,
  page: 0,
  pageCount: 1,
  stride: 0,        // 한 페이지 이동 거리 = 단 너비 + 단 간격
  lang: "original", // 'original' | 'translated'
  refs: new Map(),  // ref id → 참고문헌
  highlights: [],
  bookmarks: new Set(),
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

// ─── 인라인 태그 → HTML ──────────────────────────────────

/** 중간 JSON 의 텍스트는 XML-safe 이고 <c>/<m> 태그가 박혀 있다 (SCHEMA.md 2번).
 *  이걸 화면용 HTML 로 바꾼다. 원문의 &amp; &lt; 는 그대로 두면 브라우저가 문자로 되돌린다. */
function renderInline(text, inlineMath) {
  const mathById = new Map((inlineMath || []).map((m) => [m.id, m.latex]));

  return text
    .replace(/<c id="(ref\d+)"\/>/g, (_, id) => {
      const n = id.slice(3);
      return `<sup class="cite" data-ref="${id}">[${n}]</sup>`;
    })
    .replace(/<m id="(m\d+)"\/>/g, (_, id) => {
      const latex = mathById.get(id);
      if (!latex) return "";
      return `<span class="inline-math" data-latex="${escapeAttr(latex)}"></span>`;
    });
}

function escapeAttr(s) {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

function stripTags(text) {
  return text.replace(/<[cm] id="[^"]+"\/>/g, "");
}

/** 이 블록에서 지금 보여줄 텍스트. 번역이 없으면 원문으로 되돌아간다.
 *  스키마가 번역 필드를 nullable 로 둔 이유가 이것이다 — 일부만 번역된 논문도
 *  정상적으로 읽혀야 한다. */
function textOf(block, field) {
  if (App.lang === "translated") {
    const t = block[`${field}_translated`];
    if (t) return t;
  }
  return block[`${field}_original`];
}

// ─── 블록 → DOM ─────────────────────────────────────────

function renderBlock(block) {
  const el = document.createElement(blockTag(block));
  el.id = block.id;
  el.dataset.block = block.id;

  switch (block.type) {
    case "heading":
      el.textContent = stripTags(textOf(block, "text"));
      break;

    case "paragraph":
      el.innerHTML = renderInline(textOf(block, "text"), block.inline_math);
      break;

    case "list": {
      el.className = "list-block";
      const items =
        (App.lang === "translated" && block.items_translated) || block.items_original;
      const ul = document.createElement("ul");
      for (const item of items) {
        const li = document.createElement("li");
        li.innerHTML = renderInline(item, block.inline_math);
        ul.appendChild(li);
      }
      el.appendChild(ul);
      break;
    }

    case "equation": {
      el.className = "equation";
      const wrap = document.createElement("div");
      wrap.className = "katex-wrap";
      wrap.dataset.latex = block.latex;
      el.appendChild(wrap);
      if (block.number) {
        const num = document.createElement("span");
        num.className = "eq-number";
        num.textContent = block.number;
        el.appendChild(num);
      }
      break;
    }

    case "figure": {
      el.className = "figure";
      const box = document.createElement("div");
      box.className = "images";
      for (const path of block.image_paths) {
        const img = document.createElement("img");
        img.src = `/papers/${App.slug}/${path}`;
        img.alt = block.caption_original || "";
        box.appendChild(img);
      }
      el.appendChild(box);
      const cap = textOf(block, "caption");
      if (cap) {
        const c = document.createElement("figcaption");
        c.textContent = cap;
        el.appendChild(c);
      }
      break;
    }

    case "table": {
      el.className = "table-block";
      const scroll = document.createElement("div");
      scroll.className = "scroll";
      scroll.innerHTML = textOf(block, "table_html");
      el.appendChild(scroll);
      const cap = textOf(block, "caption");
      if (cap) {
        const c = document.createElement("div");
        c.className = "table-caption";
        c.textContent = cap;
        el.appendChild(c);
      }
      break;
    }
  }
  return el;
}

function blockTag(block) {
  if (block.type === "heading") return `h${Math.min(block.level + 1, 4)}`;
  if (block.type === "paragraph") return "p";
  if (block.type === "figure") return "figure";
  return "div";
}

// ─── 수식 ───────────────────────────────────────────────

/** throwOnError:false 인 이유: Docling 의 수식 모델이 \text{an} 을 \an 으로 잘못 뱉는 걸
 *  실측했다 (5개 중 1개). \an 은 없는 명령이라 KaTeX 가 예외를 던진다. 그대로 두면
 *  논문 하나 때문에 뷰어가 통째로 죽는다. 깨진 수식만 빨갛게 보이는 편이 낫다. */
function renderMath(root) {
  if (typeof katex === "undefined") return;
  for (const el of root.querySelectorAll(".katex-wrap")) {
    katex.render(el.dataset.latex, el, { displayMode: true, throwOnError: false });
  }
  for (const el of root.querySelectorAll(".inline-math")) {
    katex.render(el.dataset.latex, el, { displayMode: false, throwOnError: false });
  }
}

// ─── 글자 오프셋 ────────────────────────────────────────

/** 블록 안의 텍스트 노드들. KaTeX 가 만든 DOM 은 건너뛴다 — 화면에 안 보이는
 *  MathML 까지 들어 있어서 오프셋이 뒤틀린다. */
function textNodesIn(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      if (node.parentElement.closest(".katex")) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) nodes.push(n);
  return nodes;
}

/** (노드, 노드 안 오프셋) → 블록 처음부터 센 글자 위치 */
function globalOffset(root, node, offset) {
  let total = 0;
  for (const t of textNodesIn(root)) {
    if (t === node) return total + offset;
    total += t.data.length;
  }
  return -1;
}

/** 블록 안 [start, end) 구간을 <mark> 로 감싼다. 여러 텍스트 노드에 걸쳐도 된다. */
function wrapRange(root, start, end, hid) {
  let pos = 0;
  for (const t of textNodesIn(root)) {
    const len = t.data.length;
    const from = Math.max(start - pos, 0);
    const to = Math.min(end - pos, len);
    if (from < to) {
      const range = document.createRange();
      range.setStart(t, from);
      range.setEnd(t, to);
      const mark = document.createElement("mark");
      mark.className = "hl";
      mark.dataset.hid = hid;
      try {
        range.surroundContents(mark);
      } catch {
        // 태그 경계를 가로지르면 surroundContents 가 거부한다. 그 조각은 건너뛴다.
      }
    }
    pos += len;
    if (pos >= end) break;
  }
}

function applyHighlights() {
  for (const m of $$("#book mark.hl")) {
    m.replaceWith(...m.childNodes);   // 기존 표시를 걷어낸다
  }
  for (const h of App.highlights) {
    if (h.lang !== App.lang) continue;   // 다른 언어에서 그은 것은 위치가 맞지 않는다
    const el = document.getElementById(h.block_id);
    if (el) wrapRange(el, h.start, h.end, h.id);
  }
  // note 가 달린 하이라이트는 표시가 다르다
  for (const m of $$("#book mark.hl")) {
    const h = App.highlights.find((x) => String(x.id) === m.dataset.hid);
    if (h?.note) m.classList.add("has-note");
  }
}

// ─── 페이지 이동 ────────────────────────────────────────

function measure() {
  const book = $("#book");
  const gap = parseFloat(getComputedStyle(book).columnGap) || 0;
  const width = book.clientWidth;

  // 단 하나가 화면을 정확히 채우게 만든다. 이 한 줄이 페이지네이션의 전부다:
  // 높이가 고정된 상태에서 내용이 넘치면 브라우저가 알아서 오른쪽에 단을 더 만들고,
  // 그 단들이 곧 페이지가 된다.
  book.style.columnWidth = `${width}px`;

  App.stride = width + gap;
  // scrollWidth 는 마지막 단 뒤의 간격을 포함하지 않으므로 gap 을 더해서 나눈다
  App.pageCount = Math.max(1, Math.round((book.scrollWidth + gap) / App.stride));
}

function goto(page) {
  App.page = Math.max(0, Math.min(page, App.pageCount - 1));
  $("#book").style.transform = `translateX(${-App.page * App.stride}px)`;

  $("#page-label").textContent = `${App.page + 1} / ${App.pageCount}`;
  $("#progress-fill").style.width = `${((App.page + 1) / App.pageCount) * 100}%`;
  $("#prev").disabled = App.page === 0;
  $("#next").disabled = App.page >= App.pageCount - 1;

  highlightToc();
  renderFootnotes();
  updateBookmarkButton();
  savePosition();
}

/** 어떤 요소가 몇 번째 페이지에 있는가.
 *  #book 이 transform 으로 밀려 있어도 요소와 #book 의 상대 거리는 그대로다. */
function pageOf(el) {
  const x = el.getBoundingClientRect().left - $("#book").getBoundingClientRect().left;
  return Math.floor(x / App.stride + 0.01);   // 경계 부동소수 오차 방어
}

function gotoBlock(blockId) {
  const el = document.getElementById(blockId);
  if (el) goto(pageOf(el));
}

/** 지금 페이지에 보이는 첫 블록. 위치 저장과 리플로우 복원의 기준점. */
function currentBlockId() {
  for (const el of $("#book").querySelectorAll("[data-block]")) {
    if (pageOf(el) >= App.page) return el.dataset.block;
  }
  return $("#book").querySelector("[data-block]")?.dataset.block ?? null;
}

// ─── 각주 ───────────────────────────────────────────────

/** 지금 페이지에 있는 인용만 모아 페이지 하단에 각주로 그린다.
 *
 *  책처럼 "그 페이지의 각주는 그 페이지 아래에" 를 지키려면 페이지마다 각주 영역이
 *  필요한데, CSS 다단에서는 단 안에 뭘 끼워 넣을 수가 없다. 그래서 화면에 보이는
 *  페이지가 하나뿐이라는 점을 이용한다 — 각주 칸을 화면 하단에 고정해 두고,
 *  현재 페이지의 각주만 갈아 끼운다.
 *
 *  각주 칸 높이는 고정이다. 페이지마다 높이를 바꾸면 본문이 다시 흐르고, 그러면
 *  인용이 다른 페이지로 옮겨가고, 그럼 각주가 또 바뀌는 순환에 빠진다. */
function renderFootnotes() {
  const box = $("#footnotes");
  box.innerHTML = "";

  const seen = new Set();
  for (const sup of $$("#book .cite")) {
    if (pageOf(sup) !== App.page) continue;
    const id = sup.dataset.ref;
    if (seen.has(id)) continue;
    seen.add(id);

    const ref = App.refs.get(id);
    if (!ref) continue;

    const line = document.createElement("div");
    line.className = "footnote";
    line.innerHTML = `<span class="fn-marker">${ref.marker}</span> <span class="fn-text"></span>`;
    line.querySelector(".fn-text").textContent = ref.text;
    if (ref.doi) {
      const a = document.createElement("a");
      a.href = `https://doi.org/${ref.doi}`;
      a.target = "_blank";
      a.rel = "noopener";
      a.textContent = "↗";
      a.className = "fn-doi";
      line.appendChild(a);
    }
    box.appendChild(line);
  }
  box.classList.toggle("empty", seen.size === 0);
}

/** 그 블록으로 눈이 가도록 잠깐 깜빡인다. 검색 결과로 뛰어왔을 때
 *  "어디가 걸린 건데?" 를 없애준다. */
function flash(blockId) {
  const el = document.getElementById(blockId);
  if (!el) return;
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 1400);
}

// ─── 논문 안에서 찾기 ───────────────────────────────────
// 논문 JSON 은 이미 브라우저에 있으므로 서버에 묻지 않는다. 즉시 답이 나온다.

function searchInBook(query) {
  const box = $("#find-results");
  box.innerHTML = "";
  query = query.trim();
  if (query.length < 2) return;

  const re = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "i");
  let count = 0;

  for (const el of $("#book").querySelectorAll("[data-block]")) {
    const text = el.textContent;
    const m = re.exec(text);
    if (!m) continue;
    count++;
    if (count > 60) break;

    const start = Math.max(0, m.index - 32);
    const item = document.createElement("a");
    item.className = "find-hit";
    item.href = "#";
    const before = text.slice(start, m.index);
    const hit = text.slice(m.index, m.index + query.length);
    const after = text.slice(m.index + query.length, m.index + query.length + 42);
    item.innerHTML =
      `<span class="fh-page"></span>` +
      `<span class="fh-text">${start ? "…" : ""}${escapeHtml(before)}` +
      `<mark>${escapeHtml(hit)}</mark>${escapeHtml(after)}…</span>`;
    item.querySelector(".fh-page").textContent = `${pageOf(el) + 1}쪽`;
    item.addEventListener("click", (e) => {
      e.preventDefault();
      gotoBlock(el.dataset.block);
      flash(el.dataset.block);
    });
    box.appendChild(item);
  }

  if (!count) {
    const none = document.createElement("p");
    none.className = "find-none";
    none.textContent = "찾은 것이 없다.";
    box.appendChild(none);
  }
}

function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// ─── 목차 ───────────────────────────────────────────────

function buildToc(nodes, parent) {
  for (const node of nodes) {
    const a = document.createElement("a");
    a.textContent =
      (App.lang === "translated" && node.title_translated) || node.title;
    a.dataset.level = node.level;
    a.dataset.block = node.block_id;
    a.href = "#";
    a.addEventListener("click", (e) => {
      e.preventDefault();
      gotoBlock(node.block_id);
      if (window.innerWidth < 900) $("#toc").classList.remove("open");
    });
    parent.appendChild(a);
    if (node.children?.length) buildToc(node.children, parent);
  }
}

function highlightToc() {
  let current = null;
  for (const a of $$("#toc a")) {
    const el = document.getElementById(a.dataset.block);
    if (el && pageOf(el) <= App.page) current = a;
    a.classList.remove("current");
  }
  current?.classList.add("current");
}

// ─── 서버와 상태 주고받기 ───────────────────────────────

const api = (path, opts) =>
  fetch(`/api/state/${App.slug}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  }).then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))));

let saveTimer;
function savePosition() {
  // 페이지를 넘길 때마다 서버를 때리면 낭비다. 잠깐 멈췄을 때만 보낸다.
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    const block = currentBlockId();
    if (block) {
      api("/position", { method: "PUT", body: JSON.stringify({ block_id: block }) })
        .catch(() => {});   // 저장 실패로 읽기를 방해하지 않는다
    }
  }, 800);
}

function updateBookmarkButton() {
  const block = currentBlockId();
  $("#bookmark").classList.toggle("on", App.bookmarks.has(block));
}

async function toggleBookmark() {
  const block = currentBlockId();
  if (!block) return;
  try {
    const { bookmarked } = await api("/bookmark", {
      method: "POST",
      body: JSON.stringify({ block_id: block }),
    });
    bookmarked ? App.bookmarks.add(block) : App.bookmarks.delete(block);
    updateBookmarkButton();
  } catch {}
}

// ─── 하이라이트 만들기 ──────────────────────────────────

function selectionInfo() {
  const sel = window.getSelection();
  if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
  const range = sel.getRangeAt(0);

  const block = range.startContainer.parentElement?.closest("[data-block]");
  if (!block || !block.contains(range.endContainer)) return null;
  // 그림·표에는 긋지 않는다 (오프셋이 의미 없다)
  if (block.classList.contains("figure") || block.classList.contains("table-block")) {
    return null;
  }

  const start = globalOffset(block, range.startContainer, range.startOffset);
  const end = globalOffset(block, range.endContainer, range.endOffset);
  if (start < 0 || end < 0 || start >= end) return null;

  return { blockId: block.dataset.block, start, end, text: sel.toString() };
}

async function createHighlight(note = null) {
  const info = selectionInfo();
  if (!info) return;
  try {
    const { id } = await api("/highlight", {
      method: "POST",
      body: JSON.stringify({
        block_id: info.blockId,
        lang: App.lang,
        start: info.start,
        end: info.end,
        text: info.text,
        note,
      }),
    });
    App.highlights.push({ id, block_id: info.blockId, lang: App.lang, ...info, note });
    window.getSelection().removeAllRanges();
    applyHighlights();
    hidePopup();
  } catch {}
}

async function deleteHighlight(hid) {
  try {
    await api(`/highlight/${hid}`, { method: "DELETE" });
    App.highlights = App.highlights.filter((h) => String(h.id) !== String(hid));
    applyHighlights();
    hidePopup();
  } catch {}
}

async function editNote(hid) {
  const h = App.highlights.find((x) => String(x.id) === String(hid));
  const note = prompt("메모", h?.note || "");
  if (note === null) return;
  try {
    await api(`/highlight/${hid}`, {
      method: "PATCH",
      body: JSON.stringify({ note: note || null }),
    });
    if (h) h.note = note || null;
    applyHighlights();
    hidePopup();
  } catch {}
}

// ─── 떠 있는 작은 메뉴 ──────────────────────────────────

function showPopup(x, y, buttons) {
  const pop = $("#popup");
  pop.innerHTML = "";
  for (const [label, fn] of buttons) {
    const b = document.createElement("button");
    b.textContent = label;
    b.addEventListener("mousedown", (e) => {
      e.preventDefault();   // 선택이 풀리기 전에 처리한다
      fn();
    });
    pop.appendChild(b);
  }
  pop.style.left = `${Math.max(8, x - 40)}px`;
  pop.style.top = `${Math.max(8, y - 46)}px`;
  pop.classList.add("open");
}

function hidePopup() {
  $("#popup").classList.remove("open");
}

// ─── 번역 토글 ──────────────────────────────────────────

function setLang(lang) {
  App.lang = lang;
  const anchor = currentBlockId();

  const book = $("#book");
  book.innerHTML = "";
  for (const block of App.paper.blocks) book.appendChild(renderBlock(block));
  renderMath(book);

  $("#toc-list").innerHTML = "";
  buildToc(App.paper.toc, $("#toc-list"));

  applyHighlights();
  measure();
  if (anchor) gotoBlock(anchor);
  else goto(0);

  $("#lang").textContent = lang === "translated" ? "번역" : "원문";
  $("#lang").classList.toggle("on", lang === "translated");
  updateEpubLink();
}

/** 내려받기 링크(EPUB·PDF)가 지금 보는 언어를 따라가게 한다. 번역을 보고 있으면
 *  번역본을, 원문을 보고 있으면 원문을 받는다. */
function updateEpubLink() {
  const t = App.lang === "translated" ? 1 : 0;
  const epub = $("#epub");
  if (epub) epub.href = `/download/${App.slug}.epub?translated=${t}`;
  const pdf = $("#pdf");
  if (pdf) pdf.href = `/download/${App.slug}.pdf?translated=${t}`;
}

// ─── 시작 ───────────────────────────────────────────────

async function waitForImages(root) {
  // 이미지 높이가 확정돼야 단이 제대로 나뉜다. 안 기다리면 페이지 수가 틀린다.
  await Promise.all(
    [...root.querySelectorAll("img")].map((img) =>
      img.complete
        ? Promise.resolve()
        : new Promise((r) => {
            img.addEventListener("load", r, { once: true });
            img.addEventListener("error", r, { once: true });
          })
    )
  );
}

async function main() {
  App.slug = document.body.dataset.slug;
  App.paper = await (await fetch(`/api/paper/${App.slug}`)).json();
  for (const ref of App.paper.references) App.refs.set(ref.id, ref);

  const hasTranslation = App.paper.blocks.some((b) => b.text_translated);
  $("#lang").disabled = !hasTranslation;
  $("#lang").title = hasTranslation ? "원문 ↔ 번역" : "이 논문은 번역되지 않았다";

  // 책장에서 검색 결과를 눌러 들어온 경우: ?goto=b0012&lang=translated
  const params = new URLSearchParams(location.search);
  const jumpTo = params.get("goto");
  if (params.get("lang") === "translated" && hasTranslation) App.lang = "translated";

  const book = $("#book");
  for (const block of App.paper.blocks) book.appendChild(renderBlock(block));
  renderMath(book);
  await waitForImages(book);

  buildToc(App.paper.toc, $("#toc-list"));
  $("#lang").textContent = App.lang === "translated" ? "번역" : "원문";
  $("#lang").classList.toggle("on", App.lang === "translated");
  updateEpubLink();

  // 저장된 상태를 불러온다. 실패해도 읽기는 되어야 하므로 기본값으로 넘어간다.
  let state = { position: null, bookmarks: [], highlights: [] };
  try {
    state = await api("");
  } catch {}
  App.highlights = state.highlights;
  App.bookmarks = new Set(state.bookmarks.map((b) => b.block_id));
  applyHighlights();

  measure();
  // 검색 결과로 들어왔으면 그 자리, 아니면 마지막 읽던 자리
  if (jumpTo && document.getElementById(jumpTo)) {
    gotoBlock(jumpTo);
    flash(jumpTo);
  } else if (state.position && document.getElementById(state.position)) {
    gotoBlock(state.position);
  } else {
    goto(0);
  }

  $("#loading").classList.add("hidden");

  // ─── 조작 ───
  $("#next").addEventListener("click", () => goto(App.page + 1));
  $("#prev").addEventListener("click", () => goto(App.page - 1));

  // 좌우 가장자리를 톡 누르면 페이지를 넘긴다. 단, 글자를 드래그해 선택했으면
  // 넘기지 않는다 — 그건 복사하려는 것이지 페이지를 넘기려는 게 아니다.
  // (예전엔 넘김 영역이 글자를 덮어서 가장자리 글자를 선택할 수 없었다.)
  $("#viewport").addEventListener("click", (e) => {
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed && sel.toString().trim()) return;  // 선택 중 → 넘기지 않음
    // 인용·링크·하이라이트를 눌렀으면 그쪽이 처리한다
    if (e.target.closest("a, button, .cite, mark, #popup, #ref-popup")) return;
    const rect = $("#viewport").getBoundingClientRect();
    const x = e.clientX - rect.left;
    const edge = rect.width * 0.12;
    if (x < edge) goto(App.page - 1);
    else if (x > rect.width - edge) goto(App.page + 1);
  });

  $("#toc-toggle").addEventListener("click", () => $("#toc").classList.toggle("open"));
  $("#bookmark").addEventListener("click", toggleBookmark);

  // PDF 는 Chrome 으로 변환하느라 몇 초 걸린다. 만드는 동안 표시해서 재클릭을 막는다.
  const pdfBtn = $("#pdf");
  if (pdfBtn) {
    pdfBtn.addEventListener("click", () => {
      pdfBtn.classList.add("busy");
      pdfBtn.textContent = "만드는 중…";
      // 브라우저가 다운로드를 시작하면 이 페이지는 그대로 남는다. 넉넉히 뒤 되돌린다.
      setTimeout(() => {
        pdfBtn.classList.remove("busy");
        pdfBtn.textContent = "PDF";
      }, 12000);
    });
  }

  const findPanel = $("#find");
  const openFind = () => {
    findPanel.classList.add("open");
    $("#find-input").focus();
    $("#find-input").select();
  };
  $("#find-toggle").addEventListener("click", () =>
    findPanel.classList.contains("open")
      ? findPanel.classList.remove("open")
      : openFind()
  );
  $("#find-close").addEventListener("click", () => findPanel.classList.remove("open"));
  let findTimer;
  $("#find-input").addEventListener("input", (e) => {
    clearTimeout(findTimer);
    findTimer = setTimeout(() => searchInBook(e.target.value), 160);
  });
  $("#lang").addEventListener("click", () =>
    setLang(App.lang === "original" ? "translated" : "original")
  );

  // 글자 크기
  for (const [id, delta] of [["font-minus", -1], ["font-plus", 1]]) {
    $(`#${id}`).addEventListener("click", () => {
      const now = parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue("--font-size")
      );
      const next = Math.min(30, Math.max(14, now + delta));
      const anchor = currentBlockId();
      document.documentElement.style.setProperty("--font-size", `${next}px`);
      book.style.transition = "none";
      measure();
      if (anchor) gotoBlock(anchor);
      requestAnimationFrame(() => (book.style.transition = ""));
    });
  }

  document.addEventListener("keydown", (e) => {
    // Ctrl+F 는 브라우저 찾기 대신 우리 찾기를 연다. 브라우저 찾기는 다른 페이지(단)에
    // 있는 글자를 찾아도 화면을 그리로 옮겨주지 못해서 쓸모가 없다.
    if ((e.ctrlKey || e.metaKey) && e.key === "f") {
      e.preventDefault();
      openFind();
      return;
    }
    if (e.key === "Escape") {
      findPanel.classList.remove("open");
      $("#ref-popup").classList.remove("open");
      hidePopup();
      return;
    }
    if (e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
      e.preventDefault();
      goto(App.page + 1);
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      e.preventDefault();
      goto(App.page - 1);
    } else if (e.key === "Home") goto(0);
    else if (e.key === "End") goto(App.pageCount - 1);
    else if (e.key === "t") setLang(App.lang === "original" ? "translated" : "original");
    else if (e.key === "b") toggleBookmark();
  });

  // 본문에서 글자를 끌면 하이라이트 메뉴가 뜬다
  book.addEventListener("mouseup", (e) => {
    const mark = e.target.closest("mark.hl");
    if (mark) {
      const hid = mark.dataset.hid;
      const h = App.highlights.find((x) => String(x.id) === hid);
      showPopup(e.clientX, e.clientY, [
        [h?.note ? "메모 수정" : "메모", () => editNote(hid)],
        ["지우기", () => deleteHighlight(hid)],
      ]);
      return;
    }
    setTimeout(() => {
      if (selectionInfo()) {
        showPopup(e.clientX, e.clientY, [
          ["하이라이트", () => createHighlight()],
          ["메모와 함께", () => {
            const note = prompt("메모");
            if (note !== null) createHighlight(note || null);
          }],
        ]);
      } else hidePopup();
    }, 0);
  });

  document.addEventListener("mousedown", (e) => {
    if (!e.target.closest("#popup")) hidePopup();
  });

  // 인용을 누르면 그 참고문헌만 크게 보여준다
  book.addEventListener("click", (e) => {
    const cite = e.target.closest(".cite");
    if (!cite) return;
    const ref = App.refs.get(cite.dataset.ref);
    if (!ref) return;
    const box = $("#ref-popup");
    box.querySelector(".rp-text").textContent = `${ref.marker} ${ref.text}`;
    const link = box.querySelector(".rp-doi");
    link.style.display = ref.doi ? "" : "none";
    if (ref.doi) link.href = `https://doi.org/${ref.doi}`;
    box.classList.add("open");
  });
  $("#ref-popup .rp-close").addEventListener("click", () =>
    $("#ref-popup").classList.remove("open")
  );

  // 창 크기가 바뀌면 단이 다시 흐른다. 페이지 번호는 의미를 잃으므로
  // 보고 있던 블록을 기준으로 되찾아간다.
  let resizeTimer;
  window.addEventListener("resize", () => {
    const anchor = currentBlockId();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      book.style.transition = "none";
      measure();
      if (anchor) gotoBlock(anchor);
      else goto(App.page);
      requestAnimationFrame(() => (book.style.transition = ""));
    }, 120);
  });
}

main();
