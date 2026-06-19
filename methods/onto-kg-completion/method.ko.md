# 온톨로지 강화 KG 완성 (LLM) — 빠진 링크를 예측

> 출처: Guo, Wang, Chen, Li, Chen, *Ontology-Enhanced Knowledge Graph Completion using Large Language Models*, arXiv:2507.20643 (2025).

## 1. 한 줄 요약
**부분(미완성) 지식그래프**와 그 **온톨로지 제약**이 주어지면, **빠진 링크**를 예측한다(KG 완성 / 링크 예측). 즉, 처음부터 만드는 게 아니라 **이미 있는 KG를 완성**한다.

## 2. 다른 방법들과의 결정적 차이
이 프로젝트의 다른 방법들은 자유 텍스트나 역량 질문으로부터 온톨로지/KG를 **새로 구축**한다. 이 방법은 **이미 존재하지만 불완전한** KG에서 출발해, **있어야 하는데 빠져 있는 엣지를 채우는** 일만 한다. 새 클래스를 만들지 않고, 기존 스키마가 곧 탐색 공간이다.

## 3. 핵심 개념
- **구축이 아니라 완성**: 입력은 그래프, 출력은 같은 그래프 + **추론된 엣지**.
- **온톨로지 강화**: 클래스 타입과 속성 의미(domain/range, 이행성·역관계·대칭성)가 예측을 제약해 추론 링크가 스키마와 **일관**되도록 만든다 — LLM이 그래프 밖 사실을 환각하지 않게 막는 핵심 장치.
- **근거 기반 추론**: 추론 트리플은 주어와 목적어가 **모두 기존 클래스**이고 그 엣지가 **아직 없을 때만** 채택한다.

## 4. 완성 프로세스 (단계별)
1. **(load) seed KG** — `seed_kg.ttl`을 rdflib로 파싱: 기존 클래스와 기존 객체속성 엣지. 불러온 모든 노드/엣지는 `origin = "seed"`로 표시.
2. **(complete) inferred edges** — 빠진 링크 예측:
   - **MOCK** (기본, 결정론): 온톨로지 규칙 완성 —
     (a) `partOf`/`consistsOf`/`contains` 사슬의 **이행성**(A→B, B→C ⇒ A→C),
     (b) 알려진 쌍의 **역관계**(`partOf`⇄`hasPart`),
     (c) 대칭 관계의 **대칭성**,
     (d) **domain/range** 기반 제안. **새 엣지만** 추가.
   - **REAL** (`gemini`/`anthropic`): seed KG를 텍스트로 기술해 모델에 일관된 추가 트리플을 추론하게 하고, **기존 클래스 사이**이며 **아직 없는** 트리플만 채택.
   추론 엣지는 `origin = "inferred"`로 표시.
3. **산출** — 최종 그래프 = seed + inferred. `ontology.ttl`(OWL/Turtle), `ontology.json`(그래프), `steps.json`(load → complete 스냅샷) 작성.

## 5. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `seed_kg.ttl` | 기존의 부분 KG (클래스 + 객체속성 엣지) |
| 출력 | `ontology.ttl` | seed + 추론 엣지, OWL (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges, `origin` = seed \| inferred |
| 출력 | `steps.json` | 두 스냅샷: 로드된 seed, 완성된 그래프 |

## 6. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적 규칙 기반 완성(golden 고정). 샘플 KG에서 seed 엣지 4개를 10개(추론 6개)로 만든다.
- `gemini`/`anthropic`: 키가 있으면 실제 LLM이 완성을 제안하고, seed 클래스에 근거하도록 필터링. 키 없으면 자동 MOCK 폴백.

## 7. 직접 해보기
1. `samples/seed_kg.ttl`을 수정(클래스를 추가하거나 일부 링크를 일부러 빼기).
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`) 실행.
3. seed 그래프 위에 **추론된** 엣지가 나타나는 과정을 단계 슬라이더로 확인.
