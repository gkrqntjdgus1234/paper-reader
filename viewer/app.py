"""로컬 뷰어 서버 (Flask).

무거운 일은 전처리가 이미 끝냈다. 서버는 중간 JSON 을 찾아서 넘겨줄 뿐이고,
페이지네이션·목차·수식 렌더링은 전부 브라우저에서 한다.

페이지 나누기가 브라우저 몫인 이유는 스키마에 페이지 개념이 없기 때문이다
(SCHEMA.md 1번). 화면 크기와 글자 크기에 따라 매번 달라져야 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, send_from_directory

from viewer.library import scan

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def create_app(data_dir: Path = DATA_DIR) -> Flask:
    app = Flask(__name__)
    app.config["DATA_DIR"] = data_dir

    def papers():
        # 매 요청마다 훑는다. 논문 수가 수십 개 수준이라 충분히 빠르고,
        # 새 논문을 넣었을 때 서버를 다시 띄우지 않아도 된다.
        return scan(app.config["DATA_DIR"])

    @app.route("/")
    def index():
        items = sorted(papers().values(), key=lambda p: p.title.lower())
        return render_template("library.html", papers=items)

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

    return app
