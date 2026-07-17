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


def _split_authors(raw: str) -> list[str]:
    """'Ai Chen, Resul Sahin, ... and Alexander Fill' → 이름 목록.

    실측(MDPI): /Author 가 쉼표로 잇고 마지막만 'and' 로 붙인 한 줄이다.
    """
    raw = re.sub(r"\s+and\s+", ", ", raw)
    names = [n.strip(" ,;") for n in raw.split(",")]
    # 이름이 아닌 조각(소속 번호 등)을 걸러낸다
    return [n for n in names if len(n) > 2 and not n.isdigit()]


def from_pdf(pdf: Path) -> dict:
    """PDF 내장 메타데이터에서 건질 수 있는 것.

    실측:
      IEEE(FireMan)   /Subject 에 DOI 가 들어 있다 ("...;10.1109/ETFA61755.2024.10710657")
                      /Title 에 진짜 영어 제목이 들어 있다
      MDPI(batteries) DOI 가 없다. 대신 /Author 에 저자 6명이 다 들어 있다.
                      → DOI 가 없으면 CrossRef 를 못 부르므로 이게 유일한 저자 출처다.
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

    authors = (info.get("/Author") or "").strip()
    if authors:
        names = _split_authors(authors)
        if names:
            out["authors"] = names

    haystack = " ".join(str(v) for v in info.values())
    m = _DOI_RE.search(haystack)
    if m:
        out["doi"] = m.group(0).rstrip(".")
    m = _ARXIV_RE.search(haystack)
    if m:
        out["arxiv_id"] = m.group(1)

    return out


_UA = {"User-Agent": "paper-reader (local reader; mailto:anonymous@example.com)"}


def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        import requests

        # CrossRef 는 연락처를 남기면 더 나은 서비스 등급을 준다 (polite pool).
        resp = requests.get(url, params=params, headers=_UA, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()["message"]
    except Exception as exc:
        logger.warning("CrossRef 조회 실패 (%s) — PDF 에서 얻은 정보로 진행한다", exc)
        return None


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def from_crossref_title(title: str) -> dict:
    """제목으로 CrossRef 를 검색한다.

    DOI 가 PDF 메타데이터에 없는 논문이 있다 (실측: MDPI batteries). 본문 1쪽에는
    찍혀 있지만 거기는 초록 앞이라 우리가 잘라내는 구간이고, 게다가 원문에서
    '10.3390/' + 줄바꿈 + 'batteries11030096' 으로 쪼개져 있어 긁어내기 어렵다.
    제목은 PDF 메타데이터에 확실히 있으므로 그걸로 찾는 편이 튼튼하다.

    엉뚱한 논문을 물어오지 않도록 제목이 실제로 일치할 때만 받아들인다.

    제목이 같아도 판본이 여럿일 수 있다. 실측: batteries 논문을 찾으면 CrossRef 가
    Preprints.org 의 **프리프린트**(10.20944/...)를 먼저 준다. 저자 목록마저 다르다
    (출판본 6명, 프리프린트 5명). 그래서 출판된 논문(journal-article)을 먼저 고른다.
    """
    msg = _get(
        "https://api.crossref.org/works",
        {"query.bibliographic": title, "rows": 5, "select": "title,author,issued,DOI,type"},
    )
    if not msg:
        return {}

    want = _norm(title)
    matches = []
    for item in msg.get("items") or []:
        titles = item.get("title") or []
        if not titles:
            continue
        got = _norm(titles[0])
        # 앞뒤가 조금 잘려도 통과시키되, 남남인 논문은 걸러낸다
        if got == want or got.startswith(want[:60]) or want.startswith(got[:60]):
            matches.append(item)

    if not matches:
        logger.info("CrossRef 에서 제목이 일치하는 논문을 찾지 못했다")
        return {}

    # posted-content(프리프린트)보다 journal-article(출판본)을 앞세운다
    matches.sort(key=lambda i: 0 if i.get("type") == "journal-article" else 1)
    best = matches[0]
    logger.info(
        "제목으로 CrossRef 에서 찾았다: %s (%s)%s",
        best.get("DOI"), best.get("type"),
        f" — 후보 {len(matches)}건 중" if len(matches) > 1 else "",
    )
    return _parse_crossref(best)


def from_crossref(doi: str) -> dict:
    """DOI 로 CrossRef 에 물어본다. 실패하면 빈 dict."""
    msg = _get(f"https://api.crossref.org/works/{doi}")
    return _parse_crossref(msg) if msg else {}


def _parse_crossref(msg: dict) -> dict:
    out: dict = {}
    if msg.get("DOI"):
        out["doi"] = msg["DOI"]
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
    """convert() 가 만든 meta 를 채워 넣는다. 원본 dict 를 수정하지 않는다.

    출처 우선순위: CrossRef > PDF 내장 메타데이터 > Docling 이 뽑은 첫 제목.
    """
    meta = dict(meta)
    pdf_meta = from_pdf(pdf)

    for key in ("title", "authors", "doi", "arxiv_id"):
        if pdf_meta.get(key):
            meta[key] = pdf_meta[key]

    if not offline:
        if meta.get("doi"):
            logger.info("CrossRef 조회: %s", meta["doi"])
            cr = from_crossref(meta["doi"])
        elif meta.get("title"):
            # DOI 가 없는 논문 (실측: MDPI batteries) — 제목으로 찾는다
            cr = from_crossref_title(meta["title"])
        else:
            cr = {}
        for key in ("title", "authors", "year", "doi"):
            if cr.get(key):
                meta[key] = cr[key]

    if not meta.get("title"):
        meta["title"] = pdf.stem

    logger.info(
        "메타데이터: %r / 저자 %d명 / %s",
        meta["title"][:50], len(meta.get("authors") or []), meta.get("year"),
    )
    return meta
