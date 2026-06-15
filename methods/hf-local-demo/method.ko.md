# HF-Local Demo — 로컬 오픈모델로 실제 온톨로지 추출

> 본 프로젝트 데모. 클라우드·API 키 없이 **이 PC의 GPU에서 HuggingFace 오픈모델을 직접 구동**해 텍스트에서 트리플(온톨로지)을 추출한다.

## 1. 한 줄 요약
문장마다 로컬 LLM에게 "(주어, 관계, 목적어) 트리플을 JSON으로 내라"고 요청하고, 그 트리플을 모아 온톨로지 그래프를 만든다. **MOCK**(키·GPU 불필요, 결정론)과 **hf_local**(실제 GPU 추론)을 같은 코드로 전환한다.

## 2. 핵심 개념
- **로컬 추론**: 외부 API 없이 `transformers`로 오픈모델(기본 `Qwen/Qwen2.5-1.5B-Instruct`)을 내려받아 GPU(`device_map="auto"`)에서 구동. 키가 없어도, 인터넷 없이도(최초 다운로드 후) 동작.
- **이중 백엔드**: `mock`은 규칙 기반 결정론 추출(테스트 golden 고정), `hf_local`은 실제 모델이 JSON 트리플 생성. 사이트의 백엔드 드롭다운에서 `hf_local`을 고르면 실제 모델이 돈다.
- **강건한 JSON 파싱**: 모델 응답에서 `{"triples":[...]}` 블록만 안전하게 추출(주변 잡설 무시).

## 3. 구축 프로세스 (단계별)
1. **텍스트 입력** — `text.txt` (문장 단위 자동 분리).
2. **문장→트리플 (반복)** — 각 문장을 LLM(mock 또는 hf_local)에 보내 JSON 트리플을 받는다.
3. **그래프 병합** — 주어·목적어는 클래스 노드로, 관계는 엣지로 누적(중복 제거). 문장마다 스냅샷.
4. **산출** — `ontology.ttl`·`ontology.json`·`steps.json`.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `text.txt` | 자유 텍스트(문장 자동 분리) |
| 출력 | `ontology.ttl` | OWL (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges |
| 출력 | `steps.json` | 문장별 스냅샷 |

## 5. LLM 백엔드
- 기본 `mock`: 키·GPU 없이 결정론(대문자 주어/관계동사/대문자 목적어). 테스트·키리스 사이트용.
- **`hf_local`(실구동)**: `transformers`로 `HF_MODEL`(기본 Qwen2.5-1.5B-Instruct) 다운로드 후 GPU 추론. 최초 1회 모델 다운로드(수 GB). 환경변수 `HF_MODEL`로 모델 교체 가능(예: `Qwen/Qwen2.5-3B-Instruct`).
- `transformers`/`torch` 미설치 시 자동으로 MOCK 폴백(루프 불중단).

## 6. 직접 해보기
1. (실구동 준비) `pip install torch transformers accelerate` — GPU면 CUDA torch 권장.
2. 로컬: `python pipeline.py samples runs/out --backend hf_local` (최초 다운로드 후 GPU 추론).
3. 사이트: 백엔드 드롭다운에서 **hf_local** 선택 후 **Run**. (mock으로 두면 즉시 결정론 결과)
