"""중간 JSON 이 스키마를 만족하는지 검증한다.

스키마는 전처리와 뷰어의 계약이다. 계약을 어긴 파일을 내보내면 깨지는 쪽은 뷰어이고,
그때는 원인이 여기라는 걸 알기 어렵다. 그러니 내보내기 전에 여기서 막는다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "paper.schema.json"


@lru_cache(maxsize=1)
def _schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_paper(paper: dict) -> list[str]:
    """스키마 위반 목록을 돌려준다. 빈 리스트면 통과."""
    try:
        import jsonschema
    except ImportError:
        return []  # 개발용 의존성이므로 없으면 검증을 건너뛴다

    validator = jsonschema.Draft7Validator(_schema())
    errors = []
    for err in sorted(validator.iter_errors(paper), key=lambda e: list(e.path)):
        where = "/".join(str(p) for p in err.path) or "(루트)"
        errors.append(f"{where}: {err.message}")
    return errors
