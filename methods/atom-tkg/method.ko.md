# ATOM — 원자적 사실 기반 이중시간(dual-time) 시간 지식그래프

> 출처: *ATOM: AdapTive and OptiMized dynamic temporal knowledge graph construction using LLMs*, arXiv:2510.22590 (Lairgi 외, INSA Lyon / LIRIS).

## 1. 한 줄 요약
시간에 따라 계속 갱신되는 **시간 지식그래프(TKG)** 를 만든다: 각 노트를 최소 단위의 **원자적 사실(atomic fact)** 로 쪼개고, 모든 사실에 **이중 시간**(언제 *관측*되었는가 vs 언제 *유효*한가)을 부여한 뒤, 원자 그래프들을 **병합**한다. 같은 사실이 다시 관측되면 중복으로 쌓지 않고 유효 구간을 **넓힌다**.

## 2. 핵심 아이디어
- **원자적 사실**: 긴 문장은 여러 사실을 품고 있어 실행마다 추출이 불안정하다. ATOM은 먼저 노트를 최소·자기완결적 절(clause)로 분해하고, 절 하나당 `(주어, 관계, 목적어)` 트리플 하나를 추출해 *추출 충실도*와 *안정성*을 높인다.
- **이중 시간 모델링**: 한 사실은 서로 독립인 두 시간선을 가진다 — `observed`(노트가 기록한 시점)와 `valid` 구간(`valid_from` … `valid_until`, 사실이 실제로 성립하는 기간). "Beta는 **2024년부터** Acme의 자회사"가 2024-01 노트에 기록되면 `observed=2024-01`, `valid_from=2024`.
- **병렬 병합 / 지속 갱신**: 원자 TKG들을 `(주어, 관계, 목적어)` 키로 병합한다. 같은 사실이 반복되면 **가장 이른** 관측을 유지하고 유효 구간을 **넓힌다**(`valid_from`은 최소, `valid_until`은 최대). 그래서 새 증거가 그래프를 부풀리지 않고 갱신한다.

## 3. 구축 과정 (단계별)
1. **노트 읽기** — `events.txt`, 한 줄에 날짜 달린 노트 `"[YYYY-MM] 텍스트"` (`#` 주석 줄 무시). 대괄호가 **관측** 날짜다.
2. **원자 분해** — 노트 본문을 절 단위(`.` `!` `?`)로 나눈다. 각 절이 원자적 사실 하나.
3. **추출 + 이중시간 태깅** — LLM(또는 MOCK 휴리스틱)이 절마다 트리플을 반환하고, 규칙이 `since/from YYYY` 단서로 `valid_from`(없으면 관측일), `until/to YYYY` 단서로 `valid_until`(없으면 열린 구간)을 정한다.
4. **병합** — 각 원자 사실을 트리플 키로 누적 TKG에 접고, 재관측 시 유효 구간을 넓힌다. 노트마다 스냅샷을 남겨 UI가 그래프 성장과 구간 확장을 재생할 수 있게 한다.
5. **산출** — `ontology.ttl`(엔티티 `owl:Class`, 관계 `owl:ObjectProperty` 도메인/레인지, 구간은 `rdfs:comment`), `ontology.json`(엣지에 `observed`/`valid_from`/`valid_until`+`provenance`), `steps.json`.

## 4. 입력 / 출력
| 종류 | 파일 | 비고 |
|------|------|------|
| 입력 | `events.txt` | 날짜 노트 `"[YYYY-MM] 텍스트"`; `since/until YYYY` 단서가 유효 구간 설정 |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty`(도메인/레인지), 구간 주석 |
| 출력 | `ontology.json` | 그래프; 각 관계 엣지에 `observed`+`valid_from`+`valid_until`+`provenance` |
| 출력 | `steps.json` | 노트별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 키 없이 결정론적으로 동작(골든 파일 안정). 작은 관계동사 맵으로 원자 트리플을 만들고, 이중시간 태깅은 순수 규칙이다.
- `gemini` / `anthropic` / `hf_local`: 실제 모델이 원자 트리플을 추출하고, 이중시간 태깅은 규칙 그대로라 시간 그래프 형태가 안정적이다. 키가 없으면 자동으로 MOCK으로 폴백.
- 참고: 원논문 ATOM은 대규모 스트리밍·병렬성·안정성 지표를 다루지만, 본 구현은 **원자적 사실 + 이중시간 + 구간 확장 병합** 핵심만 담아 키 없이 재현 가능하게 동작한다.

## 6. 사용해 보기
1. `samples/events.txt` 편집 — `[2024-01] ...` 형식으로 날짜를 달고 `since 2024` / `until 2025` 단서를 넣고, 뒤쪽 노트에서 같은 사실을 다시 적어 구간이 넓어지는지 본다.
2. **Run** 클릭 (또는 `python pipeline.py samples runs/out --backend mock`).
3. 단계 슬라이더로 원자 사실이 병합되는 과정을 보고, 엣지에 마우스를 올려 관측 시점과 유효 시점을 확인한다.
