"""읽기 상태 저장 (SQLite).

무엇을 저장하는가: 마지막 읽던 위치, 북마크, 하이라이트·메모.

**전부 블록 id 기준이다. 페이지 번호가 아니다** (SCHEMA.md 1번).
글자 크기를 바꾸면 페이지 번호는 의미를 잃는다 — 실측으로 확인했다:
같은 블록이 글자 15px 에서 16쪽, 26px 에서 31쪽이었다. 페이지 번호로 저장했으면
글자 크기를 바꾸는 순간 북마크가 전부 엉뚱한 데를 가리킨다.

하이라이트는 블록 안에서의 글자 오프셋으로 잡는다. 블록 텍스트는 재처리 전까지
변하지 않으므로 리플로우와 무관하게 유효하다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reading_state (
    slug        TEXT PRIMARY KEY,
    block_id    TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL,
    block_id    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (slug, block_id)
);

CREATE TABLE IF NOT EXISTS highlights (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL,
    block_id    TEXT NOT NULL,
    lang        TEXT NOT NULL,      -- 'original' | 'translated'
    start       INTEGER NOT NULL,   -- 블록 텍스트 안에서의 시작 글자 위치
    end         INTEGER NOT NULL,
    text        TEXT NOT NULL,      -- 하이라이트된 대목 (목록에 보여주려고)
    note        TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_highlights_slug ON highlights (slug);
CREATE INDEX IF NOT EXISTS idx_bookmarks_slug ON bookmarks (slug);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        # Flask 의 요청마다 스레드가 다를 수 있으므로 연결을 들고 있지 않고 그때그때 연다.
        # 로컬 단일 사용자라 이 정도 비용은 문제되지 않는다.
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── 마지막 읽던 위치 ───────────────────────────────

    def get_position(self, slug: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT block_id FROM reading_state WHERE slug = ?", (slug,)
            ).fetchone()
        return row["block_id"] if row else None

    def set_position(self, slug: str, block_id: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO reading_state (slug, block_id, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT (slug) DO UPDATE SET block_id = excluded.block_id, "
                "updated_at = excluded.updated_at",
                (slug, block_id, _now()),
            )

    # ─── 북마크 ─────────────────────────────────────────

    def list_bookmarks(self, slug: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT block_id, created_at FROM bookmarks WHERE slug = ? ORDER BY id",
                (slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    def toggle_bookmark(self, slug: str, block_id: str) -> bool:
        """켜면 True, 끄면 False."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM bookmarks WHERE slug = ? AND block_id = ?", (slug, block_id)
            )
            if cur.rowcount:
                return False
            conn.execute(
                "INSERT INTO bookmarks (slug, block_id, created_at) VALUES (?, ?, ?)",
                (slug, block_id, _now()),
            )
            return True

    # ─── 하이라이트 ─────────────────────────────────────

    def list_highlights(self, slug: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, block_id, lang, start, end, text, note, created_at "
                "FROM highlights WHERE slug = ? ORDER BY id",
                (slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_highlight(
        self, slug: str, block_id: str, lang: str, start: int, end: int,
        text: str, note: str | None,
    ) -> int:
        """lang 을 함께 받는 이유: 하이라이트는 글자 오프셋으로 잡는데, 원문과 번역문은
        글자 수가 다르다. 원문에서 그은 하이라이트를 번역문에 그대로 옮길 방법이 없다.
        그래서 하이라이트는 그은 언어에 매이고, 그 언어를 볼 때만 나타난다."""
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO highlights (slug, block_id, lang, start, end, text, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (slug, block_id, lang, start, end, text, note, _now()),
            )
            return int(cur.lastrowid)

    def update_note(self, slug: str, highlight_id: int, note: str | None) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE highlights SET note = ? WHERE id = ? AND slug = ?",
                (note, highlight_id, slug),
            )
            return cur.rowcount > 0

    def delete_highlight(self, slug: str, highlight_id: int) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM highlights WHERE id = ? AND slug = ?", (highlight_id, slug)
            )
            return cur.rowcount > 0
