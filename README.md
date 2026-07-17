# 논문 리더

다운받은 논문 PDF를 **책처럼** 읽는 로컬 프로그램.

세분화된 목차, 화면에 맞춘 페이지 넘김, 영어 논문 번역 토글, Kindle 스타일 UI.
서버에 올리지 않고 각자 자기 컴퓨터에서 실행한다.

> 개발 중 (Phase 0 — 뼈대). 아직 동작하지 않는다.

## 어떻게 동작하나

```
[PDF]  →  전처리 (1회)  →  [중간 JSON]  →  뷰어 (localhost)
          Docling 파싱                     페이지네이션 · 목차
          DeepL 번역                       번역 토글 · 각주 · KaTeX
          메타데이터
```

무거운 처리(파싱·번역)는 전처리에서 **한 번만** 한다. 뷰어는 가공된 JSON만 읽어서
가볍게 표시한다. 논문을 한 번 넣으면 다음부턴 즉시 열린다.

전처리와 뷰어를 잇는 계약이 [중간 JSON 스키마](schema/SCHEMA.md)다. 양쪽 다 여기에 맞춰
독립적으로 개발한다.

## 설치

Python 3.12 필요.

```bash
git clone <이 저장소>
cd paper-reader

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
```

번역 기능을 쓰려면 DeepL API Free 키가 필요하다 (월 50만 자 무료).
[DeepL API](https://www.deepl.com/pro-api) 에서 발급받은 뒤:

```bash
cp .env.example .env
# .env 를 열어 DEEPL_API_KEY 를 채운다
```

키가 없어도 파싱과 읽기는 동작한다. 번역 토글만 비활성화된다.

## 사용법

> Phase 1·2에서 구현 예정.

```bash
python -m pipeline paper.pdf     # 전처리 → data/paper/paper.json
python -m viewer                 # http://localhost:5000
```

## 폴더 구조

| 폴더 | 역할 |
|------|------|
| `schema/` | 중간 JSON 스키마 — 전처리와 뷰어의 계약 |
| `pipeline/` | 전처리: Docling 파싱 → 번역 → JSON 생성 |
| `viewer/` | Flask 로컬 웹앱 (Kindle 스타일 뷰어) |
| `data/` | 처리 결과 (git에 올리지 않음) |

## 기술 스택

| 레이어 | 선택 |
|--------|------|
| PDF 파싱 | [Docling](https://github.com/DS4SD/docling) — 2단 컬럼·표·읽기순서 자동 정리 |
| 번역 | [DeepL API Free](https://www.deepl.com/pro-api) — 교체 가능하게 추상화 |
| 웹 서버 | Flask (로컬 전용) |
| 저장 | SQLite — 읽기 상태·북마크·하이라이트 |
| 수식 | KaTeX (CDN) |
| 메타데이터 | arXiv / CrossRef API |

## 개발 현황

- [x] **Phase 0** — 프로젝트 뼈대, JSON 스키마 확정
- [ ] **Phase 1** — 전처리 파이프라인 (Docling · 번역 · 참고문헌 · 메타데이터)
- [ ] **Phase 2** — 뷰어 골격 (목차 · KaTeX · 페이지네이션 엔진)
- [ ] **Phase 3** — Kindle 읽기 경험 (페이지 넘김 · 번역 토글 · 각주 · 하이라이트)
- [ ] **Phase 4** — 라이브러리 · 검색 · 데모

자세한 계획은 [paper_reader_plan.md](paper_reader_plan.md) 참고.
