# RAGA — Read-Search-Verify-Construct 에이전트

> 출처: Han & Cheng, *RAGA: Reading-And-Graph-building-Agent for Autonomous Knowledge Graph Construction and Retrieval-Augmented Generation*, 2026 (arXiv:2605.17072).

## 1. 한 줄 요약
**단일 자율 에이전트**가 문서를 한 단위(문장)씩 읽으며 **ReAct 인지 루프**를 돌린다. 이 루프는 **Read → Search → Verify → Construct** 네 단계로 제약되며, 읽으면서 지식 그래프를 만들고 동시에 **근거 기반 검증(evidence-anchored)**으로 스스로 감사한다.

## 2. 핵심 아이디어
- **단위별 단일-에이전트 ReAct 인지 루프**: 고정된 다중 컴포넌트 파이프라인이 아니라, *하나의* 에이전트가 읽기 단위를 순회하며 단위마다 동일한 think→act 루프를 반복한다.
- **Read–Search–Verify–Construct 인지 제약**: 매 반복마다 네 하위 단계를 강제로 거치므로, 생성(Read) 뒤에 항상 맥락 연결(Search)과 자기 검증(Verify)이 이어지고, 그다음에야 그래프에 반영(Construct)된다.
- **근거 기반 검증**: 후보 트리플의 주어와 목적어가 *둘 다* 해당 문장 텍스트로 문자 그대로 뒷받침될 때만 반영한다. 표면 근거가 없는 함축/대명사 목적어는 폐기 — 두 번째 모델 없이도 정밀도를 높인다.
- **점진적 맥락 연결**: Search 단계에서 제안된 개체를 지금까지 만든 그래프와 연결해, 노드를 중복 생성하지 않고 기존 노드를 재사용한다.

## 3. 구축 과정 (단계별)
1. **입력 수집** — `text.txt`(자유 텍스트). 한 문장 = 한 에이전트 단위.
2. 각 문장마다 에이전트가 ReAct 루프를 수행:
   - **READ** — 문장에서 후보 (주어, 관계, 목적어) 트리플을 제안.
   - **SEARCH** — 제안된 개체를 지금까지의 그래프와 연결(이미 존재하는가?).
   - **VERIFY** — 근거 기반 검사: 주어와 목적어 토큰이 둘 다 문장에 등장할 때만 유지, 함축/대명사 목적어는 폐기.
   - **CONSTRUCT** — 검증된 트리플을 성장하는 그래프에 반영.
3. **산출** — 문장마다 `steps.json` 스냅샷(read/search/verify 추적 포함)과 `ontology.ttl`, `ontology.json`. 최종 그래프에는 근거 기반으로 검증된 트리플만 남는다.

## 4. 입력 / 출력
| 종류 | 파일 | 비고 |
|------|------|------|
| 입력 | `text.txt` | 원문 텍스트; 한 문장이 한 에이전트 단위 |
| 출력 | `ontology.ttl` | 검증된 트리플의 OWL(Turtle) |
| 출력 | `ontology.json` | Cytoscape 노드/엣지(검증된 것만) |
| 출력 | `steps.json` | 문장별 ReAct 스냅샷(read / search / verify / constructed) |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적. READ 단계는 문장을 휴리스틱으로 파싱하고 SEARCH/VERIFY/CONSTRUCT는 결정론 규칙을 적용. VERIFY는 주어·목적어가 둘 다 문장에 anchored 될 때만 후보를 유지.
- `gemini`/`anthropic` (api): 키가 있으면 READ 단계가 실제 LLM(`backend.llm.extract.extract_triples`)으로 후보를 제안하고, SEARCH/VERIFY/CONSTRUCT는 동일하게 적용되어 같은 방식으로 검증된다. 키가 없으면 자동으로 MOCK로 폴백.

## 6. 사용해 보기
1. `samples/text.txt`를 자신의 문장으로 교체.
2. 실행(또는 `python pipeline.py samples runs/out`).
3. 단계 슬라이더로 문장별 Read→Search→Verify→Construct 루프를 따라가며 VERIFY가 어떤 후보를 폐기하는지 확인(예: "The Housing protects them …"의 함축 대명사 목적어).
