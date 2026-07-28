"""중간 JSON → EPUB.

핸드폰 전자책 앱에서 읽으려는 용도다. EPUB 은 정해진 구조의 zip 파일이라
외부 라이브러리 없이 표준 zipfile 로 만든다.

우리가 이미 만들어 둔 것을 그대로 쓴다: 블록 순서(읽기 순서), 목차 계층, 번역,
그림. 페이지네이션은 넣지 않는다 — 전자책 앱이 화면에 맞춰 알아서 나눈다.
"""

from __future__ import annotations

import re
import zipfile
from html import escape
from pathlib import Path
from xml.sax.saxutils import quoteattr

# 하이라이트/각주 없이, 읽기에 집중한 단순한 스타일
_CSS = """\
body { font-family: serif; line-height: 1.7; margin: 0 5%; }
h1 { font-size: 1.5em; margin: 1.2em 0 .6em; }
h2 { font-size: 1.3em; margin: 1.1em 0 .5em; }
h3 { font-size: 1.15em; margin: 1em 0 .4em; }
h4 { font-size: 1em; margin: 1em 0 .4em; color: #555; }
p { margin: 0 0 .8em; text-align: justify; }
figure { margin: 1.2em 0; text-align: center; page-break-inside: avoid; }
figure img { max-width: 100%; }
figcaption { font-size: .85em; color: #555; margin-top: .4em; }
table { border-collapse: collapse; font-size: .8em; margin: 1em 0; width: 100%; }
th, td { border: 1px solid #ccc; padding: 4px 7px; text-align: left; }
th { background: #f0ece3; }
.eq { text-align: center; margin: 1em 0; font-style: italic; }
.eq-num { color: #888; font-style: normal; float: right; }
.cite { vertical-align: super; font-size: .75em; color: #806040; }
.refs li { margin-bottom: .5em; font-size: .9em; }
sup { line-height: 0; }
"""


def _inline_to_html(text: str, inline_math: list | None, use_translation: bool) -> str:
    """중간 JSON 의 <c>/<m> 태그를 EPUB 용 HTML 로 바꾼다.

    text 는 이미 XML-safe(&amp; 등) 하므로 그대로 두고 태그만 치환한다.
    수식은 전자책이 KaTeX 를 못 돌리므로 LaTeX 원문을 그대로 보여준다.
    """
    math = {m["id"]: m["latex"] for m in (inline_math or [])}

    def repl_cite(m):
        n = m.group(1)[3:]  # ref12 → 12
        return f'<sup class="cite">[{escape(n)}]</sup>'

    def repl_math(m):
        latex = math.get(m.group(1), "")
        return f"<code>{escape(latex)}</code>"

    text = re.sub(r'<c id="(ref\d+)"/>', repl_cite, text)
    text = re.sub(r'<m id="(m\d+)"/>', repl_math, text)
    return text


def _pick(block: dict, field: str, use_translation: bool) -> str:
    """번역본을 만들 때는 번역을, 없으면 원문을 쓴다."""
    if use_translation:
        t = block.get(f"{field}_translated")
        if t:
            return t
    return block.get(f"{field}_original", "")


def _blocks_to_html(paper: dict, use_translation: bool, img_names: dict) -> str:
    parts: list[str] = []

    for block in paper["blocks"]:
        t = block["type"]

        if t == "heading":
            level = min(block["level"] + 1, 4)  # h2~h4 (h1 은 논문 제목)
            text = _pick(block, "text", use_translation)
            anchor = block["section_id"]
            parts.append(f'<h{level} id={quoteattr(anchor)}>{escape(text)}</h{level}>')

        elif t == "paragraph":
            html = _inline_to_html(
                _pick(block, "text", use_translation), block.get("inline_math"), use_translation
            )
            parts.append(f"<p>{html}</p>")

        elif t == "list":
            items = (use_translation and block.get("items_translated")) or block["items_original"]
            lis = "".join(
                f"<li>{_inline_to_html(i, block.get('inline_math'), use_translation)}</li>"
                for i in items
            )
            tag = "ol" if block.get("ordered") else "ul"
            parts.append(f"<{tag}>{lis}</{tag}>")

        elif t == "equation":
            num = f'<span class="eq-num">{escape(block["number"])}</span>' if block.get("number") else ""
            parts.append(f'<p class="eq">{num}<code>{escape(block["latex"])}</code></p>')

        elif t == "figure":
            imgs = "".join(
                f'<img src={quoteattr("images/" + img_names[p])} alt=""/>'
                for p in block["image_paths"] if p in img_names
            )
            cap = _pick(block, "caption", use_translation)
            cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
            parts.append(f"<figure>{imgs}{cap_html}</figure>")

        elif t == "table":
            html = _pick(block, "table_html", use_translation)
            cap = _pick(block, "caption", use_translation)
            cap_html = f"<figcaption>{escape(cap)}</figcaption>" if cap else ""
            parts.append(f"<figure>{html}{cap_html}</figure>")

    # 참고문헌
    if paper.get("references"):
        parts.append("<h2>References</h2><ol class='refs'>")
        for ref in paper["references"]:
            text = escape(ref["text"])
            if ref.get("doi"):
                text += f' <a href={quoteattr("https://doi.org/" + ref["doi"])}>doi</a>'
            parts.append(f"<li>{text}</li>")
        parts.append("</ol>")

    return "\n".join(parts)


