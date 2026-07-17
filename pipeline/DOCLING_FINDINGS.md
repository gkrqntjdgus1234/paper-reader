# Docling 실측 결과 (Phase 1 착수 전 확인)

논문 2편으로 Docling 2.113.0 을 실제로 돌려서 확인한 내용. **추측이 아니라 실측이다.**
Phase 1 에서 변환 코드를 짤 때 여기 적힌 함정들을 그대로 만나게 된다.

테스트 논문:
- `batteries-11-00096-v2.pdf` — MDPI, 33쪽, **수식 31개** (수식 경로 검증용)
- `FireMan-UAV-RGBT...pdf` — IEEE, 8쪽, **표 위주** (표 경로 검증용)

## 요약

| 스키마 필드 | 실측 결과 |
|---|---|
| `table_html_original` | ✅ 그대로 나옴. 캡션 포함 HTML |
| `equation.latex` | ✅ **단, 옵션을 켜야 함** (아래 1번) |
| `equation.number` | ⚠️ LaTeX 안에 섞여 나옴 → 분리 필요 (2번) |
| `figure.caption_original` | ❌ 연결 안 됨 → 직접 붙여야 함 (3번) |
| `toc` 중첩 | ❌ 전부 level=1 → 번호로 복원해야 함 (4번) |
| `references` | 미확인 (Phase 1에서 확인) |

## 1. 수식은 `do_formula_enrichment=True` 를 켜야 나온다 ★

기본값은 꺼져 있다. 끈 채로 돌리면 `FormulaItem` 이 검출은 되는데 **`text` 가 전부 빈
문자열**이다 (53개 중 53개). 수식이 있는 줄 모르고 지나가기 쉬우니 주의.

```python
opts = PdfPipelineOptions()
opts.do_formula_enrichment = True   # 이거 없으면 수식 전멸
doc = DocumentConverter(
    format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
).convert(pdf).document
```

켜면 제대로 된 LaTeX 가 나온다:

```
\frac { d x _ { \text {SEId} } } { d t } = - A _ { \text {SEId} } x _ { \text {SEId} } ^ { 0 . 5 } \exp \left ( - \frac { E _ { \text {SEId} } } { R T } \right ) \quad ( 1 )
```

토큰 사이에 공백이 많지만 KaTeX 는 무시하므로 그대로 써도 된다.

**대가:** VLM 모델이 추가로 돌아 느려진다. 논문 넣을 때 1회만 도는 전처리이므로 감수한다.

## 2. 수식 번호가 LaTeX 안에 섞여 나온다

위 예시 끝의 `\quad ( 1 )` 이 그것이다. 스키마는 `latex` 와 `number` 를 분리해 두었으므로,
변환 시 꼬리의 `\quad ( n )` 을 떼어 `number` 로 옮겨야 한다. 안 그러면 수식 옆에 번호가
수식의 일부처럼 렌더된다.

## 3. LaTeX 가 깨져 나오는 경우가 있다 → 뷰어에서 방어할 것

실측에서 발견한 실제 오류:

```
정상:  m _ { \text {an} } h _ { S E I r }
오류:  m _ { \an } h _ { S E I r }        ← \an 은 존재하지 않는 LaTeX 명령
```

VLM 모델이 `\text{an}` 을 `\an` 으로 잘못 뱉었다. 5개 중 1개에서 발생했으니 드물지 않다.
KaTeX 에 이걸 그냥 넘기면 예외가 난다.

**대응:** 뷰어에서 KaTeX 를 `throwOnError: false` 로 설정한다. 깨진 수식은 빨간 글씨로
표시되고 나머지 페이지는 정상 렌더된다. 논문 하나 때문에 뷰어 전체가 죽으면 안 된다.

## 4. 마크다운 export 로는 수식을 못 가져온다

`doc.export_to_markdown()` 결과에서 수식 자리는 `$$\n\n$$` 로 **비어 있다**.
편해 보인다고 마크다운을 거쳐 가면 안 된다. 반드시 `doc.iterate_items()` 로 아이템을
직접 순회해서 `FormulaItem.text` 를 읽어야 한다.

## 5. 그림 캡션이 연결되지 않는다

그림 30개 전부 `caption_text()` 가 `''` 이고 `captions` 필드가 빈 배열이다.
캡션 텍스트 자체는 본문에 별도 TextItem 으로 살아 있는 것으로 보인다.

**대응:** `Figure N.` / `Fig. N.` 패턴의 텍스트를 찾아 위치상 가장 가까운 그림에
붙이는 로직을 직접 짜야 한다. Phase 1 작업 항목이 하나 늘어난다.

## 6. 섹션 계층이 전부 level=1 이다

`SectionHeaderItem.level` 이 전부 1 이라 목차가 평평하다. 그대로 쓰면 "세분화 목차" 가 안 된다.

다행히 제목에 번호가 남아 있어 복원할 수 있다:

```
1. Introduction              → level 1
1.1. Motivation              → level 2
2.1.1. Thermal Runaway ...   → level 3
```

앞머리 번호의 점 개수를 세면 된다. 다만 번호 없는 소제목이 섞여 있다:

```
A1-SEI Decomposition
C2-Electrolyte Reactions
Temperature Rise
```

이런 건 직전에 나온 번호 있는 섹션의 하위로 넣는 규칙이 필요하다.

## 7. OCR 은 꺼도 된다

두 논문 다 텍스트 레이어가 있다 (pypdf 로 각각 45k자, 98k자 추출됨). Docling 은 기본적으로
OCR 모델(RapidOCR)을 받아서 돌리는데 불필요하다. `opts.do_ocr = False` 로 끄면 빨라진다.

스캔본 논문을 지원할 거라면 나중에 "텍스트 레이어 없으면 OCR 켜기" 로 자동 판단하게 한다.

## 8. 환경 함정 — 한국어 Windows

**이 프로젝트는 한글 번역이 목적이라 사용자 대부분이 한국어 Windows 다. 예외가 아니라 기본이다.**

### cp949 로 인한 torch 크래시 ★

수식 enrichment 를 켜면 torch 가 `torch.compile` 단계에서 자기 내부 템플릿 파일을 읽는데,
시스템 기본 인코딩(cp949)으로 읽으려다 UTF-8 문자에서 터진다:

```
UnicodeDecodeError: 'cp949' codec can't decode byte 0xe2
  torch/_inductor/utils.py: load_template → f.read()
```

우리 코드 문제가 아니라 torch 의 Windows 로케일 버그다. **`PYTHONUTF8=1` 로 해결된다.**
`PYTHONIOENCODING` 은 표준출력에만 적용되므로 이걸로는 안 고쳐진다.

파이프라인 진입점에서 UTF-8 모드를 보장하거나, README 실행법에 명시할 것.

### Smart App Control

이 PC 는 Smart App Control 이 enforce 상태다 (`VerifiedAndReputablePolicyState: 1`).
갓 설치한 패키지의 첫 import 가 한 번 차단될 수 있다:

```
ImportError: DLL load failed while importing indexing:
애플리케이션 제어 정책에서 이 파일을 차단했습니다.
```

pandas 에서 실제로 겪었고, 잠시 후 재시도하니 통과했다. 평판 확인이 끝나면 풀린다.
설치가 깨진 게 아니므로 재시도하면 된다 — README 에 적어두면 헛짚는 시간을 아낀다.
