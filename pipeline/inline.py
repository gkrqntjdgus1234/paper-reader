"""문단 텍스트의 인라인 태그 처리.

스키마의 핵심 계약(SCHEMA.md 2번):
  <c id="ref12"/>  인용   → references 의 항목을 가리킴
  <m id="m1"/>     수식   → 같은 블록의 inline_math 를 가리킴

이 태그들은 DeepL 의 ignore_tags 로 보호되어 번역 중에도 살아남는다.
태그가 성립하려면 텍스트가 XML-safe 여야 하므로 & < > 를 이스케이프한다.
"""

from __future__ import annotations

import re

# 본문의 인용 표시. IEEE·MDPI 둘 다 대괄호 번호식이다.
#   [12]        단일
#   [8,9]       나열
#   [3-5]       범위
#   [8,9,12-14] 혼합
_CITATION_RE = re.compile(r"\[(\d+(?:\s*[,–—-]\s*\d+)*)\]")


def escape_xml(text: str) -> str:
    """태그 처리가 성립하도록 XML 특수문자를 이스케이프한다.

    따옴표는 건드리지 않는다 — 본문에 흔하고, 속성값 안에 들어갈 일이 없다.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def unescape_xml(text: str) -> str:
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _expand_citation_group(group: str) -> list[int]:
    """'8,9' → [8, 9] / '12-14' → [12, 13, 14] / '3,5-7' → [3, 5, 6, 7]"""
    numbers: list[int] = []
    for part in re.split(r"\s*,\s*", group):
        m = re.fullmatch(r"(\d+)\s*[–—-]\s*(\d+)", part)
        if m:
            start, end = int(m.group(1)), int(m.group(2))
            if start <= end and end - start < 100:  # 범위가 터무니없으면 무시
                numbers.extend(range(start, end + 1))
        elif part.strip().isdigit():
            numbers.append(int(part.strip()))
    return numbers


def tag_citations(text: str, known_refs: set[int] | None = None) -> tuple[str, list[str]]:
    """본문의 [12] 를 <c id="ref12"/> 태그로 바꾼다.

    known_refs 를 주면 그 안에 있는 번호만 인용으로 취급한다. 참고문헌이 29개인데
    본문에 [2024] 같은 게 있으면 인용이 아니라 연도이므로 거르기 위한 것이다.

    반환: (태그가 박힌 텍스트, 이 텍스트가 참조하는 ref id 목록)
    """
    cited: list[str] = []

    def replace(match: re.Match) -> str:
        numbers = _expand_citation_group(match.group(1))
        if not numbers:
            return match.group(0)
        if known_refs is not None and not all(n in known_refs for n in numbers):
            return match.group(0)  # 참고문헌에 없는 번호 → 인용이 아니다

        tags = []
        for n in numbers:
            ref_id = f"ref{n}"
            if ref_id not in cited:
                cited.append(ref_id)
            tags.append(f'<c id="{ref_id}"/>')
        return "".join(tags)

    return _CITATION_RE.sub(replace, text), cited


def strip_tags(text: str) -> str:
    """태그를 걷어낸 순수 텍스트. 검증·글자수 계산용."""
    return re.sub(r"<[cm] id=\"[^\"]+\"/>", "", text)


def tags_in(text: str) -> list[str]:
    """텍스트에 든 태그 목록. 번역 전후 비교에 쓴다."""
    return re.findall(r"<[cm] id=\"[^\"]+\"/>", text)
