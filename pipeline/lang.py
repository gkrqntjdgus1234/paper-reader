"""원문이 무슨 언어인지 알아낸다.

이게 없으면 한국어 논문을 영어라고 우기며 DeepL 에 보낸다. 한도만 쓰고 결과는
쓸모없어진다. 이미 읽을 수 있는 언어면 번역할 이유가 없다.

별도 라이브러리를 쓰지 않는다. 우리에게 필요한 건 "한국어인가 아닌가" 수준이고,
글자 種類만 세도 충분히 갈린다.
"""

from __future__ import annotations

import re

# 글자 범위는 코드포인트로 적는다. 글자를 그대로 넣으면 편집기·인코딩을 거치며
# 조용히 망가진다 (실측: 가나 범위가 깨져 일본어를 영어로 판정했다).
_HANGUL = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")  # 완성형 + 자모
_KANA = re.compile(r"[぀-ゟ゠-ヿ]")  # 히라가나 + 가타카나
# 한자는 세지 않는다. 한국어 논문에도 섞여 나오므로 판단 근거가 못 된다.
_LATIN = re.compile(r"[A-Za-z]")

# 이 비율을 넘으면 그 언어로 본다. 한국어 논문도 전문 용어·인용은 영어라
# 낮게 잡아야 한다. 반대로 영어 논문에 한글이 섞이는 일은 거의 없다.
_THRESHOLD = 0.10


def detect(text: str) -> str:
    """'ko' | 'ja' | 'en'. 애매하면 'en' 으로 둔다 (논문 대다수가 영어다)."""
    sample = text[:20000]  # 앞부분만 봐도 충분하다

    hangul = len(_HANGUL.findall(sample))
    kana = len(_KANA.findall(sample))
    latin = len(_LATIN.findall(sample))

    total = hangul + kana + latin
    # 글자가 너무 적으면 판단하지 않는다 ("Fig. 1" 같은 조각으로 정하면 안 된다).
    # 다만 기준을 높이 잡으면 짧은 한국어 초록이 영어로 넘어간다 — 한자를 세지
    # 않으므로 동아시아 언어는 글자 수가 빨리 줄어든다.
    if total < 20:
        return "en"

    if hangul / total >= _THRESHOLD:
        return "ko"
    if kana / total >= _THRESHOLD:
        return "ja"
    return "en"


def detect_paper(paper: dict) -> str:
    """중간 JSON 에서 원문 언어를 알아낸다."""
    from pipeline.inline import strip_tags

    parts: list[str] = []
    for block in paper.get("blocks", []):
        text = block.get("text_original")
        if text:
            parts.append(strip_tags(text))
        for item in block.get("items_original") or []:
            parts.append(strip_tags(item))
        if len(" ".join(parts)) > 20000:
            break

    return detect(" ".join(parts))
