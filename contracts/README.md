# Контракты product-governance v1

Версионированные контракты product-governance (стадии отбора идеи и
форконцепта), fixtures и детерминированный валидатор (пакет
[impresario](../src/impresario/)). Доменная семантика — самодостаточно в
[docs/semantics.md](../docs/semantics.md).

| Контракт | Объект |
|----------|--------|
| [idea/v1](./idea/v1/schema.json) | Idea |
| [axis-assessment/v1](./axis-assessment/v1/schema.json) | AxisAssessment |
| [ranked-backlog/v1](./ranked-backlog/v1/schema.json) | RankedBacklog |
| [research-pack/v1](./research-pack/v1/schema.json) | ResearchPack |
| [concept-draft/v1](./concept-draft/v1/schema.json) | ConceptDraft |
| [exchange-log/v1](./exchange-log/v1/schema.json) | ExchangeLog |
| [product-proposal/v1](./product-proposal/v1/schema.json) | ProductProposal (SSOT FSM) |
| [gate-decision/v1](./gate-decision/v1/schema.json) | GateDecision |
| [run-record/v1](./run-record/v1/schema.json) | RunRecord (immutable запись материализации бэклога) |
| [loop-state/v1](./loop-state/v1/schema.json) | LoopState (текущий projection состояния цикла researcher ↔ creator; JSON-файл `loop.state`, сигнал `needs_human` — docs/semantics.md) |

## Канонические идентификаторы схем

`$id` каждой схемы: `urn:impresario:contract:<name>:v1` (например,
`urn:impresario:contract:idea:v1`). Идентификатор стабилен; правка схемы без смены
идентификатора допустима только без сужения множества валидных документов.

## Грамматика ID и ссылок

Стабильные ID объектов (регистр значим):

| Объект | ID | Пример |
|--------|-----|--------|
| Idea | `IDEA-[0-9]{3,}` | `IDEA-001` |
| AxisAssessment | `ASMT-[0-9]{3,}` | `ASMT-001` |
| RankedBacklog | `BL-[a-z0-9][a-z0-9-]*` | `BL-portfolio` |
| ResearchPack | `RP-[0-9]{3,}` | `RP-001` |
| ConceptDraft | `CD-[0-9]{3,}` | `CD-001` |
| ExchangeLog | `XL-[0-9]{3,}` | `XL-001` |
| ProductProposal | `PP-[0-9]{3,}` | `PP-001` |
| GateDecision | `GD-[0-9]{3,}` | `GD-001` |
| Evaluation run | `RUN-[0-9]{3,}` | `RUN-001` |
| Loop | `LOOP-[0-9]{3,}` | `LOOP-101` |

Внутренние ссылки — URI со схемой по типу объекта (восемь схем по числу
контрактов): `idea://IDEA-001`, `assessment://ASMT-001`,
`backlog://BL-portfolio`, `research-pack://RP-001`, `concept-draft://CD-001`,
`exchange-log://XL-001`, `proposal://PP-001`, `gate-decision://GD-001`.

Валидатор проверяет разрешимость внутренних ссылок в пределах bundle
(fail-closed: висячая ссылка известной схемы — ошибка). Прогон
материализации записывается документом `run-record/v1`, но `run://` не
является ссылочной схемой: `RUN-…` встречается только в полях
`run_id` / `last_run_id` (обычный ID). `loop://` также не является ссылочной
схемой — `loop_id` встречается только в `loop.state`. Внешние evidence-ссылки
(`strategy://…`, `standards://…`, `https://…`, произвольные URI) в v1 не
разрешаются и не считаются ошибкой.

## Версии и миграции

- `version` объекта — целое ≥ 1, монотонно растёт при каждой материализации.
- Версия контракта — сегмент пути (`…/v1`). Ломающее изменение схемы = новый
  каталог `v2` + migration note рядом; `v1` замораживается, не переписывается.
- Потребители вне репо получают **пинованную копию** контракта (вендоринг), не
  ссылку на живой файл.

## Actor и provenance

Каждый производимый агентом артефакт несёт `produced_by`
(`kind: agent | human`; для `agent` обязательны `model` и `prompt_version`).
Authority-решения (GateDecision) принимает только человек:
`decided_by.kind` — константа `human` (schema-enforced).

## Семантика времени

Все таймстемпы — RFC 3339 / ISO 8601 в UTC с суффиксом `Z`
(`2026-08-12T10:00:00Z`). `date` без времени — `YYYY-MM-DD`.

## Fixtures

У каждого контракта: `fixtures/valid/` — минимум один валидный документ;
`fixtures/invalid/` — документы, ломающие ключевые инварианты (по одному на
инвариант; имя файла называет нарушение). Канонический сквозной пример bundle —
[examples/pp-001/](./examples/pp-001/): полная цепочка
Idea → AxisAssessment → RankedBacklog → QG-4 → RP/CD/XL → ProductProposal →
Gate A → Gate B → `approved`.

## Каноническая сериализация

Носитель документов — YAML или JSON (одна модель данных). Побайтовая
воспроизводимость в v1 не требуется; если она понадобится (подписи, хэши
объектов целиком), правила canonical serialization войдут в v2 отдельным
решением. `input_hash` считается по нормализованным входам процедуры,
формирующей артефакт, и фиксируется в самом артефакте.

## Классы enforcement

Схемы дают `schema-enforced` уровень; кросс-объектные инварианты (уникальность
`rank`, порядок гейтов, FSM-переходы, разрешимость ссылок, открытые критичные
assumptions) — `tool-enforced` валидатором. Полный список проверок — в
[корневом README](../README.md).
