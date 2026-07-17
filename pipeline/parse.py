"""PDF → DoclingDocument.

Docling 관련 함정은 DOCLING_FINDINGS.md 참고. 여기서 대응하는 것:
  - do_formula_enrichment 를 켜야 수식이 나온다 (기본값 꺼짐 → 수식 전멸)
  - 텍스트 레이어가 있으면 OCR 은 불필요 (느리기만 함)
  - 변환이 느리므로 결과를 캐싱한다
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)

# 텍스트 레이어가 이 정도는 나와야 "PDF에 텍스트가 심겨 있다"고 본다.
# 실측: FireMan 45k자 / Batteries 98k자. 스캔본은 0에 가깝다.
_TEXT_LAYER_MIN_CHARS = 3000


def has_text_layer(pdf: Path) -> bool:
    """PDF에 추출 가능한 텍스트가 있는가? 없으면 스캔본이므로 OCR이 필요하다."""
    try:
        from pypdf import PdfReader
    except ImportError:
        logger.warning("pypdf 없음 — 텍스트 레이어를 확인할 수 없어 OCR을 켠다")
        return False

    try:
        reader = PdfReader(str(pdf))
        chars = 0
        for page in reader.pages[:5]:  # 앞 5쪽만 봐도 충분하다
            chars += len(page.extract_text() or "")
            if chars >= _TEXT_LAYER_MIN_CHARS:
                return True
        return chars >= _TEXT_LAYER_MIN_CHARS
    except Exception as exc:
        logger.warning("텍스트 레이어 확인 실패 (%s) — OCR을 켠다", exc)
        return False


def parse_pdf(
    pdf: Path,
    cache_dir: Path | None = None,
    force: bool = False,
    pages: tuple[int, int] | None = None,
):
    """PDF를 DoclingDocument 로 변환한다. cache_dir 를 주면 결과를 캐싱한다.

    pages 로 페이지 범위를 좁힐 수 있다. 수식이 많은 논문은 수식 모델이 페이지마다
    돌아 아주 느리므로, 확인만 하려면 일부만 돌리는 게 낫다.

    첫 변환은 모델 다운로드까지 겹쳐 수 분 걸린다. 이후는 캐시에서 즉시 로드된다.
    """
    cache_file = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        # 페이지 범위가 다르면 결과도 다르다. 캐시 이름에 범위를 넣어 섞이지 않게 한다.
        suffix = f".p{pages[0]}-{pages[1]}" if pages else ""
        cache_file = cache_dir / f"{pdf.stem}{suffix}.docling.pkl"
        if cache_file.exists() and not force:
            logger.info("캐시된 파싱 결과 사용: %s", cache_file.name)
            return pickle.loads(cache_file.read_bytes())

    # import 가 무겁고(torch) 모델을 받으므로 필요할 때만 끌어온다
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    ocr = not has_text_layer(pdf)

    opts = PdfPipelineOptions()
    opts.do_formula_enrichment = True   # ★ 이거 없으면 FormulaItem.text 가 전부 빈 문자열
    opts.do_table_structure = True
    opts.do_ocr = ocr
    opts.generate_picture_images = True  # 그림을 이미지로 뽑으려면 필요
    opts.images_scale = 2.0              # 기본 1.0 은 저해상도라 읽기 힘들다

    logger.info(
        "Docling 변환 시작: %s (OCR=%s, 수식인식=ON%s) — 처음이면 수 분 걸린다",
        pdf.name, "ON" if ocr else "OFF",
        f", {pages[0]}~{pages[1]}쪽만" if pages else "",
    )

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    kwargs = {"page_range": pages} if pages else {}
    doc = converter.convert(str(pdf), **kwargs).document

    if cache_file:
        cache_file.write_bytes(pickle.dumps(doc))
        logger.info("파싱 결과 캐시 저장: %s", cache_file.name)

    return doc
