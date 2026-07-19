"""로컬 뷰어 서버 (Flask).

무거운 일은 전처리가 이미 끝냈다. 서버는 중간 JSON 을 찾아서 넘겨줄 뿐이고,
페이지네이션·목차·수식 렌더링은 전부 브라우저에서 한다.

페이지 나누기가 브라우저 몫인 이유는 스키마에 페이지 개념이 없기 때문이다
(SCHEMA.md 1번). 화면 크기와 글자 크기에 따라 매번 달라져야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_from_directory

from viewer.db import Store
from viewer.jobs import JobRegistry, safe_name
from viewer.library import reading_progress, scan
from viewer.search import search_all

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def create_app(data_dir: Path = DATA_DIR) -> Flask:
    app = Flask(__name__)
    app.config["DATA_DIR"] = data_dir
    # 논문 PDF 는 보통 수 MB ~ 수십 MB 다 (실측: 2.8MB, 14.5MB)
    app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
    store = Store(data_dir / "reader.sqlite3")
    jobs = JobRegistry()

    def papers():
        # 매 요청마다 훑는다. 논문 수가 수십 개 수준이라 충분히 빠르고,
        # 새 논문을 넣었을 때 서버를 다시 띄우지 않아도 된다.
        return scan(app.config["DATA_DIR"])

    @app.route("/")
    def index():
        found = papers()
        items = sorted(found.values(), key=lambda p: p.title.lower())
        # 어디까지 읽었는지 — 페이지 번호가 아니라 블록 순서로 잰다
        progress = {
            p.slug: reading_progress(p, store.get_position(p.slug)) for p in items
        }
        counts = {
            p.slug: (len(store.list_bookmarks(p.slug)), len(store.list_highlights(p.slug)))
            for p in items
        }
        return render_template(
            "library.html", papers=items, progress=progress, counts=counts
        )

    # ─── 논문 가져오기 ──────────────────────────────────
    # 앱 안에서 PDF 를 넣는다. 전처리는 오래 걸리므로 백그라운드로 돌리고
    # 화면은 진행 상황만 물어본다.

    @app.route("/api/import", methods=["POST"])
    def api_import():
        file = request.files.get("pdf")
        if not file or not file.filename:
            return jsonify({"error": "PDF 파일을 골라 주세요."}), 400
        if not file.filename.lower().endswith(".pdf"):
            return jsonify({"error": "PDF 파일만 넣을 수 있습니다."}), 400

        input_dir = app.config["DATA_DIR"] / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        target = input_dir / safe_name(file.filename)
        file.save(target)

        translate = request.form.get("translate") != "0"
        job = jobs.start(target, translate, app.config["DATA_DIR"])
        return jsonify(job.to_dict())

    @app.route("/api/imports")
    def api_imports():
        return jsonify(jobs.list())

    @app.route("/api/imports/clear", methods=["POST"])
    def api_imports_clear():
        jobs.clear_finished()
        return jsonify({"ok": True})

    @app.route("/api/search")
    def api_search():
        query = request.args.get("q", "")
        hits = search_all(papers(), query)
        return jsonify([
            {
                "slug": h.slug,
                "paper_title": h.paper_title,
                "block_id": h.block_id,
                "lang": h.lang,
                "snippet": h.snippet,
                "section": h.section,
            }
            for h in hits
        ])

    @app.route("/read/<slug>")
    def read(slug: str):
        paper = papers().get(slug)
        if not paper:
            abort(404)
        return render_template("reader.html", paper=paper)

    @app.route("/api/paper/<slug>")
    def api_paper(slug: str):
        paper = papers().get(slug)
        if not paper:
            abort(404)
        return jsonify(json.loads(paper.json_path.read_text(encoding="utf-8")))

    @app.route("/papers/<slug>/figures/<path:filename>")
    def figure(slug: str, filename: str):
        paper = papers().get(slug)
        if not paper:
            abort(404)
        # send_from_directory 가 경로 탈출(../)을 막아준다
        return send_from_directory(paper.dir / "figures", filename)

    # ─── 읽기 상태 ──────────────────────────────────────
    # 전부 블록 id 기준이다. 페이지 번호는 글자 크기가 바뀌면 의미를 잃는다.

    def _require(slug: str):
        if slug not in papers():
            abort(404)

    @app.route("/api/state/<slug>")
    def get_state(slug: str):
        _require(slug)
        return jsonify({
            "position": store.get_position(slug),
            "bookmarks": store.list_bookmarks(slug),
            "highlights": store.list_highlights(slug),
        })

    @app.route("/api/state/<slug>/position", methods=["PUT"])
    def put_position(slug: str):
        _require(slug)
        block_id = (request.json or {}).get("block_id")
        if not block_id:
            abort(400, "block_id 가 필요하다")
        store.set_position(slug, block_id)
        return jsonify({"ok": True})

    @app.route("/api/state/<slug>/bookmark", methods=["POST"])
    def post_bookmark(slug: str):
        _require(slug)
        block_id = (request.json or {}).get("block_id")
        if not block_id:
            abort(400, "block_id 가 필요하다")
        return jsonify({"bookmarked": store.toggle_bookmark(slug, block_id)})

    @app.route("/api/state/<slug>/highlight", methods=["POST"])
    def post_highlight(slug: str):
        _require(slug)
        data = request.json or {}
        try:
            hid = store.add_highlight(
                slug,
                data["block_id"],
                data.get("lang", "original"),
                int(data["start"]),
                int(data["end"]),
                data.get("text", ""),
                data.get("note"),
            )
        except (KeyError, ValueError, TypeError):
            abort(400, "block_id, start, end 가 필요하다")
        return jsonify({"id": hid})

    @app.route("/api/state/<slug>/highlight/<int:hid>", methods=["PATCH", "DELETE"])
    def edit_highlight(slug: str, hid: int):
        _require(slug)
        if request.method == "DELETE":
            if not store.delete_highlight(slug, hid):
                abort(404)
            return jsonify({"ok": True})
        note = (request.json or {}).get("note")
        if not store.update_note(slug, hid, note):
            abort(404)
        return jsonify({"ok": True})

    return app
