# Ontology-Grounded KG (Wikidata 스키마 기반)

> 출처: *Ontology-grounded Automatic Knowledge Graph Construction by LLM under Wikidata schema*, 2024 (arXiv:2412.20942).

## 1. 한 줄 요약
**역량 질문(CQ)** 으로부터 온톨로지를 저작한 뒤, 그 클래스·관계를 **Wikidata의 표준 스키마(속성 P-id)** 에 정렬(grounding)해, 외부 KG와 호환되는 온톨로지를 인간 개입 최소화로 만든다.

## 2. 핵심 개념
- **CQ 기반 저작**: CQbyCQ처럼 CQ에서 클래스·관계 초안을 만든다.
- **Wikidata grounding**: 로컬에서 만든 관계 이름(예: `consistsOf`)을 Wikidata 표준 속성(예: `P527 has part`)으로 매핑한다. 이렇게 하면 만들어진 KG가 전 세계 공개 KG와 호환된다.
- **인간 개입 최소화**: 매핑·정렬을 자동화해 수작업을 줄인다.

## 3. 구축 프로세스 (단계별)
1. **CQ 수집** — `competency_questions.txt`.
2. **온톨로지 저작** — CQ에서 클래스·객체속성 초안 생성(cqbycq 방식).
3. **Wikidata grounding** — 각 클래스/관계를 Wikidata 라벨·속성에 매핑(로컬 사전 기반 결정론 매핑; 매칭 없으면 로컬 이름 유지).
4. **병합·산출** — grounding 결과를 반영해 노드/엣지에 Wikidata id를 주석으로 달고, 단계별 스냅샷과 `ontology.ttl`·`ontology.json`·`steps.json`을 쓴다.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `competency_questions.txt` | CQ 목록 |
| 출력 | `ontology.ttl` | Wikidata 속성에 정렬된 OWL (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges (Wikidata id 주석 포함) |
| 출력 | `steps.json` | 저작·grounding 단계 스냅샷 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작. 저작은 cqbycq 휴리스틱, grounding은 내장 소형 사전(예: has part→P527, made from material→P186, manufacturer→P176)으로 매핑.
- `gemini`/`anthropic`(api): 키가 있으면 실제 LLM이 저작·grounding을 수행. 키 없으면 자동 MOCK 폴백.
- 비고: 본 구현은 외부 Wikidata API 호출 대신 내장 사전으로 grounding을 시연한다(오프라인·결정론). 실제 Wikidata 조회는 키/네트워크 연동 시 확장 가능.

## 6. 직접 해보기
1. `samples/competency_questions.txt` 를 수정.
2. **Run**(또는 `python pipeline.py samples runs/out`) 실행.
3. 단계 슬라이더로 저작→Wikidata grounding 과정과 매핑된 속성 id를 확인.
