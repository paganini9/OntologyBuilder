# Ontology Construction Method Library

연구 논문에 나온 **온톨로지 / 지식그래프 자동 구축 방법**을 하나씩 구현하고, 샘플 입력을 넣으면 온톨로지가 만들어지는 과정을 보여주는 KO/EN 웹사이트. 지속형 Loop Agent가 쉬운 방법부터 채워 나간다.

A KO/EN website that implements paper-based **ontology / knowledge-graph construction methods** one by one and visualizes the ontology being built from sample input. A continuous loop agent fills it in, easiest method first.

## Quick start
```powershell
python -m pip install -r requirements.txt
python -m pytest methods/cqbycq/tests/ -q
python scripts/build_site.py
python -m backend.app        # http://127.0.0.1:8000  ->  /ko/  /en/
```

## Status
방법 현황은 [`registry/methods.json`](registry/methods.json) 참조. 첫 구현: **CQbyCQ** (CQ→OWL). 운영 매뉴얼은 [`CLAUDE.md`](CLAUDE.md).

## Methods (현재 — 22개 모두 구현·게시)
사이트의 **개요·비교표(Overview)** 페이지에서 전체를 한눈에 비교할 수 있다(방법 추가 시 자동 반영).

| id | 방법 | 입력 | 패러다임 |
|---|---|---|---|
| cqbycq | CQbyCQ (CQ→OWL, memoryless) | CQ | 스키마-우선 |
| code-de-kg | CoDe-KG (coref+분해→트리플) | 텍스트 | 트리플-우선 |
| ontogenia | Ontogenia (메타인지 자기비평) | CQ | 스키마-우선 |
| peshevski-product-kg | 제품 KG (3-agent, 개체채우기) | 제품설명 | ontology-first |
| agentigraph | AGENTiGraph (대화형) | 발화 | 대화형 점진 |
| are-llms-effective-kgc | 계층적 추출 (L1→L2→L3) | 텍스트 | 트리플+계층 |
| ontology-grounded-wikidata | Wikidata grounding | CQ | 스키마+표준정렬 |
| karma | KARMA (다중에이전트 증축) | 텍스트+seed | enrichment |
| odke-plus | ODKE+ (5단계, 2차검증) | 엔티티+근거 | 트리플+검증 |
| itext2kg | iText2KG (증분, 의미중복제거) | 문서 | 증분 |
| autoschemakg | AutoSchemaKG (스키마 유도) | 텍스트 | 스키마 bottom-up |
| gptkb | GPTKB (LLM 내부지식 재귀) | 시드엔티티 | 모델자체 KB |
| se-standards-zeroshot | 표준 zero-shot 트리플 추출 | 표준텍스트 | 트리플-우선 |
| elenchus | Elenchus (prover-skeptic 대화) | 주장 | 변증법 |
| sac-kg | SAC-KG (Gen→Verify→Prune, multi-level) | 시드엔티티 | 트리플+검증·가지치기 |

> SAC-KG는 실제 구동에 GPU/파인튜닝이 필요해 결정론적 MOCK 단순화로 구현됨(실 GPU 구동은 향후 옵션).

## License / 출처
각 방법은 해당 논문(`registry/methods.json`의 paper 필드)에 근거. 구현 코드는 교육·연구 목적.
