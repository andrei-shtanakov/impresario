# Семантика product-governance объектов

Самодостаточное описание доменной семантики, которую кодируют
[contracts v1](../contracts/README.md). Это SSOT для машинных контрактов;
методологический контекст развивается в отдельном upstream-репозитории
(приватный, вне этой экосистемы) и сюда не копируется.

Контур целиком:

```text
Signal / Idea
    │  скоринг по осям (AxisAssessment)
    ▼
RankedBacklog ──► QG-4: human select
    │
    ▼
ProductProposal ◄── цикл researcher ↔ creator
    │                (ResearchPack / ConceptDraft / ExchangeLog)
    │  Gate A (qg5_business): одобрение бизнеса
    │  Gate B (qg5_committee): продуктовый комитет
    ▼
approved ──► инженерный SDLC (внешний потребитель)
```

## Роли: author / evaluator / authority

- Агент (LLM) извлекает сведения, предлагает assessment, собирает драфты.
- Детерминированный инструмент (валидатор) владеет допустимостью объекта
  и перехода.
- Человек принимает authority-решения (QG-4 select, Gate A/B). Агент не
  может записать решение гейта: `decided_by.kind = human` — schema-enforced.

## Idea

Карточка идеи — единый формат для всех источников (`market`, `customer`,
`hd`, `competitor`, `strategy`, `rd`, `internal`, `other`). Обязательный
минимум: `title`, `date`, `source`, `priority`, `business_attractiveness`,
`status`, гипотеза. Статусы: `new → under_review →
selected | parked | rejected | merged`.

`business_attractiveness` — **pre-triage** поле (черновая сила бизнес-кейса);
в scoring policy не входит: не ось и не вес.

## Скоринг: AxisAssessment

Три оси — `fit_strategy`, `fit_market`, `fit_standards`, шкала 1…5 либо
`unknown`. Правила:

- Оценка без опоры на входные артефакты запрещена: честный `unknown`
  вместо выдуманного балла. `unknown` ≠ 0 и ≠ clean.
- Хотя бы одна ось `unknown` → итоговый score `unknown`; идея не вытесняет
  полностью оценённых кандидатов.
- **Score и blocker — разные оси:** низкий балл ранжирует, доказанный
  формальный запрет исключает. `strategy_blocker` / `standards_blocker`
  требуют evidence-ссылку `*_blocker_ref` (schema-enforced); blocker без
  evidence недопустим.
- Provenance обязателен: `run_id`, `input_hash`, `policy_version`,
  evaluator (`kind: agent` требует `model` + `prompt_version`).

**Детерминизм:** при одинаковых нормализованных assessments, той же
policy и том же составе идей детерминированный пересчёт ранга даёт тот же
RankedBacklog. Новый LLM-вызов — новый evaluation run со своим `run_id`,
provenance и объяснимой дельтой; побайтовая воспроизводимость баллов не
обещается.

## RankedBacklog

Версионируемый бизнес-объект (`version` монотонно растёт). Ранг «только в
чате» не существует для гейта: результат скоринга материализуется. Три
корзины:

- `items[]` — полностью оценённые позиции; `rank` уникален; blocker-флаги
  здесь всегда false;
- `pending_unknown[]` — идеи с `unknown`-осями + `missing_inputs`;
- `excluded[]` — доказанный blocker (с `*_blocker_ref`) или дефект карточки;
  позиция видима, но без `rank`.

Полнота состава: каждая допущенная в скоринг идея оказывается ровно в одной
из корзин — не «теряется».

## QG-4: human select

Вход — актуальная версия RankedBacklog. Агент предлагает, человек решает.
Исходы (GateDecision, `gate_id: qg4_backlog`): `select` (+
`selected_idea_ref`), `defer`, `park`, `reject`.

## ProductProposal FSM (SSOT)

Статусы: `draft`, `in_iteration`, `ready_for_business`, `business_approved`,
`approved` (терминальный успех), `on_hold`, `killed` (терминальный).

| Из | В | Триггер |
|----|---|---------|
| `draft` | `in_iteration` | старт цикла researcher ↔ creator |
| `in_iteration` | `ready_for_business` | условия выхода цикла |
| `in_iteration` | `business_approved` | условия выхода **и** действующий Gate A approve, правки не требуют повторного Gate A |
| `in_iteration` | `on_hold` \| `killed` | стоп-решение человека (запись) |
| `ready_for_business` | `business_approved` | GateDecision(`qg5_business`, approve) |
| `ready_for_business` \| `business_approved` | `in_iteration` | recycle + `return_to` |
| `ready_for_business` \| `business_approved` | `on_hold` \| `killed` | hold \| kill |
| `business_approved` | `approved` | readiness = ok **и** GateDecision(`qg5_committee`, approve) |
| `on_hold` | `in_iteration` \| `ready_for_business` \| `business_approved` | resume + `return_to` |

Ключевые инварианты:

- `ready_for_committee` **не статус**: готовность к Gate B вычисляется
  (readiness: `ok | blocked` + причины) и нигде не персистится; при
  `blocked` Gate B не открывается и решение не создаётся.
- `recycle` / `hold` / `kill` / `resume` — исходы решений, не статусы:
  статус после решения определяет таблица переходов.
- `approved` недостижим без **двух активных** approve-записей (Gate A и
  Gate B); Gate B не раньше Gate A.
- State / decision / computed readiness — три разные оси.

## GateDecision

Immutable запись решения. Поля: `gate_id` (`qg4_backlog` | `qg5_business` |
`qg5_committee` | `process`), `subject` (kind/ref/version), `decision`,
`decided_by` (человек), `decided_at`, `reason`; для `recycle` —
`required_changes[]` + `return_to`; для `resume` — `return_to`; для `hold` —
опционально `review_after`.

Исправление/перекрытие — только **новой** записью со ссылкой `supersedes`
на перекрываемую; старая запись не правится (append-only supersession).
Перекрытое approve перестаёт быть evidence для FSM. `resume` пишет тот же
гейт, что выдал `hold`, и только после него по времени. `gate_id: process` —
соглашение для стоп-решений до гейтов (из `in_iteration`).

## Цикл researcher ↔ creator

Обмен только через материализованные артефакты:

- **ResearchPack** (выход researcher, на итерацию): findings с уликами —
  confidence выше `unknown` требует `source_ref`; constraints; gaps с
  флагом `blocks_approval`; brief для креатора; запросы к креатору.
- **ConceptDraft** (выход creator, на итерацию): обязан ссылаться на
  ResearchPack (`based_on_research`, актуальный — не устаревший);
  альтернативы (≥3 или `single_path_justification`); assumptions с флагом
  `blocks_approval` — закрываются `answered_by` (ссылка на ResearchPack)
  или `human_waiver`; запросы к исследователю; `proposal_delta`.
- **ExchangeLog**: запись каждой передачи; итерации монотонны; без журнала
  цикл нетрассируем.

К гейтам не проходят открытые критичные assumptions/gaps: readiness
проверяет их по актуальным (принадлежащим той же идее и proposal)
артефактам из `refs`.

## Классы enforcement

| Класс | Значение |
|-------|----------|
| `schema-enforced` | Нарушение невозможно записать как валидный объект |
| `tool-enforced` | Валидатор отклоняет объект или переход |
| `human/process-enforced` | Опирается на review и процессную дисциплину |
| `planned` | Механизм ещё не реализован; это долг, не гарантия |

Что валидатор покрывает сейчас — таблица кодов в
[README](../README.md#коды-проверок).
