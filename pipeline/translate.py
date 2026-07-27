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

    def translate_html(self, htmls: list[str]) -> list[str]:
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

    def translate_html(self, htmls: list[str]) -> list[str]:
        """표처럼 HTML 구조가 있는 것을 번역한다.

        tag_handling='html' 을 쓰면 <table><tr><td> 같은 구조는 그대로 두고
        셀 안의 글자만 번역한다. 일반 텍스트와 태그 처리 방식이 달라 메서드를 나눴다.
        """
        if not htmls:
            return []
        results = self._client.translate_text(
            htmls,
            source_lang=self._source,
            target_lang=self._target,
            tag_handling="html",
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

    def translate_html(self, htmls: list[str]) -> list[str]:
        return list(htmls)


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


def make_translator(target_lang: str = "KO", source_lang: str = "EN") -> Translator:
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
        translator = DeepLTranslator(key, target_lang=target_lang, source_lang=source_lang)
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

    # 이미 읽을 수 있는 언어면 번역하지 않는다. 한국어 논문을 영어라고 우기며
    # DeepL 에 보내면 한도만 쓰고 결과는 쓸모없어진다.
    source_lang = (paper["meta"].get("lang") or "en").lower()
    if source_lang == target_lang.lower():
        logger.info("원문이 이미 %s 다 — 번역하지 않는다", source_lang)
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

    _translate_tables(paper, translator, cache, target_lang)

    paper["meta"]["translated_lang"] = target_lang
    return paper


def _translate_tables(
    paper: dict, translator: Translator, cache: TranslationCache, target_lang: str
) -> None:
    """표 안의 글자를 번역한다.

    표는 HTML 구조가 있어 일반 텍스트와 다른 방식(tag_handling='html')으로 번역한다.
    보통 논문에서 표는 숫자 위주라 후순위였는데, 목차를 표로 그린 문서가 있어서
    (실측: EEMUA 규격 문서) 필요해졌다.

    캐시 키가 섞이지 않게 앞에 표식을 붙인다 — 같은 문장이라도 xml 로 번역한 것과
    html 로 번역한 결과가 다를 수 있다.
    """
    tables = [b for b in paper["blocks"] if b["type"] == "table" and b["table_html_original"]]
    if not tables:
        return

    def key(html: str) -> str:
        return "\x01html\x01" + html

    todo = [t["table_html_original"] for t in tables
            if cache.get(key(t["table_html_original"]), target_lang) is None]
    if todo:
        logger.info("표 %d개 번역 중…", len(todo))
        for html in dict.fromkeys(todo):
            try:
                out = translator.translate_html([html])[0]
                cache.put(key(html), target_lang, out)
            except Exception as exc:
                logger.warning("표 번역 실패 (%s) — 이 표는 원문으로 둔다", exc)
        cache.save()

    for block in tables:
        result = cache.get(key(block["table_html_original"]), target_lang)
        if result:
            block["table_html_translated"] = result


def _translate_batch(
    batch: list[str], translator: Translator, cache: TranslationCache, target_lang: str
) -> None:
    try:
        results = translator.translate(batch)
    except Exception as exc:
        # 배치 하나가 실패하면 그 안의 전부를 잃는다. 문장 하나 때문에 수백 개가
        # 날아가면 안 된다 (실측: 'A2 <= 1.20' 한 줄이 DeepL 의 xml 파서를 깨뜨려
        # 405개 배치가 통째로 실패했다 — &lt;= 는 유효한 XML 인데 DeepL 이 오판한다).
        # 반씩 쪼개 재시도해서 진짜 범인 하나만 원문으로 남긴다.
        if len(batch) == 1:
            logger.warning("번역 실패한 문장 하나는 원문으로 둔다: %r (%s)",
                           batch[0][:50], str(exc)[:50])
            return
        mid = len(batch) // 2
        _translate_batch(batch[:mid], translator, cache, target_lang)
        _translate_batch(batch[mid:], translator, cache, target_lang)
        return
    for src, dst in zip(batch, results):
        cache.put(src, target_lang, dst)


def _walk_toc(nodes: list[dict]):
    for node in nodes:
        yield node
        yield from _walk_toc(node["children"])