def _nav_html(paper: dict, title: str) -> str:
    """EPUB3 목차 (nav). 계층을 그대로 중첩한다."""
    def walk(nodes):
        if not nodes:
            return ""
        out = ["<ol>"]
        for n in nodes:
            t = n.get("title_translated") or n["title"]
            out.append(f'<li><a href={quoteattr("content.xhtml#" + n["id"])}>{escape(t)}</a>')
            out.append(walk(n["children"]))
            out.append("</li>")
        out.append("</ol>")
        return "".join(out)

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>{escape(title)}</title></head><body>"
        f'<nav epub:type="toc"><h1>목차</h1>{walk(paper["toc"])}</nav>'
        "</body></html>"
    )


def build_epub(paper: dict, paper_dir: Path, out: Path, translated: bool | None = None) -> Path:
    """중간 JSON 을 EPUB 파일로 만든다.

    translated=None 이면 번역이 있을 때 번역본을, 없으면 원문을 만든다.
    """
    meta = paper["meta"]
    has_tr = bool(meta.get("translated_lang"))
    use_tr = has_tr if translated is None else (translated and has_tr)

    title = meta.get("title") or "논문"
    authors = meta.get("authors") or []
    lang = (meta.get("translated_lang") if use_tr else meta.get("lang")) or "en"

    # 그림 파일을 모은다. 경로가 중복되지 않게 이름만 뽑는다.
    img_names: dict[str, str] = {}
    for block in paper["blocks"]:
        if block["type"] == "figure":
            for p in block["image_paths"]:
                if p not in img_names:
                    img_names[p] = Path(p).name

    body = _blocks_to_html(paper, use_tr, img_names)
    content = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml">'
        f"<head><title>{escape(title)}</title>"
        '<link rel="stylesheet" href="style.css"/></head><body>'
        f"<h1>{escape(title)}</h1>"
        + (f"<p><em>{escape(', '.join(authors))}</em></p>" if authors else "")
        + body
        + "</body></html>"
    )

    author_meta = "".join(
        f"<dc:creator>{escape(a)}</dc:creator>" for a in authors
    )
    manifest_imgs = "".join(
        f'<item id="img{i}" href={quoteattr("images/" + name)} '
        f'media-type="{_media_type(name)}"/>'
        for i, name in enumerate(dict.fromkeys(img_names.values()))
    )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(title)}</dc:title>"
        f"<dc:language>{escape(lang)}</dc:language>"
        f'<dc:identifier id="id">paper-reader-{escape(meta.get("source_pdf", "paper"))}</dc:identifier>'
        f"{author_meta}"
        "</metadata>"
        "<manifest>"
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="content" href="content.xhtml" media-type="application/xhtml+xml"/>'
        '<item id="css" href="style.css" media-type="text/css"/>'
        f"{manifest_imgs}"
        "</manifest>"
        '<spine><itemref idref="nav"/><itemref idref="content"/></spine>'
        "</package>"
    )

    container = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype 은 압축하지 않고 맨 처음에 넣어야 한다 (EPUB 규격)
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", _nav_html(paper, title))
        z.writestr("OEBPS/content.xhtml", content)
        z.writestr("OEBPS/style.css", _CSS)
        for rel_path, name in img_names.items():
            img_file = paper_dir / rel_path
            if img_file.exists():
                z.write(img_file, f"OEBPS/images/{name}")

    return out


def _media_type(name: str) -> str:
    ext = Path(name).suffix.lower()
    return {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".svg": "image/svg+xml"}.get(ext, "image/png")
