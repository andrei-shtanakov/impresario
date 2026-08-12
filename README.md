# impresario

Product-governance контур экосистемы: машинные контракты пути
`Idea → RankedBacklog → ProductProposal → human gates → approved` и
детерминированный инструмент их enforcement. Импресарио решает, какие
постановки ставить и финансировать, — этот репозиторий владеет объектами
и правилами таких решений, но сами authority-решения принимает человек.

- **Контракты**: [contracts/](./contracts/README.md) — 8 схем v1
  (JSON Schema 2020-12, `urn:impresario:contract:<name>:v1`), валидные и
  невалидные fixtures, канонический сквозной пример
  [contracts/examples/pp-001](./contracts/examples/pp-001/).
- **Семантика**: [docs/semantics.md](./docs/semantics.md) — FSM
  ProductProposal, GateDecision, скоринг, цикл researcher ↔ creator.
- **Валидатор**: пакет `impresario` — LLM авторит содержание, валидатор
  владеет допустимостью объекта и перехода.

Методология-upstream живёт в отдельном приватном репозитории и здесь не
вендорится; этот репо самодостаточен и является SSOT машинных контрактов.
Потребители экосистемы получают **пинованные копии** контрактов
(вендоринг), не ссылки на живые файлы.

## Быстрый старт

```bash
uv sync
uv run impresario validate contracts/examples/pp-001   # bundle
uv run impresario validate path/to/artifact.yaml       # schema-only
uv run pytest
```

Каталог контрактов ищется вверх от cwd; переопределяется `--contracts DIR`.

## Stage 4: rank и typed QG-4

Рабочая директория (workspace): `ideas/`, `assessments/`, `backlog.yaml`,
`runs/`, `decisions/` (живой пример — [pilot/](./pilot/README.md)).

```bash
# канонический input_hash карточки — для авторства assessments
uv run impresario hash pilot/ideas/*.yaml

# детерминированный ранг: dry-run печатает предлагаемый бэклог, ничего не пишет
uv run impresario backlog rank pilot --backlog-id BL-ecosystem

# apply: CAS-материализация + immutable run record
uv run impresario backlog rank pilot --backlog-id BL-ecosystem --apply \
    --actor <id> [--expected-version N]   # N обязателен, если бэклог уже есть

# typed QG-4: человек выбирает идею; пишется immutable GateDecision,
# версия бэклога растёт, карточка получает status: selected
uv run impresario backlog select pilot IDEA-101 \
    --expected-version 1 --actor <id> --reason "<почему>"
```

Гарантии apply/select: schema всех входов; `input_hash` каждого assessment
равен текущему хэшу карточки (`STALE_INPUT` иначе); `--expected-version`
совпадает с текущей (`VERSION_CONFLICT` иначе); select дополнительно
сверяет выбираемую карточку с run record текущей версии бэклога
(`STALE_INPUT` / `RUN_RECORD_MISSING`) и пре-флайтит правку карточки до
первой записи; single-writer lock; validate-then-atomic-replace;
монотонная версия; собственные выходы проходят те же контракты.
Канонический хэш считается по распарсенному документу: комментарии в YAML
его не меняют, смысловые правки — меняют. Детерминизм (P-07) — у rank
engine от нормализованных assessments; новый LLM-вызов = новый
evaluation run.

## Режимы валидации

- **Файлы** — schema-only: каждый документ против схемы своего контракта
  (тип определяется по `assessment_id` / `proposal_id` / `decision_id` /
  префиксу `id`).
- **Каталог (bundle)** — schema + кросс-объектные проверки по всем
  документам (`--bundle` форсирует для списка файлов).

## Forconcept: reference runner цикла researcher ↔ creator

Эталон семантики bounded-цикла (M2); oracle для будущих execution-бэкендов.
Durable-артефакты — единственное состояние: завершённость стадии выводится
из файлов на диске, поэтому crash/resume на любой границе не даёт ни
дублей, ни потерь (проверено побайтовым сравнением с некрашившимся
прогоном, включая trace).

