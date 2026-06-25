# MedKGent — 두 에이전트 기반, 신뢰도 인식, 시간 진화 의료 지식그래프

> 출처: *MedKGent: A Large Language Model Agent Framework for Constructing Temporally Evolving Medical Knowledge Graph*, arXiv:2508.12393 (Zhang 외, MBZUAI 등).

## 1. 한 줄 요약
정적 말뭉치에서 LLM 추출 결과를 단순 합치는 대신, MedKGent는 협력하는 두 에이전트로 의료 KG를 **하루 단위로** 구축한다: 날짜가 달린 초록에서 신뢰도 점수가 매겨진 트리플을 뽑는 **Extractor**, 그리고 그것을 시간순으로 통합하며 반복된 발견을 **강화**하고 모순을 신뢰도로 **해소**하는 **Constructor**.

## 2. 핵심 아이디어
- **시간적 역학.** 생의학 지식은 변한다 — 2022년 주장이 2025년 시험으로 뒤집힐 수 있다. MedKGent는 모든 사실에 타임스탬프를 달고 발표일 순서로 그래프를 구축해, 지식이 *언제* 등장했는지를 KG에 반영한다.
- **존재 여부가 아니라 신뢰도.** Extractor는 샘플링 기반 추정으로 각 트리플에 신뢰도를 부여한다. 약한 주장("may", "preliminary")은 낮은 점수를 받아 임계값 미만이면 **걸러지고**, 강한 주장("confirmed", "significantly")은 높은 점수를 받는다.
- **강화(Reinforcement).** 동일 `(주어, 관계, 목적어)`가 다시 관측되면 신뢰도를 결합(noisy-OR)하고 support를 늘리며 유효 기간을 넓힌다 — 반복 지식은 중복되지 않고 강화된다.
- **충돌 해소(Conflict resolution).** 같은 쌍에 대한 극성 반대 관계(예: 위험을 `increases` vs `reduces`)는 신뢰도가 높은 사실을 남겨 조정하고, 패자는 **superseded**로 표시해 활성 그래프에서 제외한다.

## 3. 구축 과정 (단계별)
1. **날짜순 정렬** — 초록을 `[YYYY-MM-DD]` 기준으로 정렬해 Constructor가 시간 순방향으로 작업하게 한다.
2. **Extractor 에이전트** — 각 초록을 절(clause)로 나눠 절마다 `(주어, 관계, 목적어)` 트리플 하나를 추출하고 언어적 단서로 신뢰도를 매긴다. 임계값 미만 트리플은 버린다.
3. **Constructor 에이전트** — 남은 트리플을 통합: 새 것이면 *추가*, 본 적 있으면 *강화*(신뢰도 결합, support 증가, `first_seen…last_seen` 확장), 극성 충돌이 나면 강한 사실을 남기고 약한 것을 superseded 처리.
4. **출력(Emit)** — 초록마다 스냅샷 하나(시간에 따라 그래프가 진화하는 모습을 UI에서 재생) 후 `ontology.ttl`, `ontology.json`(엣지가 confidence/support/first_seen/last_seen/provenance를 가짐), `steps.json`.

## 4. 입력 / 출력
| 종류 | 파일 | 설명 |
|------|------|------|
| 입력 | `abstracts.txt` | 날짜 달린 초록 `"[YYYY-MM-DD] text"`; 대문자 엔티티를 관계 동사가 연결, 약함/강함 단어가 신뢰도 결정 |
| 출력 | `ontology.ttl` | OWL: 엔티티=`owl:Class`, 활성 관계=`owl:ObjectProperty`(domain/range); confidence/support/기간은 `rdfs:comment` |
| 출력 | `ontology.json` | 그래프; 각 관계 엣지가 `confidence`, `support`, `first_seen`, `last_seen`, `provenance`를 가짐 |
| 출력 | `steps.json` | 초록별(하루별) 스냅샷 — 시간 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 결정론적·키 불필요(골든 파일 안정). 관계 동사 맵이 트리플을, 투명한 단서 기반 휴리스틱이 샘플링 기반 신뢰도를 대신하며, 강화·충돌 해소는 순수 규칙이다.
- `gemini` / `anthropic` / `hf_local`: 실제 모델이 Extractor 역할을 하고, 신뢰도 결합과 충돌 해소는 규칙 기반으로 유지해 시간 그래프 형태가 안정적이다. 키가 없으면 자동으로 MOCK으로 폴백.
- 참고: 발표된 MedKGent는 32B 모델로 약 1,000만 PubMed 초록을 처리해 지금까지 가장 큰 LLM 유래 의료 KG를 만든다. 본 구현은 **두 에이전트 + 신뢰도 + 시간 강화/충돌** 핵심을 유지하면서 작은 샘플에서 키 없이 재현 가능하게 동작한다.

## 6. 사용해 보기
1. `samples/abstracts.txt`를 편집 — 각 줄에 `[YYYY-MM-DD]`를 달고, 이후 초록에서 같은 사실을 다시 진술해 강화되는 모습을, 더 강한 표현의 반대 주장(`increases` vs `reduces`)을 넣어 충돌 해소를 확인한다.
2. **Run**(또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 KG가 하루씩 진화하는 모습을 보고, 엣지에 마우스를 올려 신뢰도·support·기간을 확인한다.
