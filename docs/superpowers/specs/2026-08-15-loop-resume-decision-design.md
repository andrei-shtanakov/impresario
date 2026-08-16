# Дизайн: контракт loop-resume-decision/v1 — авторизация resume ожидания цикла

Дата: 2026-08-15. Статус: на ревью (закрывает impresario#14, блокер
resume-пути kapelle M3/S4).

## Проблема

Переход `needs_human → resumed` цикла researcher ↔ creator не имеет
producer-owned типизированного носителя авторизации. Сегодня resume
записывается внутренним trace-событием `resumed` — это evidence «что
произошло», а не авторизация, которую внешний execution backend (kapelle)
может проверить до перехода. GateDecision не подходит: он принадлежит FSM
ProductProposal, требует предшествующего `hold` того же гейта и не несёт
`(loop_id, iteration)` — не может однозначно авторизовать одно конкретное
ожидание. Kapelle корректно отказался донашивать GateDecision и держит
свой needs-human путь fail-closed до появления контракта (issue #14).

## Решение

Отдельный immutable контракт **loop-resume-decision/v1** (вариант A
issue #14): документ-авторизация возобновления одного конкретного
ожидания `(loop_id, iteration)`. Reference runner переходит на него
полностью (`forconcept resume` создаёт документ и сам его потребляет тем
же протоколом, что обязателен для kapelle) — раннер остаётся oracle
resume-пути. Исторический resume LOOP-101 бэкфиллится из immutable
evidence.

Отвергнутые альтернативы: расширение gate-decision/v1 (семантический
мисматч + сужение/изменение множества валидных документов без смены
`$id`); встраивание в loop-state/v1 (перезаписываемый projection не может
нести immutable авторизацию).

## Контракт

`contracts/loop-resume-decision/v1/schema.json`,
`$id: urn:impresario:contract:loop-resume-decision:v1`, домашний стиль
(`additionalProperties: false` на всех уровнях, строгие паттерны,
timestamp `…Z` через `$defs/timestamp`).

| Поле | Тип / паттерн | Примечание |
|---|---|---|
| `decision_id` | `^LRD-[0-9]{3,}$` | новая строка в грамматике ID |
| `subject` | объект `{loop_id, iteration}` | identity ожидания; оба обязательны |
| `subject.loop_id` | `^LOOP-[0-9]{3,}$` | |
| `subject.iteration` | integer ≥ 0 | 0-based, как в trace/loop-state |
| `new_max_iterations` | integer ≥ 1 | новый бюджет; авторизация самодостаточна, side-channel не нужен |
| `decided_by` | `{kind: enum ["human"], id}` | authority schema-enforced, как в GateDecision |
| `decided_at` | RFC 3339 `…Z` | |
| `reason` | string, minLength 1 | |
| `supersedes` | `^loop-resume-decision://LRD-[0-9]{3,}$`, опционально | исправление только новой записью; старая не правится |

Обязательны все поля, кроме `supersedes`.

`loop-resume-decision://` — девятая разрешимая ссылочная схема
(`_REF_RE` в checks, README контрактов): висячая ссылка `supersedes` в
bundle покрывается существующим `REF_DANGLING`.

Расположение: `decisions/` loop-workspace, рядом с gate-решениями
(прецедент — `pilot/forconcept/pp-101/decisions/`).

## Семантика active-set (supersedes)

Формально: **решение активно, если на него не ссылается семантически
допустимое ребро `supersedes` никакого другого schema-valid решения того
же bundle**. Допустимое ребро — разрешимое, той же identity, не
самоссылка и не часть цикла; недопустимое ребро — нарушение
(`REF_DANGLING` / `LRD_SUPERSEDES`) и **не участвует** в вычислении
active-set. Следствия:

- Самоссылка (`supersedes` на собственный `decision_id`) и циклы
  супер-цепочки — нарушение `LRD_SUPERSEDES`; такие рёбра не делают
  никого неактивным (иначе schema-valid самоссылка одновременно давала
  бы нарушение и убирала единственное решение из active-set).
- Несколько решений, перекрывающих один LRD, — допустимо на уровне
  active-set (перекрытый неактивен один раз); итоговое число активных
  вершин контролирует `LRD_DUP`.
- Цепочка A ← B ← C: активна только C; A и B перекрыты.
- Перекрытие имеет смысл только до потребления: после успешного resume
  CAS закрыт (`stop: null`), новые решения той же identity эффекта не
  имеют.

## Протокол resume (docs/semantics.md, «Состояние цикла»)

Роли различны: **producer** (reference CLI `forconcept resume` — авторит
решение по слову человека) находит существующий активный LRD либо создаёт
новый; **consumer** (kapelle и любой внешний бэкенд) решение только
принимает — отсутствие активного LRD для ожидания есть fail-closed отказ,
консьюмер решений не создаёт.

Порядок и атомарные границы producer-перехода (нормативные для reference
runner; шаг 3b — только producer):

1. Взять single-writer lock workspace на весь consume-переход
   (существующий O_EXCL-механизм `workspace.py`; concurrent writer —
   typed fail-fast).
2. Прочитать и провалидировать `loop.state` (fail-closed: невалидный
   state — типизированный отказ).
3. CAS-предусловие: `stop.verdict = needs_human`; identity ожидания —
   `(loop_id, stop.iteration)`. `failed` не resumable.
   3b. Найти активный LRD этой identity; если его нет —
   validate-then-atomic-write создать новый.
4. Перечитать состояние непосредственно перед потреблением: это
   обнаруживает изменение, случившееся до начала перехода, но само по
   себе гонку не закрывает — исключение конкурентной записи даёт lock
   шага 1 (single-writer на весь переход).
5. Идемпотентно записать trace-событие `resumed` с новым полем
   `decision_ref` (dedup по identity, как сейчас).
6. Atomic-replace `loop.state`: `stop: null`,
   `max_iterations = decision.new_max_iterations`.

Для внешнего backend/store настоящий атомарный CAS шагов 4–6 —
обязанность его хранилища (у kapelle — транзакция стора): файловый
протокол выше корректен при single-writer, который reference runner
обеспечивает lock-ом.

**Источник перехода — всегда записанный LRD, не аргументы вызова.**
Ретрай после частичного сбоя (LRD существует, state ещё `needs_human`)
обязан: найти единственное активное решение identity, проверить его,
дедуплицировать `resumed`, установить бюджет именно из
`decision.new_max_iterations` и сохранить исходные `decided_at`,
`decided_by`, `reason`. Повторный вызов с несовпадающими аргументами
(`--max-iterations`, `--reason`, `--actor`) — typed-отказ, но источником
перехода при совпадении остаётся существующий LRD. Иначе повторный вызов
создаёт расхождение между авторизацией, trace и состоянием.

Окно «LRD записан, state ещё `needs_human`» — валидное состояние bundle
(это граница между шагами 3 и 6), не ошибка.

Внешний бэкенд (kapelle) — чистый консьюмер: перед переходом проверяет
схему по пинованной копии, совпадение subject с активным ожиданием,
`new_max_iterations` строго больше текущего бюджета, активность решения.
Любой провал — как и полное отсутствие решения — отказ, ожидание
сохраняется (fail-closed).

## Кросс-чеки (bundle)

| Код | Проверка |
|-----|----------|
| `LRD_LOOP` | `subject.loop_id` резолвится ровно в один loop.state бандла |
| `LRD_BUDGET` | `new_max_iterations ≥ subject.iteration + 2` (needs_human на 0-based итерации *i* означает исчерпанный бюджет *i+1*; resume обязан дать больше) |
| `LRD_SUPERSEDES` | ссылка резолвится в решение той же identity; самоссылка и цикл цепочки — нарушение |
| `LRD_DUP` | больше одного активного решения на одну identity |

Порядок вычисления: сначала `LRD_SUPERSEDES` (валидность рёбер), затем
active-set, затем `LRD_DUP` по числу активных вершин.

## Раннер и CLI

- `resume_loop()` (`loop.py`) реализует протокол выше. Сигнатура CLI
  `forconcept resume <ws> --max-iterations N --actor <id> --reason <text>`
  не меняется; добавляется генерация `decision_id` (следующий свободный
  LRD-номер по файлам `decisions/`) и validate-then-atomic-write файла
  решения.
- Loader: ветвление по значению `decision_id` (`GD-` → gate-decision,
  `LRD-` → loop-resume-decision) — сейчас любой `decision_id`
  классифицируется как gate-decision (`loader.py`).

## Бэкфилл pp-101

Из immutable trace (событие `resumed`: by `andrei`, исторический reason,
`max_iterations: 3`) создаётся
`pilot/forconcept/pp-101/decisions/lrd-001.yaml`:
subject `(LOOP-101, 1)`, `new_max_iterations: 3`, `decided_by`
`{human, andrei}`, исходный reason дословно.

`decided_at`: historic trace-событие не несёт `at`. Канонический источник —
**`2026-08-12T04:01:21Z`**: `at` записи `research-pack://RP-503` (первого
post-resume артефакта) в immutable `exchange-log.yaml`. Именно operational
timestamp ExchangeLog, а не `produced_at: 2026-08-12T21:00:00Z` самого
RP-503 (авторское поле документа, расходится с operational-временем; уже
восстановленный loop.state использует ту же шкалу ExchangeLog). Провенанс
фиксируется в коммит-сообщении бэкфилла. Trace не трогаем (immutable);
бандл pp-101 обязан проходить валидатор с новыми чеками.

## Тесты

- Fixtures: ≥1 valid; invalid на каждый класс нарушения схемы (не-human
  actor, пустой reason, лишние поля, битые паттерны id/subject/supersedes,
  `new_max_iterations < 1`).
- Ломающий тест на каждый новый кросс-чек, включая самоссылку и цикл в
  `LRD_SUPERSEDES`, цепочку A ← B ← C для active-set, дубль активных в
  `LRD_DUP`.
- Протокольные тесты resume: happy path (LRD записан и потреблён, trace
  несёт `decision_ref`); ретрай после частичного сбоя — переход из
  существующего LRD, без дублей, с сохранением исходных
  `decided_at`/`decided_by`/`reason`; повторный вызов с несовпадающими
  аргументами — typed-отказ; отказ от невалидного/перекрытого решения —
  fail-closed, ожидание сохраняется; single-writer lock на переходе
  (конкурентный writer — typed fail-fast) и перечитывание состояния
  перед потреблением.
- CLI-тест `forconcept resume`; тест чистоты бандла pp-101 после
  бэкфилла.

## Вне скоупа

- Изменение loop-state/v1 и gate-decision/v1 — не требуется.
- Retryable-vs-terminal семантика инфраструктурных ошибок бэкенда
  (урок friction №11) — отдельный трек M3, не этот контракт.
- Kapelle-сторона (resume-policy adapter, вендоринг новой схемы) — их
  репо; после мержа отвечаем в issue #14 пин-коммитом.

## Закрытие

После мержа (человеком): ответ в impresario#14 — пин-коммит для
вендоринга, ссылка на семантику, чек-лист консьюмера; обновление TODO.md
(M3-прогресс).
