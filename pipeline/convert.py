"""DoclingDocument → 중간 JSON (schema/paper.schema.json).

여기가 Phase 1 의 본체다. DOCLING_FINDINGS.md 에 적힌 함정들을 전부 여기서 흡수한다:
  - 마크다운을 거치지 않고 iterate_items() 로 직접 순회 (마크다운엔 수식이 비어 있다)
  - 수식 꼬리의 "\\quad ( 1 )" 을 number 로 분리
  - 캡션(label=caption)을 위치로 그림·표에 붙임 (Docling 이 연결해주지 않는다)
  - 섹션 계층을 제목 번호로 복원 (전부 level=1 로 오므로)
  - 참고문헌은 References 헤더 뒤의 ListItem 이고, 번호가 없으므로 순서가 곧 번호
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from pipeline.inline import escape_xml, tag_citations
from pipeline.sections import SectionTracker

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"

# 수식에 붙어 나오는 번호.
# 실측: '... \exp \left( ... \right) \quad ( 1 ) \quad i n g e'
#   → 꼬리에만 있는 게 아니라 뒤에 잡음이 더 붙기도 한다. 그래서 끝(\Z)에 고정하지 않는다.
# "\quad (n)" 은 수식 번호를 뜻하는 강한 신호다. 반면 맨 끝의 "(n)" 만으로는
# 판단하지 않는다 — 수식 자체의 괄호일 수 있다.
_EQ_NUMBER_RES = [
    re.compile(r"\\quad\s*\(\s*(\d+[a-z]?)\s*\)"),
    re.compile(r"\\tag\s*\{\s*(\d+[a-z]?)\s*\}"),
]

# 본문 시작 지점. 이 앞은 저자·소속·이메일이라 "책처럼 읽기"에 방해된다.
_ABSTRACT_RE = re.compile(r"^\s*abstract\b", re.I)


def _label(item: Any) -> str:
    """DocItemLabel 은 str 이 섞인 enum 이라 str() 로 비교하면 표현이 갈린다."""
    lab = getattr(item, "label", None)
    return str(getattr(lab, "value", lab) or "")


def _prov(item: Any):
    provs = getattr(item, "prov", None)
    return provs[0] if provs else None


def split_equation_number(latex: str) -> tuple[str, str | None]:
    """수식 LaTeX 에서 번호를 떼어낸다.

    실측 예: '\\frac{...}{dt} = ... \\quad ( 1 )'  →  ('\\frac{...}{dt} = ...', '(1)')
    떼지 않으면 번호가 수식의 일부처럼 렌더된다.
    """
    latex = latex.strip()
    for pattern in _EQ_NUMBER_RES:
        m = pattern.search(latex)
        if m:
            # 번호 자리를 도려내고 앞뒤를 잇는다. 번호 뒤에 모델이 흘린 잡음이
            # 붙어 있으면 그것도 함께 버린다 — 수식의 일부가 아니다.
            return latex[: m.start()].strip(), f"({m.group(1)})"
    return latex, None


def _find_caption(items: list, start: int) -> str:
    """start 번째 아이템(그림·표) 바로 뒤에 오는 캡션을 찾는다.

    실측(FireMan·MDPI 모두): Docling 의 읽기 순서에서 캡션은 예외 없이 그림·표
    **바로 다음** 아이템이다.

        #14 PictureItem → #15 caption 'Fig. 1: ...'
        #52 TableItem   → #53 caption 'TABLE I: ...'

    처음엔 'Figure N' 의 번호로 매칭했는데 틀렸다. 그림 하나만 누락돼도 그 뒤가
    전부 한 칸씩 밀려 엉뚱한 캡션이 붙는다 (실제로 그렇게 됐었다). 인접성은
    번호 형식(Fig./Figure/TABLE I 로마숫자)에도 의존하지 않아 더 튼튼하다.
    """
    if start + 1 < len(items) and _label(items[start + 1][0]) == "caption":
        return (getattr(items[start + 1][0], "text", "") or "").strip()
    return ""


def _extract_references(items: list) -> tuple[list[dict], int]:
    """References 헤더 뒤의 ListItem 들을 참고문헌으로 뽑는다.

    실측: Docling 이 번호([1] 등)를 떼고 주므로 등장 순서가 곧 번호다.
    (검증: 8·9번 자리에 Richard & Dahn 두 편 → 본문의 [8,9] 와 일치)

    반환: (references, References 헤더의 아이템 인덱스). 헤더가 없으면 인덱스 -1.
    """
    start = -1
    for i, (item, _) in enumerate(items):
        if _label(item) == "section_header":
            title = (getattr(item, "text", "") or "").strip().lower()
            if title in ("references", "reference", "bibliography"):
                start = i
                break

    if start < 0:
        logger.warning("References 섹션을 찾지 못했다 — 인용 각주가 비게 된다")
        return [], -1

    refs: list[dict] = []
    for item, _ in items[start + 1 :]:
        if type(item).__name__ != "ListItem":
            continue
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        n = len(refs) + 1
        refs.append({
            "id": f"ref{n}",
            "marker": f"[{n}]",
            "text": text,
            "doi": _find_doi(text),
        })

    logger.info("참고문헌 %d개", len(refs))
    return refs, start


_DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:a-z0-9]+", re.I)


def _find_doi(text: str) -> str | None:
    m = _DOI_RE.search(text)
    return m.group(0).rstrip(".") if m else None


def _save_picture(item: Any, doc: Any, out_dir: Path, index: int) -> str | None:
    """그림을 파일로 저장하고 상대 경로를 돌려준다."""
    try:
        image = item.get_image(doc)
    except Exception as exc:
        logger.debug("그림 이미지 추출 실패: %s", exc)
        return None
    if image is None:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"fig{index:03d}.png"
    image.save(out_dir / name)
    return f"figures/{name}"


def _find_body_start(items: list) -> int:
    """본문이 시작되는 아이템 인덱스. 초록(Abstract)부터가 본문이다.

    그 앞은 저자·소속·이메일·로고인데, 조각나서 '† ⋆ ⋆' 같은 블록까지 생긴다.
    책처럼 읽는 게 목적이므로 1쪽부터 이런 게 나오면 안 된다.
    초록을 못 찾으면 아무것도 버리지 않는다 — 본문을 통째로 날리는 것보다 낫다.
    """
    for i, (item, _) in enumerate(items):
        if _ABSTRACT_RE.match(getattr(item, "text", "") or ""):
            return i
    logger.warning("초록을 찾지 못했다 — 앞부분(저자·소속)이 본문에 섞일 수 있다")
    return 0


def convert(doc: Any, source_pdf: str, figures_dir: Path) -> dict:
    """DoclingDocument 를 중간 JSON dict 로 바꾼다."""
    items = list(doc.iterate_items())

    references, ref_header_idx = _extract_references(items)
    known_refs = {int(r["id"][3:]) for r in references}

    tracker = SectionTracker()
    blocks: list[dict] = []
    toc: list[dict] = []
    toc_stack: list[dict] = []

    section_id = "sec0"          # 첫 제목 전에 나오는 초록 등이 갈 곳
    pending_list: list[str] = []  # 연속된 ListItem 을 하나의 list 블록으로 묶는다
    pending_list_cites: list[str] = []
    fig_index = 0

    def bid() -> str:
        return f"b{len(blocks) + 1:04d}"

    def flush_list() -> None:
        nonlocal pending_list, pending_list_cites
        if not pending_list:
            return
        blocks.append({
            "id": bid(),
            "type": "list",
            "section_id": section_id,
            "ordered": False,
            "items_original": pending_list,
            "items_translated": None,
            "inline_math": [],
            "citations": list(dict.fromkeys(pending_list_cites)),
        })
        pending_list = []
        pending_list_cites = []

    # References 이후는 참고문헌 목록이므로 본문 블록으로 넣지 않는다
    end = ref_header_idx if ref_header_idx >= 0 else len(items)
    body_start = _find_body_start(items)

    i = body_start
    while i < end:
        item, _level = items[i]
        kind = type(item).__name__
        label = _label(item)
        text = (getattr(item, "text", "") or "").strip()

        # 캡션은 그림·표에 붙여 쓰므로 본문 블록으로 만들지 않는다
        if label == "caption":
            i += 1
            continue

        if kind == "SectionHeaderItem":
            flush_list()
            # 논문 제목도 SectionHeaderItem 이지만 초록보다 앞에 있으므로
            # body_start 덕분에 여기까지 오지 않는다. 따로 걸러낼 필요가 없다.
            section_id, level, clean_title = tracker.next(text)
            block_id = bid()
            blocks.append({
                "id": block_id,
                "type": "heading",
                "section_id": section_id,
                "level": level,
                "text_original": escape_xml(clean_title),
                "text_translated": None,
            })
            node = {
                "id": section_id,
                "title": clean_title,
                "title_translated": None,
                "level": level,
                "block_id": block_id,
                "children": [],
            }
            while toc_stack and toc_stack[-1]["level"] >= level:
                toc_stack.pop()
            (toc_stack[-1]["children"] if toc_stack else toc).append(node)
            toc_stack.append(node)
            i += 1
            continue

        if kind == "FormulaItem":
            flush_list()
            if not text:
                # 수식 인식이 꺼져 있거나 모델이 못 읽은 경우. 빈 수식 블록은 무의미하다.
                logger.debug("빈 수식 아이템 건너뜀")
                i += 1
                continue
            latex, number = split_equation_number(text)
            blocks.append({
                "id": bid(),
                "type": "equation",
                "section_id": section_id,
                "latex": latex,
                "number": number,
            })
            i += 1
            continue

        if kind == "TableItem":
            flush_list()
            try:
                html = item.export_to_html(doc=doc)
            except Exception as exc:
                logger.warning("표 HTML 추출 실패: %s", exc)
                i += 1
                continue
            blocks.append({
                "id": bid(),
                "type": "table",
                "section_id": section_id,
                "table_html_original": html,
                "table_html_translated": None,
                "caption_original": _find_caption(items, i),
                "caption_translated": None,
                "full_page": True,
                "citations": [],
            })
            i += 1
            continue

        if kind == "PictureItem":
            flush_list()
            # 연속된 그림들은 (a)(b) 로 나뉜 복합 그림이고 캡션 하나를 공유한다
            # (실측: FireMan Fig. 6 = 그림 2개). 한 덩어리로 묶어 한 쪽에 배치한다.
            run_end = i
            while run_end < end and type(items[run_end][0]).__name__ == "PictureItem":
                run_end += 1

            caption = _find_caption(items, run_end - 1)
            if not caption:
                # 캡션 없는 그림은 로고·아이콘이다. 크기로 거르지 않는 이유:
                # 실측에서 68x75 짜리 진짜 그림(FireMan Fig. 3)이 있었다. 크기 필터를
                # 쓰면 그걸 버리고, 그 뒤 캡션이 전부 밀려 엉뚱한 그림에 붙는다.
                logger.debug("캡션 없는 그림 %d개 건너뜀 (로고로 판단)", run_end - i)
                i = run_end
                continue

            paths = []
            for item_in_run, _ in items[i:run_end]:
                fig_index += 1
                path = _save_picture(item_in_run, doc, figures_dir, fig_index)
                if path:
                    paths.append(path)
                else:
                    fig_index -= 1

            if paths:
                blocks.append({
                    "id": bid(),
                    "type": "figure",
                    "section_id": section_id,
                    "image_paths": paths,
                    "caption_original": caption,
                    "caption_translated": None,
                    "full_page": True,
                    "citations": [],
                })
            i = run_end
            continue

        if kind == "ListItem":
            if not text:
                i += 1
                continue
            tagged, cites = tag_citations(escape_xml(text), known_refs)
            pending_list.append(tagged)
            pending_list_cites.extend(cites)
            i += 1
            continue

        if kind == "TextItem" and label in ("text", "paragraph"):
            flush_list()
            if not text:
                i += 1
                continue
            tagged, cites = tag_citations(escape_xml(text), known_refs)
            blocks.append({
                "id": bid(),
                "type": "paragraph",
                "section_id": section_id,
                "text_original": tagged,
                "text_translated": None,
                "inline_math": [],
                "citations": cites,
            })
            i += 1
            continue

        i += 1  # 위에서 걸리지 않은 아이템 (footnote, page_header 등)

    flush_list()

    return {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "title": _guess_title(doc, items),
            "authors": [],
            "year": None,
            "source_pdf": source_pdf,
            "lang": "en",
            "doi": None,
            "arxiv_id": None,
            "translated_lang": None,
        },
        "toc": toc,
        "blocks": blocks,
        "references": references,
    }


def _guess_title(doc: Any, items: list) -> str:
    """제목은 첫 SectionHeaderItem 이다 (실측). 메타데이터 조회는 metadata.py 가 덮어쓴다."""
    for item, _ in items:
        if _label(item) == "section_header":
            return (getattr(item, "text", "") or "").strip()
    return getattr(doc, "name", "") or "제목 없음"
