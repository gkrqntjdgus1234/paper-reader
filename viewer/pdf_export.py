"""인쇄용 HTML → PDF.

이미 있는 Chrome 을 headless 로 돌려 우리 인쇄 페이지를 PDF 로 뽑는다. 별도 PDF
라이브러리(weasyprint 등)를 쓰지 않는 이유: 그런 라이브러리는 KaTeX 수식·복잡한
표를 브라우저만큼 정확히 그리지 못한다. Chrome 은 화면에서 보던 것을 그대로 낸다.

Chrome 이 없으면 None 을 돌려주고, 뷰어가 EPUB 을 권한다.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 흔한 설치 위치들. 순서대로 찾는다.
_CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str | None:
    for p in _CHROME_PATHS:
        if Path(p).exists():
            return p
    return None


def html_url_to_pdf(url: str, out: Path, chrome: str | None = None) -> bool:
    """headless 브라우저로 url 을 열어 PDF 로 저장한다. 성공하면 True.

    --print-to-pdf 는 페이지의 window.__ready 를 기다려주지 않으므로, 수식·이미지가
    그려질 시간을 벌기 위해 --virtual-time-budget 을 준다.
    """
    chrome = chrome or find_chrome()
    if not chrome:
        logger.warning("Chrome/Edge 를 찾지 못했다 — PDF 를 만들 수 없다")
        return False

    out.parent.mkdir(parents=True, exist_ok=True)
    # 임시 프로필을 쓴다. 사용자의 실제 Chrome 세션을 건드리지 않는다.
    profile = out.parent / ".chrome-profile"

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        f"--user-data-dir={profile}",
        "--virtual-time-budget=15000",   # 수식·이미지 렌더를 기다린다
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={out}",
        "--print-to-pdf-no-header",
        url,
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=120, text=True)
    except subprocess.TimeoutExpired:
        logger.error("PDF 생성이 시간을 초과했다")
        return False
    except Exception as exc:
        logger.error("PDF 생성 실패: %s", exc)
        return False

    # headless Chrome 은 성공해도 stderr 에 로그를 쏟으므로 종료코드로 판단한다
    if out.exists() and out.stat().st_size > 1000:
        return True
    logger.error("PDF 가 생성되지 않았다: %s", (proc.stderr or "")[-300:])
    return False
