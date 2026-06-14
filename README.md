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

## Methods (현재)
| rank | id | 방법 | 상태 |
|---|---|---|---|
| 1 | cqbycq | CQbyCQ (CQ→OWL, memoryless) | implemented |
| 2 | code-de-kg | CoDe-KG | queued |
| 3 | ontogenia | Ontogenia | queued |
| 4 | peshevski-product-kg | AI Agent Product KG (3 agents) | queued |
| … | … | KARMA, ODKE+, AGENTiGraph, SAC-KG … | queued |

## License / 출처
각 방법은 해당 논문(`registry/methods.json`의 paper 필드)에 근거. 구현 코드는 교육·연구 목적.
