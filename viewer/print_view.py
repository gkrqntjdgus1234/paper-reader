"""인쇄용 HTML — Chrome 으로 PDF 를 뽑기 위한 페이지.

화면 뷰어의 페이지네이션(CSS 다단)은 스크롤용이라 종이 PDF 에 맞지 않는다.
인쇄는 브라우저의 인쇄 엔진이 종이 크기에 맞춰 알아서 페이지를 나누므로,
여기서는 그냥 위에서 아래로 흐르는 단순한 문서를 만든다.

수식은 KaTeX 를 CDN 으로 불러 렌더한다 (인쇄 시점에 이미 그려져 있게).
"""

from __future__ import annotations

import re
from html import escape
from xml.sax.saxutils import quoteattr

_PRINT_CSS = """\
@page { margin: 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Noto Serif KR", "Nanum Myeongjo", serif;
  font-size: 11pt; line-height: 1.75; color: #1a1a1a;
  max-width: 720px; margin: 0 auto; padding: 0 8px;
}
h1.doc-title { font-size: 19pt; line-height: 1.3; margin: 0 0 6pt; }
.authors { color: #555; font-size: 10pt; margin-bottom: 20pt; }
h2, h3, h4 { line-height: 1.35; margin: 16pt 0 6pt; break-after: avoid; }
h2 { font-size: 14pt; } h3 { font-size: 12pt; } h4 { font-size: 11pt; color: #444; }
p { margin: 0 0 8pt; text-align: justify; }
ul, ol { margin: 0 0 8pt; padding-left: 20pt; }
li { margin-bottom: 3pt; }
figure { margin: 12pt 0; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; max-height: 220mm; }
figcaption { font-size: 9pt; color: #555; margin-top: 4pt; }
table { border-collapse: collapse; font-size: 8.5pt; margin: 8pt auto; }
th, td { border: 1px solid #bbb; padding: 3pt 6pt; text-align: left; }
th { background: #f0ece3; }
.equation { text-align: center; margin: 10pt 0; break-inside: avoid; }
.eq-number { color: #888; font-size: 9pt; }
sup.cite { color: #806040; font-size: .75em; }
.katex-error { color: #c0392b; }
.refs { font-size: 9.5pt; }
.refs li { margin-bottom: 4pt; }
h2.refs-title { break-before: page; }
"""


def _inline(text: str, math: dict) -> str:
    def cite(m):
        return f'<sup class="cite">[{escape(m.group(1)[3:])}]</sup>'

    def mth(m):
        latex = math.get(m.group(1), "")
        return f'<span class="imath" data-latex={quoteattr(latex)}></span>'

    text = re.sub(r'<c id="(ref\d+)"/>', cite, text)
    text = re.sub(r'<m id="(m\d+)"/>', mth, text)
    return text


def _pick(block: dict, field: str, translated: bool) -> str:
    if translated:
        t = block.get(f"{field}_translated")
        if t:
            return t
    return block.get(f"{field}_original", "")


def render_print_html(paper: dict, slug: str, translated: bool) -> str:
    meta = paper["meta"]
    title = meta.get("title") or "논문"
    authors = meta.get("authors") or []

    parts: list[str] = [f'<h1 class="doc-title">{escape(title)}</h1>']
    if authors:
        parts.append(f'<div class="authors">{escape(", ".join(authors))}</div>')

    for block in paper["blocks"]:
        t = block["type"]
        if t == "heading":
            lv = min(block["level"] + 1, 4)
            parts.append(f"<h{lv}>{escape(_pick(block, 'text', translated))}</h{lv}>")
        elif t == "paragraph":
            math = {m["id"]: m["latex"] for m in block.get("inline_math") or []}
            parts.append(f"<p>{_inline(_pick(block, 'text', translated), math)}</p>")
        elif t == "list":
            items = (translated and block.get("items_translated")) or block["items_original"]
            math = {m["id"]: m["latex"] for m in block.get("inline_math") or []}
            lis = "".join(f"<li>{_inline(i, math)}</li>" for i in items)
            parts.append(f"<{'ol' if block.get('ordered') else 'ul'}>{lis}</{'ol' if block.get('ordered') else 'ul'}>")
        elif t == "equation":
            num = f'<span class="eq-number">{escape(block["number"])}</span>' if block.get("number") else ""
            parts.append(
                f'<div class="equation"><span class="dmath" data-latex={quoteattr(block["latex"])}></span> {num}</div>'
            )
        elif t == "figure":
            imgs = "".join(
                f'<img src={quoteattr(f"/papers/{slug}/{p}")} alt=""/>'
                for p in block["image_paths"]
            )
            cap = _pick(block, "caption", translated)
            cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
            parts.append(f"<figure>{imgs}{cap_html}</figure>")
        elif t == "table":
            html = _pick(block, "table_html", translated)
            cap = _pick(block, "caption", translated)
            cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
            parts.append(f"<figure>{html}{cap_html}</figure>")

    if paper.get("references"):
        parts.append('<h2 class="refs-title">References</h2><ol class="refs">')
        for ref in paper["references"]:
            parts.append(f"<li>{escape(ref['text'])}</li>")
        parts.append("</ol>")

    body = "\n".join(parts)

    return f"""<!DOCTYPE html>
<html lang="{escape((meta.get('translated_lang') if translated else meta.get('lang')) or 'en')}">
<head>
<meta charset="utf-8">
<title>{escape(title)}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<style>{_PRINT_CSS}</style>
</head>
<body>
{body}
<script>
  // 수식을 그려 둔다. 인쇄(PDF 변환)는 이게 끝난 뒤에 이뤄져야 한다.
  document.addEventListener("DOMContentLoaded", function () {{
    document.querySelectorAll(".dmath").forEach(function (el) {{
      katex.render(el.dataset.latex, el, {{ displayMode: true, throwOnError: false }});
    }});
    document.querySelectorAll(".imath").forEach(function (el) {{
      katex.render(el.dataset.latex, el, {{ displayMode: false, throwOnError: false }});
    }});
    window.__ready = true;   // PDF 변환기가 이 값을 보고 시작한다
  }});
</script>
</body>
</html>"""
