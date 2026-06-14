# ODKE+ — 온톨로지 가이드 5단계 개방형 추출

> 출처: Khorshidi, Nikfarjam et al. (Apple), *ODKE+: Ontology-Guided Open-Domain Knowledge Extraction with LLMs*, 2025 (arXiv:2509.04696).

## 1. 한 줄 요약
**5단계 프로덕션 파이프라인**(추출 개시 → 근거 수집 → 하이브리드 추출 → 검증(2차 LLM) → 보강)으로, 엔티티 타입별 **온톨로지 스니펫을 동적 생성**해 스키마 제약과 정렬하며 사실을 자동 추출·적재한다.

## 2. 핵심 개념
- **5개 컴포넌트**: (1) **Extraction Initiator**(누락/오래된 사실 탐지), (2) **Evidence Retriever**(근거 문서 수집), (3) **Hybrid Extractor**(규칙 + 온톨로지-가이드 LLM 프롬프트), (4) **Grounder**(2차 LLM이 추출 사실 검증), (5) **Corroborator**(후보 순위·정규화).
- **동적 온톨로지 스니펫**: 엔티티 타입마다 필요한 스키마 조각을 즉석 생성해 추출을 제약.
- **생성-검증 분리**: 추출 LLM과 검증 LLM을 분리해 정밀도를 높인다(원논문 19M 사실, 98.8% 정밀도).

## 3. 구축 프로세스 (단계별)
1. **입력 수집** — `entities.txt`(추출 대상 엔티티 목록)와 근거 텍스트(`samples/evidence.txt`, 선택).
2. **추출 개시** — 각 엔티티에 대해 채울 속성 슬롯(온톨로지 스니펫)을 정한다.
3. **근거 수집** — 엔티티 관련 근거 문장을 모은다.
4. **하이브리드 추출** — 규칙 + (온톨로지-가이드) LLM으로 후보 사실(트리플)을 뽑는다.
5. **Grounder 검증** — 2차 패스로 각 후보가 근거에 부합하는지 검증, 불합격은 버린다.
6. **Corroborator 보강** — 검증된 후보를 순위·정규화해 최종 그래프에 적재.
7. **산출** — 단계별 스냅샷과 `ontology.ttl`·`ontology.json`·`steps.json`을 쓴다.

## 4. 입력 / 출력
| 구분 | 파일 | 설명 |
|------|------|------|
| 입력 | `entities.txt` | 추출 대상 엔티티(한 줄 1개) |
| 입력 | `evidence.txt` | 근거 텍스트(선택) |
| 출력 | `ontology.ttl` | 검증된 사실 기반 OWL (Turtle) |
| 출력 | `ontology.json` | Cytoscape nodes/edges (검증 통과만) |
| 출력 | `steps.json` | 5단계 스냅샷(검증 합격/탈락 표시) |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작. 추출은 cqbycq 휴리스틱, Grounder 검증은 "근거 텍스트에 주어·목적어가 함께 등장하는가" 규칙으로 합격 판정(미충족 후보는 탈락).
- `gemini`/`anthropic`(api): 키가 있으면 추출 LLM + 별도 검증 LLM을 사용. 키 없으면 자동 MOCK 폴백.

## 6. 직접 해보기
1. `samples/entities.txt`(와 선택적으로 `samples/evidence.txt`)를 교체.
2. **Run**(또는 `python pipeline.py samples runs/out`) 실행.
3. 단계 슬라이더로 개시→수집→추출→검증→보강 흐름과 탈락한 후보를 확인.