```bash
uv run impresario forconcept init <ws> --idea-file <selected-idea.yaml> \
    --loop-id LOOP-101 --proposal-id PP-101 --exchange-log-id XL-101 \
    --max-iterations 2

uv run impresario forconcept run <ws> --script <file>.script \
    [--stop-after research:0|concept:0|apply:0|evaluate:0|...]
```

Стадии итерации: research → validate → concept → validate → apply delta →
evaluate. Детерминированный evaluator: нет открытых критичных
assumptions/gaps и запросов → `ready_for_business`; есть и остались
итерации → `continue`; итерации кончились → `needs_human`; невалидный
артефакт — не персистится, вердикт `failed` (fail-closed, exit 1).
Вердикт терминален: повторный `run` — no-op с тем же ответом. Агенты —
интерфейс; референс — `ScriptedAgent` (реплей законтрактованных
артефактов, он же формат golden-фикстур). Живой пример —
[pilot/forconcept/](./pilot/forconcept/pp-101/), скрипт —
`pp-101.script`.

## Коды проверок

| Код | Проверка |
|-----|----------|
| `USAGE` | Ошибка вызова: путь не существует / contracts не найден |
| `LOAD` | Документ не читается (в т.ч. битый YAML/JSON) или тип контракта не определяется |
| `SCHEMA` | Нарушение JSON Schema контракта (включая format-проверку дат RFC 3339) |
| `REF_DANGLING` | Внутренняя ссылка известной схемы не разрешается в bundle |
| `REF_FOREIGN` | Артефакт в `refs` proposal принадлежит другой идее/proposal |
| `BL_RANK_DUP` | Дубль `rank` среди полностью оценённых позиций бэклога |
| `FSM_EVIDENCE` | Статус proposal не подтверждён активными (не перекрытыми через `supersedes`) decision records |
| `GATE_ORDER` | Решение Gate B без предшествующего по времени approve Gate A |
| `GD_VERSION_AHEAD` | Решение ссылается на версию proposal больше текущей |
| `RESUME_WITHOUT_HOLD` | `resume` без предшествующего по времени активного `hold` того же гейта |
| `ASSUMPTION_OPEN` | Критичное допущение открыто при статусе ≥ `ready_for_business` |
| `GAP_OPEN` | Критичный research-gap открыт при статусе ≥ `ready_for_business` |
| `RP_ITERATION_MISMATCH` | `based_on_research.iteration` не совпадает с итерацией указанного ResearchPack |
| `RP_STALE` | ConceptDraft ссылается на устаревший ResearchPack при доступном более свежем |
| `ALTERNATIVES_MISSING` | Меньше 3 альтернатив без `single_path_justification` при статусе ≥ `ready_for_business` |
| `XLOG_ORDER` | Итерации ExchangeLog не монотонны |

Отчёт — JSON в stdout (`ok`, `checked`, `errors[]`) при любом исходе.
Сравнение времён решений — парсинг RFC 3339, не лексикографика.

## Exit codes (стабильные)

| Код | Значение |
|-----|----------|
| 0 | Нарушений нет |
| 1 | Найдены нарушения (список в отчёте) |
| 2 | Ошибка использования (`USAGE` в отчёте) |

## Разработка

```bash
uv run pytest          # 51 тест: fixtures + кросс-чеки + CLI
uv run ruff format . && uv run ruff check .
uv run pyrefly check
```

Инварианты покрытия: каждый контракт имеет ≥1 валидную и ≥1 невалидную
fixture; канонический bundle проходит чисто; каждый кросс-чек имеет
ломающий тест.

## Границы

- Этот репо **не** оркестратор и не инженерный SDLC: исполняемые задачи,
  DAG-и, evaluation и деплой — у других инструментов экосистемы.
- Валидатор не принимает решений: authority у человека, записи решений
  immutable (GateDecision).
- Очередь развития — [TODO.md](./TODO.md).
