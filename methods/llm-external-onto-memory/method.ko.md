# LLM External Ontology Memory — 이기종 소스 수집 + SHACL/OWL 생성-검증-교정

> 출처: *Automatic Ontology Construction Using LLMs as an External Layer of Memory, Verification, and Planning for Hybrid Intelligent Systems*, arXiv:2604.20795.

## 1. 한 줄 요약
**이기종 소스(문서·API·대화 로그)**를 하나의 RDF/OWL **온톨로지 메모리 계층**으로 합치는 자동 파이프라인이다. 개체 인식 → 관계 추출 → 정규화 → 트리플 생성 후, **SHACL/OWL 제약으로 검증**하되 *생성-검증-교정* 루프를 돌려 고치고(예: 비표준 날짜를 `xsd:date`로 정규화), 그래프를 **지속적으로 갱신**한다.

## 2. 핵심 아이디어
- **이기종 수집.** 소스 타입별로 처리: `document`/`dialogue`는 텍스트에서 NER/RE, `api`는 레코드 필드를 직접 트리플로. 모든 개체는 출처(provenance)를 보존한다.
- **외부 온톨로지 메모리.** 파라메트릭 지식·벡터 검색(RAG)만 의존하지 않고, 검증 가능한 구조적 KG(RDF/OWL)를 별도 메모리 계층으로 유지한다.
- **생성-검증-교정(3-결과).** 단순 거절만 하는 검증기와 달리, SHACL/OWL 검사는 **세 가지** 결과를 낸다 — *채택*, *교정*(고칠 수 있는 위반을 수리: 비-ISO 날짜 → `xsd:date`), *거절*(고칠 수 없는 위반: `worksIn` 값이 Department가 아님(sh:class), `@` 없는 이메일(sh:pattern)).
- **정규화 + 지속 갱신.** 표면형을 표준 개체로 정규화("Eng"/"Engineering" → 한 Department 노드)하고, 소스를 순서대로 처리하며 누적 그래프 위에서 검증한다(앞 소스에서 Person으로 인식된 Bob 때문에 뒤 대화의 "Carol works in Bob"이 sh:class로 거절됨).

## 3. 구축 과정 (단계별)
1. **소스 읽기** — `sources.json`(`{id, type, content}` 목록; content는 텍스트 또는 레코드 또는 발화 리스트).
2. **이기종 수집 + NER/RE** — 타입별 디스패치로 `(주어, 속성, 값)` 사실 추출.
3. **정규화** — 표면형 → 표준 개체(부서 별칭 병합); 기존 개체로 풀리면 그 타입을 사용.
4. **생성-검증-교정** — 객체 속성은 sh:class, 데이터 속성은 datatype/sh:pattern으로 검증; 고칠 수 있으면 교정 후 채택, 아니면 거절(감사 로그).
5. **출력** — `ontology.ttl`(클래스 + 객체/데이터 속성 + 검증된 ABox), `ontology.json`(Cytoscape; 개체 노드에 출처 + 채택된 데이터 속성), `steps.json`(소스당 스냅샷).

## 4. 입력 / 출력
| 구분 | 파일 | 비고 |
|------|------|------|
| 입력 | `sources.json` | `{"sources":[{"id","type":"document|api|dialogue","content":...}]}` |
| 출력 | `ontology.ttl` | OWL: `owl:Class`, `owl:ObjectProperty`/`owl:DatatypeProperty`, 타입화 개체 + 리터럴 |
| 출력 | `ontology.json` | 그래프; 개체 노드에 `provenance`·데이터 속성, `worksIn` 간선 |
| 출력 | `steps.json` | 소스별 스냅샷 — 지속 갱신 재생용 |

## 5. LLM 백엔드
- 기본 `mock`: 규칙 기반 NER/RE + 결정론적 정규화·검증·교정 — 안정적 골든 파일, 키 불필요.
- `gemini`/`anthropic`/`hf_local`: 텍스트 소스의 NER/RE를 LLM이 대체할 수 있으며, 정규화·검증·교정 단계는 결정론으로 유지. 키가 없으면 자동 MOCK 폴백.
- 범위 참고: 논문의 추론시 계획(Tower of Hanoi 등) 활용은 데모 범위 밖이며, 여기서는 **구축 + 검증 계층**에 집중한다.

## 6. 사용해 보기
1. `samples/sources.json`에서 `document`·`api`·`dialogue` 세 타입이 한 그래프로 합쳐지는 것을 본다.
2. `joinedOn`에 `2019/12/01` 같은 비-ISO 날짜를 넣어 **교정**되는지(`manifest.corrected`), `@` 없는 이메일이 **거절**되는지(`manifest.rejected`) 확인한다.
3. `worksIn` 값을 부서가 아닌 사람 이름으로 두어 **sh:class** 거절을 확인한다.
4. 실행: `python pipeline.py samples runs/out --backend mock` (또는 사이트의 **Run** 버튼).
