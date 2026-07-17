"""python -m viewer — 로컬 뷰어를 띄운다."""

from __future__ import annotations

import argparse
import logging
import webbrowser
from pathlib import Path

from viewer.app import DATA_DIR, create_app


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="python -m viewer", description="논문 리더 뷰어를 localhost 에 띄운다."
    )
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--data", type=Path, default=DATA_DIR, help="논문 폴더 (기본: data/)")
    ap.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않는다")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    app = create_app(args.data)
    url = f"http://127.0.0.1:{args.port}"
    print(f"\n  논문 리더 → {url}\n  (끄려면 Ctrl+C)\n")

    if not args.no_browser:
        webbrowser.open(url)

    # 로컬 전용이므로 127.0.0.1 에만 묶는다. 0.0.0.0 으로 열면 같은 공유기의
    # 다른 기기에서도 논문이 보인다 — 의도한 바가 아니다.
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
