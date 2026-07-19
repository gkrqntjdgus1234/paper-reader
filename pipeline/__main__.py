"""python -m pipeline <PDF> — 논문 하나를 중간 JSON 으로 만든다."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path


def _ensure_utf8_mode() -> None:
    """UTF-8 모드가 아니면 켜서 자기 자신을 다시 실행한다.

    한국어 Windows(cp949)에서 torch 가 수식 모델을 준비하다 자기 내부 템플릿 파일을
    기본 인코딩으로 읽고 터진다 (DOCLING_FINDINGS.md 8번):

        UnicodeDecodeError: 'cp949' codec can't decode byte 0xe2
          torch/_inductor/utils.py: load_template → f.read()

    PYTHONUTF8 은 인터프리터 시작 전에 정해져야 해서 나중에 os.environ 으로 바꿔봐야
    소용없다. 그래서 환경변수를 세팅하고 다시 띄운다. 이 프로젝트는 한글 번역이
    목적이라 사용자 대부분이 한국어 Windows 다 — 예외가 아니라 기본 경로다.

    os.execve 가 아니라 subprocess 를 쓰는 이유: Windows 에는 exec 가 없어서 파이썬이
    "새 프로세스를 띄우고 부모는 즉시 종료" 로 흉내 낸다. 그러면 호출한 쉘은 부모의
    종료(코드 0)만 보고 끝난 줄 알고, 정작 일하는 자식은 분리되어 출력도 사라진다.
    """
    if sys.flags.utf8_mode or os.environ.get("PAPER_READER_REEXEC"):
        return

    import subprocess

    env = dict(os.environ, PYTHONUTF8="1", PAPER_READER_REEXEC="1")
    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pipeline", *sys.argv[1:]],
        env=env,
        cwd=Path(__file__).resolve().parent.parent,
    )
    sys.exit(result.returncode)


_ensure_utf8_mode()

from pipeline.convert import convert          # noqa: E402  (UTF-8 모드 확정 후 import)
from pipeline.lang import detect_paper        # noqa: E402
from pipeline.metadata import enrich          # noqa: E402
from pipeline.parse import parse_pdf          # noqa: E402
from pipeline.translate import (              # noqa: E402
    TranslationCache,
    make_translator,
    translate_paper,
)
from pipeline.validate import validate_paper  # noqa: E402

logger = logging.getLogger("pipeline")


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="논문 PDF 를 뷰어가 읽을 중간 JSON 으로 변환한다.",
    )
    ap.add_argument("pdf", type=Path, help="논문 PDF 경로")
    ap.add_argument("-o", "--out", type=Path, default=Path("data"),
                    help="결과를 넣을 폴더 (기본: data/)")
    ap.add_argument("--force", action="store_true", help="캐시를 무시하고 다시 파싱")
    ap.add_argument("--pages", metavar="A-B",
                    help="이 페이지 범위만 처리한다 (예: 5-10). 수식이 많은 논문을 "
                         "빠르게 확인할 때 쓴다")
    ap.add_argument("--no-translate", action="store_true",
                    help="번역을 건너뛴다 (원문만)")
    ap.add_argument("--offline", action="store_true",
                    help="네트워크를 쓰지 않는다 (CrossRef 조회 생략)")
    ap.add_argument("--lang", default=os.environ.get("DEEPL_TARGET_LANG", "KO"),
                    help="번역 언어 (기본: KO)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s  %(message)s",
    )

    if not args.pdf.exists():
        logger.error("PDF 를 찾을 수 없다: %s", args.pdf)
        return 1

    pages = None
    if args.pages:
        try:
            a, b = (int(x) for x in args.pages.split("-", 1))
            pages = (a, b)
        except ValueError:
            logger.error("--pages 는 5-10 형태여야 한다: %r", args.pages)
            return 1

    # 부분 처리 결과가 전체 논문을 덮어쓰면 안 된다 — 다른 폴더에 넣는다
    name = args.pdf.stem + (f" (p{pages[0]}-{pages[1]})" if pages else "")
    paper_dir = args.out / name
    paper_dir.mkdir(parents=True, exist_ok=True)

    doc = parse_pdf(args.pdf, cache_dir=paper_dir / ".cache", force=args.force, pages=pages)

    logger.info("중간 JSON 으로 변환 중...")
    paper = convert(doc, source_pdf=args.pdf.name, figures_dir=paper_dir / "figures")

    paper["meta"] = enrich(paper["meta"], args.pdf, offline=args.offline)

    # 원문이 무슨 언어인지 본문을 보고 정한다. 이게 없으면 한국어 논문을 영어라고
    # 우기며 DeepL 에 보내게 된다 (한도만 쓰고 결과는 쓸모없다).
    paper["meta"]["lang"] = detect_paper(paper)
    logger.info("원문 언어: %s", paper["meta"]["lang"])

    if not args.no_translate:
        translator = make_translator(
            target_lang=args.lang, source_lang=paper["meta"]["lang"].upper()
        )
        cache = TranslationCache(args.out / ".translation-cache.json")
        paper = translate_paper(paper, translator, cache, target_lang=args.lang.lower())

    errors = validate_paper(paper)
    if errors:
        logger.error("스키마 검증 실패 — %d건", len(errors))
        for err in errors[:5]:
            logger.error("  %s", err)
        return 1

    out_file = paper_dir / "paper.json"
    out_file.write_text(
        json.dumps(paper, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    kinds: dict[str, int] = {}
    for block in paper["blocks"]:
        kinds[block["type"]] = kinds.get(block["type"], 0) + 1

    logger.info("완료: %s", out_file)
    logger.info("  블록 %d개 %s", len(paper["blocks"]), kinds)
    logger.info("  목차 %d개 (최상위)", len(paper["toc"]))
    logger.info("  참고문헌 %d개", len(paper["references"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
