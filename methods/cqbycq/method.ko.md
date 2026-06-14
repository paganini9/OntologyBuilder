# CQbyCQ — 역량 질문(CQ) 단위 온톨로지 구축

> 출처: Lippolis et al., *Ontology Generation using Large Language Models*, ESWC 2024 (arXiv:2503.05388) 의 **CQbyCQ** 변형.

## 1. 한 줄 요약
**역량 질문(Competency Question, CQ)** 을 하나씩, 서로의 맥락 없이(*memoryless*) OWL 온톨로지 조각으로 바꾼 뒤 합쳐서 온톨로지를 만든다.

## 2. 핵심 개념
- **역량 질문(CQ)**: 온톨로지가 답할 수 있어야 하는 질문. 예) "제품은 어떤 부품들로 구성되는가?"
- **Memoryless**: 각 CQ를 독립적으로 처리 → 프롬프트가 짧고 토큰을 아낀다(원논문 기준 컨텍스트 약 60% 절감). 대신 CQ 간 일관성은 병합 단계에서 확보.
- **온톨로지 조각**: CQ 하나에서 추출되는 (클래스, 객체 속성, 데이터 속성, 제약) 묶음.

## 3. 구축 프로세스 (단계별)
1. **CQ 수집** — `competency_questions.txt` 한 줄에 하나씩.
2. **CQ → 조각 변환 (반복)** — CQ마다 LLM(또는 MOCK 휴리스틱)이 JSON 조각 `{classes, object_properties, data_properties, restrictions}` 을 생성.
3. **병합** — 조각을 누적 그래프에 합친다. 속성의 domain/range로 참조된 클래스는 자동 생성. 중복은 무시.
4. **산출** — 각 CQ 처리 후 스냅샷을 남겨 "온톨로지가 자라나는 과정"을 보여주고, 최종적으로 `ontology.ttl`(OWL/Turtle), `ontology.json`(그래프), `steps.json`(단계별 스냅샷)을 쓴다.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `competency_questions.txt` | CQ 목록(한 줄 1개, `#` 주석·빈 줄 무시) |
| 출력 | `ontology.ttl` | OWL 온톨로지 (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges (그래프 시각화용) |
| 출력 | `steps.json` | CQ별 스냅샷 — 단계별 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(테스트 golden 고정). CQ에서 대문자 명사를 클래스로, 관계 동사(consist/made/produce/satisfy …)를 객체 속성으로 추출.
- `gemini`/`anthropic`: env에 키가 있으면 실제 LLM이 더 정교한 조각을 생성. 키 없으면 자동으로 MOCK 폴백.

## 6. 직접 해보기
1. `samples/competency_questions.txt` 를 수정하거나 새 CQ를 추가.
2. 사이트의 **Run** 버튼(또는 `python pipeline.py samples runs/out`) 실행.
3. 그래프가 CQ마다 커지는 과정을 단계 슬라이더로 확인.
