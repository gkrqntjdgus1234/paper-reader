"""번역 계층.

계획서대로 번역기는 함수 뒤에 숨긴다. DeepL 이 마음에 안 들면 Translator 만 갈아끼운다.

핵심은 <c>/<m> 태그 보존이다 (SCHEMA.md 2번). DeepL 에 LaTeX 를 그냥 던지면 깨지므로
XML 태그 처리 기능으로 보호한다:

    tag_handling="xml", ignore_tags=["c", "m"]

이러면 DeepL 이 태그 안은 건드리지 않고 어순에 맞게 위치만 옮긴다.

번역은 한도를 먹는다. 그래서:
  - 같은 문장은 한 번만 번역하고 캐시에 남긴다
  - 캐시는 논문 폴더가 아니라 공용이다 — 논문 간 중복 문장도 아낀다

한도는 계정마다 다르므로 상수로 박지 않고 DeepL 에 물어본다 (usage()).
실측: 이 계정은 100만 자였다 (문서에 흔히 적힌 50만이 아니다).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Protocol

from pipeline.inline import strip_tags, tags_in

logger = logging.getLogger(__name__)


class Translator(Protocol):
    """번역기 인터페이스. 이것만 만족하면 DeepL 이 아니어도 된다."""

    def translate(self, texts: list[str]) -> list[str]:
        ...


class DeepLTranslator:
    def __init__(self, api_key: str, target_lang: str = "KO", source_lang: str = "EN") -> None:
        import deepl

        self._client = deepl.Translator(api_key)
        self._target = target_lang
        self._source = source_lang

    def translate(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        results = self._client.translate_text(
            texts,
            source_lang=self._source,
            target_lang=self._target,
            tag_handling="xml",      # ← <c>/<m> 태그를 태그로 인식시킨다
            ignore_tags=["c", "m"],  # ← 그 안은 번역하지 않는다
        )
        return [r.text for r in results]

    def usage(self) -> tuple[int, int] | None:
        """(사용한 글자 수, 한도). 조회 실패 시 None."""
        try:
            u = self._client.get_usage()
            if u.character is not None:
                return u.character.count, u.character.limit
        except Exception as exc:
            logger.debug("사용량 조회 실패: %s", exc)
        return None


class NullTranslator:
    """번역기가 없을 때. 원문을 그대로 돌려준다.

    키가 없다고 파이프라인이 죽으면 안 된다 — 번역 없이 원문만 읽는 것도
    유효한 사용법이고, 스키마도 번역 필드를 nullable 로 두었다.
    """

    def translate(self, texts: list[str]) -> list[str]:
        return list(texts)


class TranslationCache:
    """번역 결과를 디스크에 남긴다. 같은 문장을 두 번 번역하지 않기 위해서."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, str] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("번역 캐시를 읽지 못했다 (%s) — 새로 시작한다", exc)

    @staticmethod
    def _key(text: str, target: str) -> str:
        return hashlib.sha256(f"{target}\x00{text}".encode()).hexdigest()[:32]

    def get(self, text: str, target: str) -> str | None:
        return self._data.get(self._key(text, target))

    def put(self, text: str, target: str, translated: str) -> None:
        self._data[self._key(text, target)] = translated

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, ensure_ascii=False), encoding="utf-8"
        )
        logger.debug("번역 캐시 저장: %d개", len(self._data))


