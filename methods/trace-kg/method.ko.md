# TRACE-KG — 텍스트 기반 스키마, 맥락 강화 지식그래프

> 출처: *Beyond Predefined Schemas: TRACE-KG for Context-Enriched Knowledge Graphs from Complex Documents* (**TRACE-KG**, Text-dRiven schemA), arXiv:2604.03496 (Arizona State University).

## 1. 한 줄 요약
**미리 정의된 온톨로지 없이** 지식그래프를 만든다: 텍스트에서 곧바로 **데이터 기반 스키마**를 유도하고, 관계에 **조건 한정자(qualifier)**를 붙이며, 모든 엣지를 **원문 문장까지 추적(traceability)**한다.

## 2. 핵심 아이디어
- **스키마 사전정의를 넘어서**: 온톨로지 기반 파이프라인은 수작업 스키마가 필요하고, 스키마-프리 추출은 파편화된 그래프를 낳는다. TRACE-KG는 그 중간 — 스키마 뼈대를 *텍스트 자체에서 유도*(여기서는 명시적 is-a 단서로)하여, 사전 설계 없이도 재사용 가능한 의미 backbone을 유지한다.
- **맥락 강화 관계**: 실제 문서의 사실은 *특정 조건 아래에서만* 성립하는 경우가 많다. TRACE-KG는 그 조건을 관계의 **한정자**로 포착한다(예: `Pump consistsOf Impeller [Pressure]`). 평면 트리플이 버리는 맥락을 보존한다.
- **추적성**: 모든 노드·엣지가 **원문 문장 인덱스(`provenance`)**를 기록하여, 그래프를 항상 근거 문장으로 되짚을 수 있다.

## 3. 구축 과정 (단계별)
1. **텍스트 읽기** — `text.txt`의 자유 본문을 문장 단위로 분리(`#` 주석 줄 무시).
2. **문장별 분류** — LLM(또는 MOCK 휴리스틱)이 각 문장을 둘 중 하나로 태깅:
   - **is-a 사실** → `subClassOf(child, parent)`, 유도된 스키마 뼈대를 키움; 또는
   - **관계** `(주어, 관계, 목적어)` + `when / if / during / under / while` 절에서 추출한 선택적 **한정자**.
   UI 재생을 위해 문장마다 스냅샷을 남긴다.
3. **누적** — 클래스, 한정 관계, subClassOf 엣지를 삽입 순서대로(결정론) 병합. 각 엣지는 `qualifier`(없을 수 있음)와 `provenance`(원문 문장)를 지닌다.
4. **출력** — `ontology.ttl`(클래스 `owl:Class`, 관계 `owl:ObjectProperty`+domain/range, 계층 `rdfs:subClassOf`), `ontology.json`(그래프; 엣지 라벨은 `관계 [한정자]`), `steps.json`(단계 스냅샷).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `text.txt` | 자유 텍스트(`.` `!` `?`로 문장 분리) |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty`(domain/range), `rdfs:subClassOf` |
| 출력 | `ontology.json` | 그래프; 관계 엣지에 `qualifier`+`provenance` 포함 |
| 출력 | `steps.json` | 단계별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(골든 파일 안정). is-a 단서가 스키마 뼈대를, `when/if/during/...` 절이 한정자를 만든다.
- `gemini`/`anthropic`/`hf_local`: 키/모델이 있으면 실제 LLM이 관계를 추출(실모델 경로에서는 한정자 비움). 병합·출력 로직은 동일해 그래프 형태가 안정적. 키 없으면 자동 MOCK 폴백.
- 참고: 발표된 TRACE-KG는 멀티모달로 제시되지만, 본 구현은 **텍스트 기반 스키마 + 한정자 + 추적성** 핵심만 살려 키 없이 재현 가능하게 동작한다.

## 6. 직접 해보기
1. `samples/text.txt`를 편집 — is-a 문장(`A Pump is a kind of Machine.`)과 조건 관계(`The Pump consists of an Impeller when the Pressure is high.`)를 섞는다.
2. 사이트 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 스키마 뼈대와 한정 관계가 쌓이는 과정을 확인하고, 엣지에 마우스를 올려 한정자·출처를 본다.
