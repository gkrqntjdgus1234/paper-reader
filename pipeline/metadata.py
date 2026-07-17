"""논문 메타데이터(제목·저자·연도) 채우기.

파일명은 믿을 수 없다. 실측 예: 파일명이 "FireMan-UAV-RGBT 감지를 위한 ... (SCIE).pdf"
로 한글 번역돼 있는데 실제 제목은 영어다.

순서:
  1. PDF 내장 메타데이터에서 제목·DOI 를 본다 (IEEE·MDPI 모두 넣어준다)
  2. DOI 가 있으면 CrossRef 에 물어 저자·연도까지 정확히 채운다
  3. 다 실패하면 Docling 이 뽑은 첫 제목을 그대로 쓴다

네트워크가 없거나 조회에 실패해도 파이프라인이 죽으면 안 된다. 메타데이터는
있으면 좋은 것이지 없으면 못 읽는 게 아니다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_TIMEOUT = 10

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)
_ARXIV_RE = re.compile(r"arxiv[.:/ ]*(\d{4}\.\d{4,5})", re.I)


def from_pdf(pdf: Path) -> dict:
    """PDF 내장 메타데이터에서 건질 수 있는 것.

    실측:
      MDPI  /Subject 에 DOI 가 들어 있다 ("...;10.1109/ETFA61755.2024.10710657")
      IEEE  /Title 에 진짜 영어 제목이 들어 있다
    """
    out: dict = {}
    try:
        from pypdf import PdfReader

        info = PdfReader(str(pdf)).metadata or {}
    except Exception as exc:
        logger.debug("PDF 메타데이터를 읽지 못했다: %s", exc)
        return out

    title = (info.get("/Title") or "").strip()
    # PDF 제목이 파일명이거나 빈 껍데기인 경우가 흔하다
    if title and len(title) > 10 and not title.lower().endswith(".pdf"):
        out["title"] = title

    haystack = " ".join(str(v) for v in info.values())
    m = _DOI_RE.search(haystack)
    if m:
        out["doi"] = m.group(0).rstrip(".")
    m = _ARXIV_RE.search(haystack)
    if m:
        out["arxiv_id"] = m.group(1)

    return out


def from_crossref(doi: str) -> dict:
    """DOI 로 CrossRef 에 물어본다. 실패하면 빈 dict."""
    try:
        import requests

        # CrossRef 는 연락처를 남기면 더 나은 서비스 등급을 준다 (polite pool).
        resp = requests.get(
            f"https://api.crossref.org/works/{doi}",
            headers={"User-Agent": "paper-reader (local reader; mailto:anonymous@example.com)"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        msg = resp.json()["message"]
    except Exception as exc:
        logger.warning("CrossRef 조회 실패 (%s) — PDF 에서 얻은 정보로 진행한다", exc)
        return {}

    out: dict = {}
    titles = msg.get("title") or []
    if titles:
        out["title"] = titles[0].strip()

    authors = []
    for a in msg.get("author") or []:
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p)
        if name:
            authors.append(name)
    if authors:
        out["authors"] = authors

    for key in ("published-print", "published-online", "issued", "created"):
        parts = (msg.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            out["year"] = int(parts[0][0])
            break

    return out


def enrich(meta: dict, pdf: Path, offline: bool = False) -> dict:
    """convert() 가 만든 meta 를 채워 넣는다. 원본 dict 를 수정하지 않는다."""
    meta = dict(meta)
    pdf_meta = from_pdf(pdf)

    if pdf_meta.get("title"):
        meta["title"] = pdf_meta["title"]
    for key in ("doi", "arxiv_id"):
        if pdf_meta.get(key):
            meta[key] = pdf_meta[key]

    if meta.get("doi") and not offline:
        logger.info("CrossRef 조회: %s", meta["doi"])
        cr = from_crossref(meta["doi"])
        for key in ("title", "authors", "year"):
            if cr.get(key):
                meta[key] = cr[key]

    if not meta.get("title"):
        meta["title"] = pdf.stem

    logger.info(
        "메타데이터: %r / 저자 %d명 / %s",
        meta["title"][:50], len(meta.get("authors") or []), meta.get("year"),
    )
    return meta