def make_translator(target_lang: str = "KO") -> Translator:
    """.env 의 키를 보고 번역기를 만든다. 키가 없으면 NullTranslator."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    key = os.environ.get("DEEPL_API_KEY", "").strip()
    if not key or key.startswith("your-key"):
        logger.warning("DEEPL_API_KEY 가 없다 — 번역 없이 원문만 만든다")
        return NullTranslator()

    try:
        translator = DeepLTranslator(key, target_lang=target_lang)
    except Exception as exc:
        logger.error("DeepL 초기화 실패 (%s) — 번역 없이 진행한다", exc)
        return NullTranslator()

    usage = translator.usage()
    if usage:
        used, limit = usage
        logger.info(
            "DeepL 사용량: %s / %s 자 (%.1f%%)", f"{used:,}", f"{limit:,}", 100 * used / limit
        )
    return translator


def _verify_tags(original: str, translated: str) -> bool:
    """번역문이 원문의 태그를 그대로 보존했는가?

    SCHEMA.md 2번의 규칙: 위치는 어순 따라 바뀌어도 되지만 개수와 id 는 같아야 한다.
    어긋나면 인용 각주나 수식이 사라진다는 뜻이므로 번역을 버리고 원문을 쓴다.
    """
    return sorted(tags_in(original)) == sorted(tags_in(translated))


def translate_paper(
    paper: dict,
    translator: Translator,
    cache: TranslationCache,
    target_lang: str = "ko",
) -> dict:
    """중간 JSON 의 번역 필드를 채운다. paper 를 제자리에서 수정한다."""
    if isinstance(translator, NullTranslator):
        return paper

    # (텍스트, 되돌려 놓을 자리) 목록을 모은다
    jobs: list[tuple[str, dict, str]] = []       # (원문, 블록, 필드명)
    list_jobs: list[tuple[str, dict, int]] = []  # (원문, 블록, 항목 인덱스)

    for block in paper["blocks"]:
        t = block["type"]
        if t in ("paragraph", "heading"):
            jobs.append((block["text_original"], block, "text_translated"))
        elif t in ("figure", "table"):
            if block["caption_original"]:
                jobs.append((block["caption_original"], block, "caption_translated"))
        elif t == "list":
            for idx, item in enumerate(block["items_original"]):
                list_jobs.append((item, block, idx))
        # equation 은 번역 대상이 아니다

    for node in _walk_toc(paper["toc"]):
        jobs.append((node["title"], node, "title_translated"))

    texts = [j[0] for j in jobs] + [j[0] for j in list_jobs]
    unique = list(dict.fromkeys(texts))

    todo = [t for t in unique if cache.get(t, target_lang) is None]
    chars = sum(len(strip_tags(t)) for t in todo)
    logger.info(
        "번역 대상 %d개 (캐시 적중 %d개, 새로 번역 %d개, 약 %s자)",
        len(unique), len(unique) - len(todo), len(todo), f"{chars:,}",
    )

    if todo:
        # DeepL 은 요청당 여러 문장을 받는다. 너무 크면 거절하므로 나눠 보낸다.
        batch: list[str] = []
        batch_chars = 0
        for text in todo:
            if batch and batch_chars + len(text) > 30_000:
                _translate_batch(batch, translator, cache, target_lang)
                batch, batch_chars = [], 0
            batch.append(text)
            batch_chars += len(text)
        if batch:
            _translate_batch(batch, translator, cache, target_lang)
        cache.save()

    dropped = 0
    for original, holder, field in jobs:
        result = cache.get(original, target_lang)
        if result is None:
            continue
        if not _verify_tags(original, result):
            dropped += 1
            continue
        holder[field] = result

    for original, block, idx in list_jobs:
        result = cache.get(original, target_lang)
        if result is None or not _verify_tags(original, result):
            if result is not None:
                dropped += 1
            continue
        if block["items_translated"] is None:
            block["items_translated"] = list(block["items_original"])
        block["items_translated"][idx] = result

    if dropped:
        logger.warning(
            "태그가 어긋나 버린 번역 %d개 — 해당 부분은 원문으로 표시된다", dropped
        )

    paper["meta"]["translated_lang"] = target_lang
    return paper


def _translate_batch(
    batch: list[str], translator: Translator, cache: TranslationCache, target_lang: str
) -> None:
    try:
        results = translator.translate(batch)
    except Exception as exc:
        logger.error("번역 실패 (%s) — 이 묶음은 원문으로 남는다", exc)
        return
    for src, dst in zip(batch, results):
        cache.put(src, target_lang, dst)
    logger.info("  %d개 번역 완료", len(batch))


def _walk_toc(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk_toc(node["children"])
