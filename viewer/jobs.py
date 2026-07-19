"""논문 가져오기 작업 관리.

전처리는 몇 분에서 몇십 분까지 걸린다 (실측: 수식 많은 논문이 6쪽에 10분).
웹 요청 안에서 그대로 돌리면 브라우저가 먼저 포기한다. 그래서 백그라운드로 돌리고
화면은 진행 상황만 물어본다.

파이프라인을 함수로 부르지 않고 별도 프로세스(python -m pipeline)로 띄우는 이유:
  - Docling 이 죽어도 뷰어 서버는 살아 있다
  - CLI 가 이미 검증된 경로다 (한국어 Windows 의 UTF-8 재실행 포함)
  - torch 를 뷰어 프로세스에 끌어들이지 않는다
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_name(name: str) -> str:
    """올린 파일 이름을 안전하게 만든다.

    한글을 지우지 않는다 — 논문 파일명이 한글인 경우가 많다 (실측: 파일명이
    한글로 번역된 논문). Windows 가 싫어하는 문자와 경로 구분자만 걷어낸다.
    """
    name = Path(name).name  # ../ 같은 경로 부분 제거
    name = _BAD_NAME.sub("_", name).strip(" .")
    return name or "paper.pdf"


def _friendly(line: str) -> str | None:
    """파이프라인 로그 한 줄을 사람이 읽을 말로 바꾼다.

    Docling 이 쏟아내는 로그를 그대로 보여주면 무슨 일이 일어나는지 알 수 없다.
    의미 있는 줄만 골라 우리말로 바꾼다. 해당 없으면 None.
    """
    if "변환 시작" in line:
        return "PDF 구조를 읽는 중… 처음이면 모델을 받느라 몇 분 걸립니다"
    if "캐시된 파싱 결과" in line:
        return "이전에 읽어둔 결과를 쓰는 중…"
    if "Batch processed" in line:
        m = re.search(r"(\d+) images in ([\d.]+)s", line)
        if m:
            return f"수식·그림을 읽는 중… ({m.group(1)}개, {float(m.group(2)):.0f}초)"
        return "수식·그림을 읽는 중…"
    if "Finished converting" in line:
        return "PDF 읽기 완료. 정리하는 중…"
    if "참고문헌" in line and "개" in line:
        m = re.search(r"(\d+)개", line)
        return f"참고문헌 {m.group(1)}개를 찾았습니다" if m else None
    if "CrossRef" in line or "제목으로" in line:
        return "논문 정보(제목·저자·연도)를 조회하는 중…"
    if "번역 대상" in line:
        m = re.search(r"약 ([\d,]+)자", line)
        return f"번역하는 중… (약 {m.group(1)}자)" if m else "번역하는 중…"
    if "번역 완료" in line:
        return "번역하는 중…"
    if "완료:" in line:
        return "거의 다 됐습니다…"
    return None


@dataclass
class Job:
    id: str
    filename: str
    status: str = "running"          # running | done | error
    message: str = "준비하는 중…"     # 화면에 보여줄 현재 상태
    log: list[str] = field(default_factory=list)   # 문제 생겼을 때 볼 원본
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def elapsed(self) -> int:
        return int((self.finished_at or time.time()) - self.started_at)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "message": self.message,
            "elapsed": self.elapsed,
            "log": self.log[-40:],
        }


class JobRegistry:
    """돌고 있는 가져오기 작업들. 로컬 단일 사용자라 메모리에만 둔다."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.started_at)
        return [j.to_dict() for j in jobs]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def clear_finished(self) -> None:
        with self._lock:
            self._jobs = {k: v for k, v in self._jobs.items() if v.status == "running"}

    def start(self, pdf: Path, translate: bool, data_dir: Path) -> Job:
        job = Job(id=uuid.uuid4().hex[:8], filename=pdf.name)
        with self._lock:
            self._jobs[job.id] = job

        thread = threading.Thread(
            target=self._run, args=(job, pdf, translate, data_dir), daemon=True
        )
        thread.start()
        return job

    def _run(self, job: Job, pdf: Path, translate: bool, data_dir: Path) -> None:
        cmd = [sys.executable, "-X", "utf8", "-m", "pipeline", str(pdf), "-o", str(data_dir)]
        if not translate:
            cmd.append("--no-translate")

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            job.status = "error"
            job.message = f"실행하지 못했습니다: {exc}"
            job.finished_at = time.time()
            return

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            job.log.append(line)
            nice = _friendly(line)
            if nice:
                job.message = nice

        code = proc.wait()
        job.finished_at = time.time()
        if code == 0:
            job.status = "done"
            job.message = "완료"
        else:
            job.status = "error"
            # 마지막 오류 줄을 찾아 보여준다. 없으면 로그 끝줄.
            errors = [l for l in job.log if "ERROR" in l or "Error" in l]
            job.message = (errors[-1] if errors else (job.log[-1] if job.log else "실패"))[:200]
