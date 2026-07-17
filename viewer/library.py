"""data/ 폴더를 훑어 읽을 수 있는 논문 목록을 만든다."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Paper:
    slug: str
    dir: Path
    title: str
    authors: list[str]
    year: int | None
    translated: bool
    block_count: int
    block_ids: list[str]

    @property
    def json_path(self) -> Path:
        return self.dir / "paper.json"


def reading_progress(paper: Paper, position: str | None) -> int:
    """어디까지 읽었나, 0~100.

    페이지 번호로 재지 않는다. 페이지는 글자 크기와 창 크기에 따라 매번 달라진다
    (실측: 같은 논문이 15px 에서 35쪽, 26px 에서 68쪽). 대신 저장된 블록이 전체
    블록 중 몇 번째인지로 잰다 — 이건 화면과 무관하다.
    """
    if not position or not paper.block_ids:
        return 0
    try:
        idx = paper.block_ids.index(position)
    except ValueError:
        return 0
    return round((idx + 1) / len(paper.block_ids) * 100)


def _slugify(name: str) -> str:
    """폴더 이름 → URL 에 넣기 안전한 짧은 id.

    폴더 이름에 한글·공백·괄호가 섞여 있다 (실측: "FireMan-UAV-RGBT 감지를 ... (SCIE)").
    URL 에 그대로 넣으면 퍼센트 인코딩으로 길고 지저분해진다. 그래서 아스키만 남기고,
    이름이 겹치거나 아스키가 하나도 안 남는 경우를 대비해 해시를 뒤에 붙인다.
    """
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", name).strip("-").lower()[:40]
    digest = hashlib.sha256(name.encode()).hexdigest()[:6]
    return f"{ascii_part}-{digest}" if ascii_part else digest


def scan(data_dir: Path) -> dict[str, Paper]:
    """data/*/paper.json 을 모아 slug → Paper 로 돌려준다."""
    papers: dict[str, Paper] = {}
    if not data_dir.exists():
        return papers

    for json_file in sorted(data_dir.glob("*/paper.json")):
        try:
            doc = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("%s 를 읽지 못했다: %s", json_file, exc)
            continue

        meta = doc.get("meta", {})
        folder = json_file.parent
        slug = _slugify(folder.name)
        blocks = doc.get("blocks") or []
        papers[slug] = Paper(
            slug=slug,
            dir=folder,
            title=meta.get("title") or folder.name,
            authors=meta.get("authors") or [],
            year=meta.get("year"),
            translated=bool(meta.get("translated_lang")),
            block_count=len(blocks),
            block_ids=[b["id"] for b in blocks],
        )

    return papers
