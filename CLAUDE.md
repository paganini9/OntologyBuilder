# implementation/ — 온톨로지 구축 방법 구현 Loop (운영 매뉴얼)

연구된 온톨로지 구축 방법을 **하나씩 구현**해 KO/EN 웹사이트로 보여주는 지속형 Loop Agent. 이 폴더만 별도 git repo다.

## 폴더 지도
```
registry/methods.json     # 단일 진실원 — 방법 목록 + 상태 + 난이도 (루프 제어)
registry/candidates.json  # 일일 탐색으로 발견된 미승인 신규 후보
registry/new-candidates.md# 일일 작업이 쓰는 사람이 읽는 리포트
methods/<id>/             # 방법별: meta.json, method.ko/en.md, pipeline.py, samples/, fixtures/, tests/
backend/llm/              # LLM 백엔드 추상화 (mock|gemini|anthropic|hf_local)
backend/app.py            # FastAPI (목록/실행/정적 서빙, 127.0.0.1)
backend/runner.py         # 파이프라인 subprocess 격리 실행
backend/registry.py       # registry 접근 + next_easiest() 선택 규칙
site/_src/                # 단일 소스(템플릿+assets+locales) — 여기만 수정
site/ko, site/en          # build_site.py가 생성하는 두 정적 사이트 (직접 수정 금지)
scripts/                  # build_site.py, git_push_method.ps1, run_daily.ps1, notify.ps1
runs/                     # FastAPI 실행 산출물 (gitignore)
```

## 파이프라인 계약 (모든 방법 공통)
- `methods/<id>/pipeline.py` 에 `run(input_dir, out_dir, backend=None) -> manifest(dict)`.
- LLM은 `from backend.llm import get_backend` 로만. MOCK 결정론을 위해 `get_backend(backend, mock_responder=<방법전용 결정론 함수>)`.
- 출력: `ontology.ttl`, `ontology.json`(Cytoscape nodes/edges), `steps.json`(단계 스냅샷), `manifest.json`.
- 그래프 포맷은 `methods/cqbycq/pipeline.py`의 `_Model.to_graph()`와 동일.
- 레퍼런스 구현: **cqbycq** (이 구조를 그대로 따라 새 방법을 만든다).

## 로컬 실행
```powershell
cd implementation
python -m pip install -r requirements.txt          # 최초 1회
python -m pytest methods/cqbycq/tests/ -q           # 테스트
python scripts/build_site.py                        # 사이트 빌드
python -m backend.app                                # http://127.0.0.1:8000 (→ /ko/, /en/)
```
파이프라인 단독 실행: `python methods/cqbycq/pipeline.py methods/cqbycq/samples runs/out --backend mock`

## 루프 (방법 1개 = 한 사이클)
`/impl-next` 가 수행: 선택(next_easiest) → `method-analyst` → `method-implementer` → `method-tester`(실패 시 최대 2회 재시도) → `site-builder` → status=published → `git_push_method.ps1`.
- `/impl-status` 현황, `/impl-approve <id>` 신규 후보 승격, `/impl-daily-check` 일일 탐색.
- 다음 선택 규칙: status∈{discovered,analyzed,queued} ∧ approved ∧ blockers==[] 중 (difficulty.score, mock 우선, 입력 수) 최소.

## LLM 백엔드 (env)
`.env`(gitignore) 또는 시스템 환경변수. 키 없으면 자동 MOCK 폴백.
- `LLM_BACKEND=mock|gemini|anthropic|hf_local` (기본 mock)
- `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `HF_MODEL`/`HF_HOME`
- 키는 코드·git에 절대 쓰지 않는다. 필요해지면 사용자에게 입력 요청.

### 로컬 HuggingFace 실구동 (검증됨)
- 이 PC: **RTX 3080 Ti(12GB) + torch cu128 + transformers/accelerate 설치 완료** → `hf_local` 백엔드가 실제 GPU에서 동작.
- 데모 방법 **`hf-local-demo`** 가 `backend=hf_local` 선택 시 `HF_MODEL`(기본 Qwen2.5-1.5B-Instruct)을 다운로드해 GPU 추론(검증: CLI + 사이트 API 둘 다). 기본은 mock(결정론).
- GPU torch 설치: `pip install torch --index-url https://download.pytorch.org/whl/cu128`. 모델 캐시는 `.hf_cache/`(gitignore).
- 다른 방법도 `hf_local`로 돌리려면 meta의 `backend_default`/사이트 드롭다운에서 선택. 무거운 방법(SAC-KG 등 파인튜닝)은 여전히 별도 작업 필요.

## 매일 07:00 스케줄 등록 (최초 1회, 사용자 실행)
관리자 PowerShell에서:
```powershell
schtasks /Create /TN "OntologyResearch-DailyMethods" /SC DAILY /ST 07:00 `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"C:\Users\jaehyunlee\ClaudeWork\Working\OntologyResearch\implementation\scripts\run_daily.ps1`""
```
`run_daily.ps1` → `claude -p "/impl-daily-check"` (headless). **탐색→자동 구현→푸시→사후통지**까지 수행(사용자 사전 승인됨).

### 자동 구현 정책 (daily-check)
- **자동 구현**: MOCK으로 키 없이 동작 + 논문 확보 + GPU/파인튜닝 불필요 + 난이도<8 인 후보. 한 번에 최대 2개.
- **자동 구현 제외(알림만, `/impl-approve` 대기)**: 실제 GPU/파인튜닝, 유료키 실구동 필수, 논문 PDF 미확보, 난이도≥8.
- **게이트**: 자동 구현은 `pytest` 전체 + `scripts/verify_ui.py`(UI 렌더) 통과 시에만 published+push. 실패는 `status="blocked"`로 두고 통지.
- 새 방법은 `comparison.json`에도 행을 추가(양언어)해 비교표에 자동 반영.

## git / GitHub
- 이 폴더가 repo. 방법 published 시 `scripts/git_push_method.ps1 <id>`.
- **GitHub 연결(최초 1회)**: 빈 repo 생성 후
  ```powershell
  git -C implementation remote add origin <REPO_URL>
  git -C implementation push -u origin main
  ```
  (`gh` CLI가 있으면 `gh repo create`로 대체 가능. 현재 미설치.)

## 블로커 (사용자 액션 필요)
1. GitHub 원격/`gh` 미설치 → 첫 push 전 1회.
2. schtasks 등록(관리자 권한) → 최초 1회.
3. 실제 API 키 → 비-MOCK 출력 원할 때만(없으면 MOCK 진행).
4. 논문 PDF 없음 → analyst가 요청, 사용자가 다운로드.

## 의존성 참고
core: fastapi, uvicorn, rdflib, python-dotenv, requests, pytest.
프론트는 cytoscape.js(CDN)로 그래프 렌더 — 오프라인 시 그래프만 비활성(브라우징·실행은 동작).
