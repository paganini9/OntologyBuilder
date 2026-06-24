# LLMs4OL 2025 — 모듈형 온톨로지 학습 (용어 → 타입 → 분류체계)

> 출처: *Alexbek at LLMs4OL 2025 Tasks A, B, and C: Heterogeneous LLM Methods for Ontology Learning* (Few-Shot Prompting, Ensemble Typing, Attention-Based Taxonomies), arXiv:2508.19428. 코드: github.com/BelyaevaAlex/LLMs4OL-Challenge-Alexbek.

## 1. 한 줄 요약
LLMs4OL 챌린지의 온톨로지 학습 전 과정을 하나의 **모듈형** 파이프라인으로 다룬다: 텍스트에서 용어와 타입을 **추출**(Task A), 처음 보는 용어를 **검색(retrieval)** 으로 **타이핑**(Task B), 타입들 사이의 **is-a 분류체계를 유도**(Task C). 전체 파인튜닝 없이 가볍게 동작한다.

## 2. 핵심 아이디어
- **세 서브태스크, 하나의 파이프라인**: 거대한 단일 모델 대신 온톨로지 학습을 Text2Onto(A), 용어 타이핑(B), 분류체계 발견(C)으로 분해한다. 각 모듈은 작고 교체 가능하며 같은 온톨로지를 함께 키운다.
- **검색 기반 용어 타이핑(핵심 차별점)**: 처음 보는 용어를 **이미 타입이 매겨진 예시 중 가장 가까운 것**을 찾아 그 타입을 부여한다. 원논문은 임베딩 코사인 + 신뢰도 가중 앙상블을 쓰지만, 여기서는 **공유 토큰/문자 트라이그램** 일치를 결정론적·키 없는 대체물로 쓴다. 그래서 `axial pump`는 가장 가까운 이웃 `centrifugal pump` 때문에 `Pump`로 타이핑된다.
- **is-a 유도로서의 분류체계**: 타입 계층(`Pump ⊑ Machine`)을 is-a 단서에서 유도해, 타이핑된 용어들이 매달릴 재사용 가능한 골격을 만든다.

## 3. 구축 과정 (단계별)
1. **읽기 & 라우팅** — `documents.txt`; 각 단서를 표면형으로 분기한다: `"<a/an 용어> is a/an <Type>"` → Task A; `"<Type> is a kind of <Parent>"` → Task C; `"? <용어>"` → Task B.
2. **Task A — Text2Onto** — A 단서마다 LLM(또는 MOCK 휴리스틱)이 `(용어, Type)` 쌍을 반환한다. Type은 클래스, 용어는 그 클래스의 `instanceOf` 개체가 된다. 이 쌍들이 **검색 뱅크**가 된다.
3. **Task C — 분류체계 발견** — C 단서마다 `subClassOf(Type, Parent)` 엣지를 추가해 계층을 키운다(부모는 필요 시 생성).
4. **Task B — 용어 타이핑** — 처음 보는 `? 용어`를 검색 뱅크와 매칭(공유 토큰 최대 → 트라이그램, 동점은 가장 이른 예시)해 타입을 부여한다. 엣지는 inferred로 표시하고 매칭된 이웃을 기록한다.
5. **산출** — `ontology.ttl`(타입 `owl:Class`, 계층 `rdfs:subClassOf`, 용어 `owl:NamedIndividual`을 클래스에 `rdf:type`), `ontology.json`(타입+용어 노드, `subClassOf`·`instanceOf` 엣지, 추론된 타이핑은 `instanceOf*`), `steps.json`(단서별 스냅샷, A → C → B 순서).

## 4. 입력 / 출력
| 종류 | 파일 | 비고 |
|------|------|------|
| 입력 | `documents.txt` | A/`is a`, C/`is a kind of`, B/`? 용어` 단서 |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf`, 타입 매겨진 `owl:NamedIndividual` |
| 출력 | `ontology.json` | 타입+용어 노드; `subClassOf`+`instanceOf` 엣지(추론은 `instanceOf*`, `via` 포함) |
| 출력 | `steps.json` | 단서별 스냅샷, Task A → C → B 순서 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(골든 파일 안정). Task A 추출은 휴리스틱 파싱, Task B 검색과 Task C 분류체계는 규칙 기반이라 그래프가 재현 가능하다.
- `gemini` / `anthropic` / `hf_local`: 실제 모델이 Task A `(용어, 타입)` 추출을 수행하고, 검색(B)·분류체계(C)는 결정론적으로 유지돼 형태가 안정적이다. 키가 없으면 자동으로 MOCK 폴백.
- 참고: 원 시스템은 분류체계용 소형 cross-attention 레이어(LoRA)와 타이핑용 임베딩 앙상블을 추가로 학습하지만, 본 구현은 **세 서브태스크 구조 + 검색 타이핑 + is-a 유도** 핵심만 담아 GPU·파인튜닝 없이 키 없이 재현 가능하게 동작한다.

## 6. 사용해 보기
1. `samples/documents.txt` 편집 — 타입 예시(`A gear pump is a Pump.`), is-a 엣지(`Pump is a kind of Machine.`), 미지의 질의(`? rotary pump`)를 추가한다.
2. **Run** 클릭 (또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 Task A 추출 → Task C 분류체계 → Task B 검색 타이핑을 차례로 보고, `instanceOf*` 엣지에 마우스를 올려 어떤 이웃으로부터 타이핑됐는지 확인한다.
