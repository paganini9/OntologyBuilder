# AGENTiGraph — 대화형 멀티에이전트 KG 구축

> 출처: *AGENTiGraph: A Multi-Agent Knowledge Graph Framework for Interactive, Domain-Specific LLM Chatbots*, CIKM 2025 Demo (arXiv:2508.02999).

## 1. 한 줄 요약
비전문가가 **자연어 발화**로 지식그래프를 점진적으로 구축·정제할 수 있도록, **의도 분류 → 작업 계획 → 자동 지식 통합**을 담당하는 멀티에이전트가 사용자 발화를 처리해 KG를 키워 나간다(사용자 in-the-loop).

## 2. 핵심 개념
- **대화형 점진 구축**: 한 번에 일괄 추출이 아니라, 사용자의 발화(turn) 하나하나를 받아 KG를 조금씩 키운다.
- **의도 분류(Intent Classification)**: 각 발화가 "엔티티 추가/관계 추가/질의/수정" 중 무엇인지 분류한다(원논문 3,500-query 벤치마크 95.12% 분류 정확도).
- **작업 계획(Task Planning)**: 분류된 의도를 실행 단계로 분해한다(어떤 엔티티·관계를 어떤 순서로 통합할지).
- **자동 지식 통합(Knowledge Integration)**: 계획에 따라 새 지식을 기존 KG에 충돌 없이 병합한다.

## 3. 구축 프로세스 (단계별)
1. **시드·발화 수집** — `seed_text.txt`(초기 도메인 문맥, 선택)와 `user_turns.txt`(사용자 발화, 한 줄 1개).
2. **발화별 의도 분류 (반복)** — 각 발화를 add-entity / add-relation / query / refine 등으로 분류.
3. **작업 계획** — 의도를 통합 단계로 분해(추가할 클래스·관계 결정).
4. **지식 통합** — 계획대로 KG에 병합. 기존 노드와 충돌하면 통합/갱신.
5. **산출** — 발화마다 스냅샷을 남겨 "대화로 KG가 자라는 과정"을 보여주고, `ontology.ttl`·`ontology.json`·`steps.json`을 쓴다.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `seed_text.txt` | 초기 도메인 문맥(선택; 비어 있어도 됨) |
| 입력 | `user_turns.txt` | 사용자 발화(한 줄 1개) |
| 출력 | `ontology.ttl` | OWL 온톨로지 (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges |
| 출력 | `steps.json` | 발화별 스냅샷(의도·계획 포함) — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작. 의도는 규칙(의문문→query, "추가/연결" 동사→add, 대문자 2개+관계동사→add-relation)으로 분류하고, 통합은 cqbycq 휴리스틱으로 클래스·관계를 추출해 병합.
- `gemini`/`anthropic`(api): 키가 있으면 실제 LLM이 의도 분류·계획·통합을 수행. 키 없으면 자동 MOCK 폴백.

## 6. 직접 해보기
1. `samples/user_turns.txt` 에 자신의 발화를 한 줄씩 추가(예: "제품에 부품을 연결해줘").
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out`) 실행.
3. 단계 슬라이더로 각 발화의 의도→통합 결과와 그래프 성장 과정을 확인.
