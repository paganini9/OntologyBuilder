# 반복형 LLM 온톨로지 지식베이스 — 초안 → 정제

> 출처: *Development of Ontological Knowledge Bases by Leveraging Large Language Models*, arXiv:2601.10436 (차량 판매 도메인 사례).

## 1. 한 줄 요약
온톨로지 지식베이스를 **반복(iterative)** 사이클로 구축한다: 1차 패스가 뼈대(클래스+관계)를 **초안(draft)**으로 뽑고, **정제(refine)** 패스가 is-a 계층을 유도하고 데이터 속성을 붙여 풍부하게 만든다.

## 2. 핵심 아이디어
- **반복적 지식 획득**: 일회성 추출이 아니라 패스를 나눠 — 생성 후 검토·정제 — KB를 발전시킨다. 초안이 무엇을 잡았고 정제가 무엇을 더했는지 보이므로 구축 과정이 *감사 가능*하다.
- **뼈대 먼저, 보강은 나중**: 초안은 의도적으로 클래스와 그 사이 객체 속성만 담는다. 계층·속성은 1차에서 만들지 않고, 초안 전체를 보는 정제 단계에서 도출한다.
- **아티팩트 생성**: 각 패스가 구체적 산출물(성장하는 온톨로지 그래프 + TTL)을 만들고, 단계 스냅샷이 사이클의 감사 기록이 된다.

## 3. 구축 과정 (단계별)
1. **텍스트 읽기** — `text.txt`의 자유 도메인 텍스트를 문장 단위로 분리(`#` 주석 줄 무시).
2. **반복 1 — DRAFT(문장별)**: LLM(또는 MOCK 휴리스틱)이 클래스와 객체 속성 `{name, domain, range}` 하나를 추출. 문장마다 스냅샷(`stage = "draft"`).
3. **반복 2 — REFINE(초안 전체 대상)**:
   - **계층**: compound-tail 규칙으로 `rdfs:subClassOf` 유도(예: `ElectricVehicle ⊑ Vehicle`, `SportsCar ⊑ Car`).
   - **속성**: 클래스와 함께 언급된 데이터 단어(`price`, `model`, `brand`, `year`, `color` 등)를 데이터타입 속성으로 부착.
   스냅샷 1개(`stage = "refine"`).
4. **출력** — `ontology.ttl`(클래스, 객체/데이터타입 속성, `rdfs:subClassOf`), `ontology.json`(그래프; 노드에 데이터 속성 표시), `steps.json`(초안 스냅샷 + 정제 스냅샷).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `text.txt` | 자유 도메인 텍스트(`.` `!` `?`로 문장 분리) |
| 출력 | `ontology.ttl` | OWL: 클래스, 객체/데이터타입 속성, `rdfs:subClassOf` |
| 출력 | `ontology.json` | 그래프; 노드에 데이터 속성 포함 |
| 출력 | `steps.json` | 문장별 초안 스냅샷 + 정제 스냅샷 1개 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적(골든 파일 안정). 초안 = 대문자 명사 + 관계 동사; 정제 = compound-tail subClassOf + 데이터 단어 속성.
- `gemini`/`anthropic`/`hf_local`: 키/모델이 있으면 초안은 실제 추출기 사용, 정제는 동일(결정론)해 계층·속성이 안정적. 키 없으면 자동 MOCK 폴백.

## 6. 직접 해보기
1. `samples/text.txt`를 편집 — 기본 클래스와 합성어(예: `Vehicle` + `ElectricVehicle`), 속성 단어(`price`, `year`)를 포함.
2. 사이트 **Run** 버튼(또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 초안 뼈대가 만들어진 뒤 정제 단계에서 계층·속성이 들어오는 과정을 확인.
