"""섹션 제목의 번호를 읽어 목차 계층을 복원한다.

Docling 은 SectionHeaderItem.level 을 전부 1 로 준다 (DOCLING_FINDINGS.md 6번).
그대로 쓰면 목차가 평평해져 "세분화 목차" 가 안 된다. 다행히 제목에 번호가 남아 있다.

지원하는 번호 형식 (테스트 논문 2편 기준):
  MDPI  : "1. Introduction"  "1.1. Motivation"  "2.1.1. Thermal Runaway Sub-Model"
  IEEE  : "I. INTRODUCTION"  "II. RELATED WORK"  →  최상위
          "A. Dataset"       "B. Evaluation"     →  그 아래
"""

from __future__ import annotations

import re

_ROMAN = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
    "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12,
}

# "1." "1.1." "2.1.1." — 마침표로 이어진 아라비아 숫자
_ARABIC_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
# "I." "IV." — 로마 숫자 (IEEE 최상위 섹션)
_ROMAN_RE = re.compile(r"^\s*([IVX]{1,5})\.\s+(\S.*)$")
# "A." "B." — 알파벳 (IEEE 하위 섹션)
_ALPHA_RE = re.compile(r"^\s*([A-Z])\.\s+(\S.*)$")


def parse_heading(text: str) -> tuple[tuple[int, ...] | None, str, str | None]:
    """제목에서 번호를 떼어낸다.

    반환: (번호 튜플, 번호 뺀 제목, 번호 종류)
      "2.1.1. Thermal Runaway"  → ((2,1,1), "Thermal Runaway", "arabic")
      "III. FIREMAN DATABASE"   → ((3,),    "FIREMAN DATABASE", "roman")
      "B. Evaluation"           → ((2,),    "Evaluation",       "alpha")
      "Temperature Rise"        → (None,    "Temperature Rise", None)
    """
    text = text.strip()

    m = _ARABIC_RE.match(text)
    if m:
        nums = tuple(int(p) for p in m.group(1).split("."))
        return nums, m.group(2).strip(), "arabic"

    m = _ROMAN_RE.match(text)
    if m:
        n = _ROMAN.get(m.group(1).lower())
        if n:
            return (n,), m.group(2).strip(), "roman"

    m = _ALPHA_RE.match(text)
    if m:
        return (ord(m.group(1)) - ord("A") + 1,), m.group(2).strip(), "alpha"

    return None, text, None


class SectionTracker:
    """제목들을 순서대로 먹여주면 section_id 와 level 을 돌려준다.

    번호 없는 제목(예: "A1-SEI Decomposition", "Temperature Rise")은 직전 섹션의
    하위로 넣는다. 논문에서 실제로 그런 위치에 있기 때문이다.
    """

    def __init__(self) -> None:
        self._current: tuple[int, ...] = ()      # 마지막 번호 있는 섹션의 번호
        self._unnumbered_count = 0               # 직전 섹션 아래 번호 없는 제목 개수

    def next(self, heading_text: str) -> tuple[str, int, str]:
        """반환: (section_id, level, 표시용 제목).

        표시용 제목은 번호를 포함한 원문이다. 번호는 계층(section_id)을 정하는 데만
        쓰고 화면에서는 지우지 않는다 — "1.4 What is not included" 에서 "1.4" 가
        사라지면 원문 대조가 어렵고 책처럼 읽기에도 어색하다.
        """
        display = heading_text.strip()
        nums, _title, kind = parse_heading(heading_text)

        if nums is None:
            # 번호 없는 제목 → 직전 섹션의 자식으로 만든다
            self._unnumbered_count += 1
            parent = self._current or (0,)
            path = parent + (self._unnumbered_count,)
            return _sec_id(path), len(path), display

        if kind == "alpha" and self._current:
            # IEEE 의 "A." 는 직전 로마숫자 섹션의 하위다: III + A → (3, 1)
            path = (self._current[0],) + nums
        else:
            path = nums

        self._current = path
        self._unnumbered_count = 0
        return _sec_id(path), len(path), display


def _sec_id(path: tuple[int, ...]) -> str:
    """(2, 1, 1) → 'sec2.1.1'  — 스키마의 sectionId 패턴을 만족해야 한다."""
    return "sec" + ".".join(str(p) for p in path)
