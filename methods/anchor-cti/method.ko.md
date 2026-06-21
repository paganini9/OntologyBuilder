# ANCHOR — 하이브리드 온톨로지 디스커버리 기반 스키마-무관 CTI 지식그래프

> 출처: *Schema-Agnostic Knowledge Graph Construction via Hybrid Ontology Discovery for Cyber Threat Intelligence* (**ANCHOR**), arXiv:2606.01208, Kim 외, 2026.

## 1. 한 줄 요약
프롬프트 재작성 없이 **여러 스키마(UCO, STIX, MALOnt)**에서 동일하게 동작하는 CTI 지식그래프 파이프라인. 각 후보 엔티티는 스키마 트리를 **검색-내비게이트(search-and-navigate)**로 탐색해 클래스를 찾고, **SHACL** 제약을 통과한 클래스에만 인스턴스를 귀속한다.

## 2. 핵심 아이디어
- **스키마 무관**: 기존 CTI 추출 파이프라인은 스키마별로 프롬프트를 새로 짠다. ANCHOR는 프롬프트를 고정하고 스키마를 *네비게이트할 트리*로만 다루므로, UCO→STIX→MALOnt 전환이 설정 변경 수준에서 끝난다.
- **하이브리드 온톨로지 디스커버리(검색-내비게이트)**: 사전 어휘(별칭+클래스명)로 후보 시드 클래스를 찾고, 검증에 실패하면 `subClassOf` 사슬을 **위로 내비게이트**해 가장 가까운 조상에서 받아들인다. 각 인스턴스에는 디스커버리 경로(`path`)가 기록돼 감사 가능하다.
- **SHACL 형식 검증**: 클래스마다 구조 제약(예: `Vulnerability`는 `CVE-\d{4}-\d{4,}`, `IPAddress`는 IPv4 정규식)을 선언할 수 있다. 값이 제약을 통과하지 못하면 통과 가능한 가장 가까운 상위 클래스로 **강등(demotion)** 되고 `shacl_demoted=true`로 표시된다(잘못된 타입 부여 대신 보수적 처리).

## 3. 구축 과정 (단계별)
1. **텍스트 읽기** — `text.txt` 자유 본문을 문장 단위로 분리(`#` 주석 줄 무시; IP·CVE·해시 내부의 `.`은 보존).
2. **후보 추출** — LLM(또는 MOCK 휴리스틱)이 문장별 후보 토큰을 반환: PascalCase 엔티티명 + 지시자 값(IP, CVE id, 해시, 도메인)을 원문 그대로.
3. **하이브리드 온톨로지 디스커버리** — 각 후보에 대해 스키마의 어휘 카탈로그(별칭+클래스명)를 검색해 가장 구체적인 시드 클래스를 찾고, 값이 SHACL 제약을 통과할 때까지 `subClassOf` 사슬을 위로 이동한다. 전체 경로(seed → … → 수용 클래스)를 기록한다.
4. **그래프 조립** — 확정된 인스턴스는 `rdf:type`으로 타입화, 관련 클래스 계층이 자동 포함되며 CTI 관계(`deploys`, `exfiltrates`, `affects`, `hosts`, `exploits` …)는 두 엔티티 공출현 시 추가된다.
5. **출력** — `ontology.ttl`(OWL 클래스+subClassOf+개체 타입+ObjectProperty), `ontology.json`(Cytoscape 그래프; 각 엣지에 활성 `schema` 태그), `steps.json`(문장당 스냅샷, UI 디스커버리 재생용).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `text.txt` | 자유 CTI 텍스트(`.` `!` `?`로 문장 분리, IP·CVE·해시 내부 `.`은 보존) |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `rdfs:subClassOf`, 타입화 개체, `owl:ObjectProperty` 관계 |
| 출력 | `ontology.json` | 그래프; 인스턴스 노드에 `schema`·`value`·`shacl_demoted` 포함 |
| 출력 | `steps.json` | 문장별 스냅샷 — 단계 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 결정론적 후보 추출 + 결정론적 검색-내비게이트 + 결정론적 SHACL — 키 없이 안정적 골든 파일.
- `gemini`/`anthropic`/`hf_local`: LLM은 후보 토큰만 시드하고 내비게이트·SHACL은 결정론이라 그래프 형태는 안정. 키 없으면 자동 MOCK.
- **스키마 스위치**: `LLM_SCHEMA=uco|stix|malont` (기본 `uco`). 코드 경로는 동일하고 트리/별칭/SHACL만 바뀐다.

## 6. 사용해보기
1. `samples/text.txt`를 편집 — 잘 형성된 진술(`The IPAddress 198.51.100.7 hosts ...`)에 잘못 형성된 것(`CVE-ABCDE`는 강등 대상)을 섞어보자.
2. 사이트의 **Run** 버튼을 누르거나 `python pipeline.py samples runs/out --backend mock`.
3. 슬라이더로 단계 재생 — 문장마다 디스커버리가 보이고, 인스턴스가 타입 사슬과 함께 자라며, SHACL 강등은 `shacl_demoted=true` 인스턴스로 드러난다.
