# 신규 방법 후보 — 2026-06-15 (exa 탐색)

라이브러리 9개 방법을 모두 구현한 뒤, exa 딥서치로 2025–2026 신규 LLM 온톨로지/KG 구축 방법을 탐색했다. registry의 9개와 중복되지 않는 후보만 추렸다.

> ⚠️ 신뢰도 메모: 3개 탐색 에이전트 중 1개는 exa 접근 실패(결과 없음), 일부 후보의 arXiv id(특히 2026년 후반 날짜)는 자동탐색 환각 가능성이 있어 **구현 전 method-analyst가 원문 재검증** 필요. `verified=true`는 이번 세션에서 WebFetch로 실재 확인한 것.

## 추천 후보 (구현 용이순)

| id | 방법 | arXiv | 코드 | 난이도 | 검증 | 차별점 |
|----|------|-------|:---:|:---:|:---:|--------|
| **itext2kg** | iText2KG — 증분 zero-shot KG 구축 | 2409.03284 (WISE 2024) | ✅ AuvaLab/itext2kg | 3 | ✅ | Document Distiller + 문서 증분 + 엔티티/관계 **의미 중복 제거** |
| **autoschemakg** | AutoSchemaKG — 동적 스키마 유도 | 2505.23628 (2025) | ✅ HKUST-KnowComp | 5 | ✅ | 스키마를 **데이터에서 bottom-up 유도**(사전 스키마 0) |
| gptkb | GPTKB — LLM 내부지식 KB화 | 2411.04920 (ACL 2025) | ✅ Knowledge-aware-AI | 4 | ⏳ | 입력 코퍼스 없이 **모델 자체**에서 시드 재귀 확장 |
| se-standards-zeroshot | 엔지니어링 표준 zero-shot 트리플 추출 | 2509.00140 (2025) | ❓ | 2 | ⏳ | **표준 문서(SPMM/STEP) 직접 대상** — 본 프로젝트 도메인 적합 |
| elenchus | Elenchus — prover-skeptic 대화 | 2603.06974(미검증) | ✅(추정) | 6 | ⏳ | 적대적 **2역할 대화**로 KB 수렴(Ontogenia 단일 자기비평과 구분) |

## 다음 동작
- **권장 1순위: iText2KG** — 검증됨, 코드 공개, 증분/의미중복제거로 기존 9개와 뚜렷이 구분, MOCK 결정론 구현 용이.
- 사용자가 `/impl-approve <id>` 로 승격하거나, 본 세션에서 바로 구현 진행.
- 나머지 후보는 재검증 후 순차 구현 가능.

## 자동탐색 시 제외(이미 구현)
SAC-KG, CoDe-KG, Ontogenia/CQbyCQ, Peshevski 제품KG, AGENTiGraph, Are-LLMs-Effective, Ontology-Grounded(Wikidata), KARMA, ODKE+.
