"""전체 텍스트 검색.

논문 수십 편에 편당 블록 수백 개 규모다. 그냥 훑어도 사람이 못 느낄 만큼 빠르므로
색인(FTS 등)을 두지 않는다. 색인은 만드는 순간 "언제 다시 만드나" 를 관리해야 하는데,
얻는 게 없다.

검색 결과는 페이지 번호가 아니라 블록 id 를 가리킨다. 페이지는 화면마다 다르다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pipeline.inline import strip_tags


@dataclass
class Hit:
    slug: str
    paper_title: str
    block_id: str
    lang: str          # 'original' | 'translated' — 어느 쪽에서 걸렸나
    snippet: str       # 검색어 앞뒤를 잘라낸 미리보기
    section: str


_SNIPPET_PAD = 45


def _snippet(text: str, at: int, length: int) -> str:
    start = max(0, at - _SNIPPET_PAD)
    end = min(len(text), at + length + _SNIPPET_PAD)
    out = text[start:end].replace("\n", " ")
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out


def _texts_of(block: dict) -> list[tuple[str, str]]:
    """이 블록에서 검색 대상이 되는 (언어, 텍스트) 목록."""
    out: list[tuple[str, str]] = []
    for lang, suffix in (("original", "_original"), ("translated", "_translated")):
        for field in ("text", "caption"):
            value = block.get(f"{field}{suffix}")
            if value:
                out.append((lang, strip_tags(value)))
        items = block.get(f"items{suffix}")
        if items:
            out.append((lang, " ".join(strip_tags(i) for i in items)))
    return out


def search_paper(paper_dir: Path, slug: str, query: str, limit: int = 40) -> list[Hit]:
    try:
        doc = json.loads((paper_dir / "paper.json").read_text(encoding="utf-8"))
    except Exception:
        return []

    pattern = re.compile(re.escape(query), re.I)
    title = doc.get("meta", {}).get("title") or slug

    # 블록이 어느 섹션에 속하는지 — 결과에 맥락을 주려고
    section_titles: dict[str, str] = {}

    def walk(nodes):
        for n in nodes:
            section_titles[n["id"]] = n["title"]
            walk(n["children"])

    walk(doc.get("toc") or [])

    hits: list[Hit] = []
    for block in doc.get("blocks") or []:
        for lang, text in _texts_of(block):
            m = pattern.search(text)
            if not m:
                continue
            hits.append(
                Hit(
                    slug=slug,
                    paper_title=title,
                    block_id=block["id"],
                    lang=lang,
                    snippet=_snippet(text, m.start(), len(query)),
                    section=section_titles.get(block.get("section_id", ""), ""),
                )
            )
            if len(hits) >= limit:
                return hits
    return hits


def search_all(papers: dict, query: str, limit_per_paper: int = 8) -> list[Hit]:
    query = query.strip()
    if len(query) < 2:
        return []   # 한 글자로는 결과가 너무 많아 쓸모가 없다

    hits: list[Hit] = []
    for slug, paper in papers.items():
        hits.extend(search_paper(paper.dir, slug, query, limit=limit_per_paper))
    return hits
