/* 페이지네이션 엔진.
 *
 * 계획서 6번의 "방법 B": CSS 다단에 맡긴다. 브라우저가 텍스트를 단에 흘려주고,
 * 우리는 단 하나를 한 페이지로 보고 좌우로 이동시킨다.
 *
 * 페이지 번호는 어디에도 저장하지 않는다. 글자 크기나 창 크기가 바뀌면 단이 다시
 * 흐르고 페이지 수가 달라지기 때문이다. 위치는 항상 블록 id 로 기억한다
 * (SCHEMA.md 1번).
 */

const App = {
  paper: null,
  page: 0,
  pageCount: 1,
  stride: 0,     // 한 페이지 이동 거리 = 단 너비 + 단 간격
};

const $ = (sel) => document.querySelector(sel);

// ─── 인라인 태그 → HTML ──────────────────────────────────

/** 중간 JSON 의 텍스트는 XML-safe 이고 <c>/<m> 태그가 박혀 있다 (SCHEMA.md 2번).
 *  이걸 화면용 HTML 로 바꾼다. 원문의 & < > 는 이스케이프된 채로 두면
 *  브라우저가 알아서 문자로 되돌려 그린다. */
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

// ─── 블록 → DOM ─────────────────────────────────────────

function renderBlock(block, slug) {
  const el = document.createElement(blockTag(block));
  el.id = block.id;
  el.dataset.block = block.id;

  switch (block.type) {
    case "heading":
      el.textContent = stripTags(block.text_original);
      break;

    case "paragraph":
      el.innerHTML = renderInline(block.text_original, block.inline_math);
      break;

    case "list": {
      el.className = "list-block";
      const ul = document.createElement("ul");
      for (const item of block.items_original) {
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
        img.src = `/papers/${slug}/${path}`;
        img.alt = block.caption_original || "";
        box.appendChild(img);
      }
      el.appendChild(box);
      if (block.caption_original) {
        const cap = document.createElement("figcaption");
        cap.textContent = block.caption_original;
        el.appendChild(cap);
      }
      break;
    }

    case "table": {
      el.className = "table-block";
      const scroll = document.createElement("div");
      scroll.className = "scroll";
      scroll.innerHTML = block.table_html_original;
      el.appendChild(scroll);
      if (block.caption_original) {
        const cap = document.createElement("div");
        cap.className = "table-caption";
        cap.textContent = block.caption_original;
        el.appendChild(cap);
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

function stripTags(text) {
  return text.replace(/<[cm] id="[^"]+"\/>/g, "");
}

// ─── 수식 렌더링 ────────────────────────────────────────

/** KaTeX 를 throwOnError:false 로 부른다.
 *
 *  실측에서 Docling 의 수식 모델이 \text{an} 을 \an 으로 잘못 뱉는 걸 봤다
 *  (5개 중 1개). \an 은 존재하지 않는 명령이라 KaTeX 가 예외를 던진다.
 *  그대로 두면 논문 하나 때문에 뷰어가 통째로 죽는다. 깨진 수식만 빨갛게
 *  보이고 나머지 페이지는 살아 있는 편이 낫다. */
function renderMath(root) {
  if (typeof katex === "undefined") return;

  for (const el of root.querySelectorAll(".katex-wrap")) {
    katex.render(el.dataset.latex, el, { displayMode: true, throwOnError: false });
  }
  for (const el of root.querySelectorAll(".inline-math")) {
    katex.render(el.dataset.latex, el, { displayMode: false, throwOnError: false });
  }
}

// ─── 페이지 이동 ────────────────────────────────────────

function measure() {
  const book = $("#book");
  const gap = parseFloat(getComputedStyle(book).columnGap) || 0;
  const width = book.clientWidth;

  // 단 하나가 화면을 정확히 채우게 만든다. 이 한 줄이 페이지네이션의 전부다:
  // 높이가 고정된 상태에서 내용이 넘치면 브라우저가 알아서 오른쪽에 단을 더 만들고,
  // 그 단들이 곧 페이지가 된다. 글자 크기를 바꾸면 저절로 다시 흐른다.
  book.style.columnWidth = `${width}px`;

  App.stride = width + gap;
  // scrollWidth 는 마지막 단 뒤의 간격을 포함하지 않으므로 gap 을 더해서 나눈다
  App.pageCount = Math.max(1, Math.round((book.scrollWidth + gap) / App.stride));
}

function goto(page, { silent = false } = {}) {
  App.page = Math.max(0, Math.min(page, App.pageCount - 1));
  $("#book").style.transform = `translateX(${-App.page * App.stride}px)`;

  $("#page-label").textContent = `${App.page + 1} / ${App.pageCount}`;
  $("#progress-fill").style.width =
    `${((App.page + 1) / App.pageCount) * 100}%`;
  $("#prev").disabled = App.page === 0;
  $("#next").disabled = App.page >= App.pageCount - 1;

  if (!silent) highlightToc();
}

/** 어떤 요소가 몇 번째 페이지에 있는가.
 *  #book 이 transform 으로 밀려 있어도, 요소와 #book 의 상대 거리는 그대로다. */
function pageOf(el) {
  const bookLeft = $("#book").getBoundingClientRect().left;
  const x = el.getBoundingClientRect().left - bookLeft;
  return Math.floor(x / App.stride + 0.01);   // 경계 부동소수 오차 방어
}

function gotoBlock(blockId) {
  const el = document.getElementById(blockId);
  if (el) goto(pageOf(el));
}

// ─── 목차 ───────────────────────────────────────────────

function buildToc(nodes, parent, slug) {
  for (const node of nodes) {
    const a = document.createElement("a");
    a.textContent = node.title;
    a.dataset.level = node.level;
    a.dataset.block = node.block_id;
    a.href = "#";
    a.addEventListener("click", (e) => {
      e.preventDefault();
      gotoBlock(node.block_id);
      if (window.innerWidth < 900) $("#toc").classList.remove("open");
    });
    parent.appendChild(a);
    if (node.children?.length) buildToc(node.children, parent, slug);
  }
}

function highlightToc() {
  let current = null;
  for (const a of document.querySelectorAll("#toc a")) {
    const el = document.getElementById(a.dataset.block);
    if (el && pageOf(el) <= App.page) current = a;
    a.classList.remove("current");
  }
  if (current) current.classList.add("current");
}

// ─── 시작 ───────────────────────────────────────────────

async function main() {
  const slug = document.body.dataset.slug;
  const res = await fetch(`/api/paper/${slug}`);
  App.paper = await res.json();

  const book = $("#book");
  for (const block of App.paper.blocks) {
    book.appendChild(renderBlock(block, slug));
  }

  renderMath(book);

  // 이미지가 다 로드돼야 높이가 확정되고, 그래야 단이 제대로 나뉜다.
  // 이걸 안 기다리면 페이지 수가 틀리게 계산된다.
  await Promise.all(
    [...book.querySelectorAll("img")].map((img) =>
      img.complete
        ? Promise.resolve()
        : new Promise((r) => {
            img.addEventListener("load", r, { once: true });
            img.addEventListener("error", r, { once: true });
          })
    )
  );

  buildToc(App.paper.toc, $("#toc-list"), slug);
  measure();
  goto(0);
  $("#loading").classList.add("hidden");

  // ─── 조작 ───
  $("#next").addEventListener("click", () => goto(App.page + 1));
  $("#prev").addEventListener("click", () => goto(App.page - 1));
  $(".tap.right").addEventListener("click", () => goto(App.page + 1));
  $(".tap.left").addEventListener("click", () => goto(App.page - 1));
  $("#toc-toggle").addEventListener("click", () => $("#toc").classList.toggle("open"));

  document.addEventListener("keydown", (e) => {
    if (e.key === "ArrowRight" || e.key === " " || e.key === "PageDown") {
      e.preventDefault();
      goto(App.page + 1);
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      e.preventDefault();
      goto(App.page - 1);
    } else if (e.key === "Home") goto(0);
    else if (e.key === "End") goto(App.pageCount - 1);
  });

  // 창 크기가 바뀌면 단이 다시 흐른다. 페이지 번호는 의미를 잃으므로
  // 보고 있던 블록을 기준으로 다시 찾아간다 — 위치는 블록 id 로 기억한다.
  let resizeTimer;
  window.addEventListener("resize", () => {
    const anchor = currentBlockId();
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      $("#book").style.transition = "none";
      measure();
      if (anchor) gotoBlock(anchor);
      else goto(App.page);
      requestAnimationFrame(() => ($("#book").style.transition = ""));
    }, 120);
  });
}

/** 지금 페이지에 보이는 첫 블록의 id. 리플로우 후 되찾아갈 기준점. */
function currentBlockId() {
  for (const el of $("#book").querySelectorAll("[data-block]")) {
    if (pageOf(el) >= App.page) return el.dataset.block;
  }
  return null;
}

main();
