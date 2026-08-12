# Дизайн: контракт loop-state/v1 — сигнал `needs_human` для внешних наблюдателей

Дата: 2026-08-12. Статус: утверждён (развязка TODO M4, блокер фазы 2
dispatcher#129).

## Проблема

Вердикт `needs_human` цикла researcher ↔ creator живёт в `loop.state` —
внутреннем состоянии reference-раннера, не законтрактованном артефакте.
Внешний наблюдатель (dispatcher, фаза 2 issue #129) не может надёжно
показать «какие циклы ждут человека»: формат файла ничем не обещан.

## Решение

Промоутировать `loop.state` в версионированный контракт **loop-state/v1**.
Файл — **текущий projection состояния цикла**, не журнал: история
(`needs_human` → resume) остаётся в immutable evidence (ExchangeLog, trace,
run records). Отдельный `loop-event/v1` сознательно **не** вводится —
до появления реального потребителя аудита/replay (YAGNI).

Обоснование выбора (vs типизированное emitted-событие): наблюдателю нужен
текущий уровень состояния, а не восстановление state через replay журнала;
контракт состояния проще валидировать fail-closed и дешевле читать на
каждый запрос; resume атомарно снимает ожидание в том же файле — нет
двойной записи и риска расхождения.

## Контракт

`contracts/loop-state/v1/schema.json`,
`$id: urn:impresario:contract:loop-state:v1`, домашний стиль
(`additionalProperties: false`, строгие паттерны, timestamp `…Z`).

Файл: имя ровно `loop.state`, JSON (не произвольный YAML), UTF-8, корень
loop-workspace.

| Поле | Тип / паттерн | Примечание |
|---|---|---|
| `loop_id` | `^LOOP-[0-9]{3,}$` | новая строка в грамматике ID |
| `idea_ref` | `^idea://IDEA-[0-9]{3,}$` | |
| `idea_input_hash` | `^sha256:[0-9a-f]{64}$` | пин входа цикла |
| `proposal_id` | `^PP-[0-9]{3,}$` | однозначная связь с proposal |
| `exchange_log_id` | `^XL-[0-9]{3,}$` | |
| `max_iterations` | integer ≥ 1 | |
| `stop` | `null` \| объект | см. ниже |

`stop` (все поля required):

| Поле | Тип | Примечание |
|---|---|---|
| `verdict` | enum `ready_for_business` \| `needs_human` \| `failed` | `paused` в файл не пишется |
| `reason` | string, `minLength: 1` | обязателен и непуст |
| `iteration` | integer ≥ 0 | **новое поле**; identity ожидания |
| `at` | timestamp `…Z` | **новое поле**; freshness |

`loop://` ссылочной схемой не становится; `run://`-прецедент.

## Семантика (секция в docs/semantics.md)

- `stop: null` — активного ожидания нет (цикл не завершён: до первого
  терминального вердикта или после resume).
- `stop.verdict == "needs_human"` — активное ожидание человека.
- Identity ожидания: `(loop_id, stop.iteration)`. Freshness: `stop.at`.
- **Terminal projection сохраняет stop**: `ready_for_business` и `failed`
  никогда не откатываются в `null`; единственный легальный переход
  `stop != null → null` — resume из `needs_human` (tool-enforced
  предусловием resume; `failed` не resumable, fail-closed).
- Запись файла — **validate-then-atomic-replace** (tool-enforced):
  невалидное состояние не пишется, файл остаётся в последнем
  консистентном виде.
- Наблюдатель: строго read-only; вендорит пиненую копию схемы;
  **неизвестная версия / невалидный / нечитаемый файл = unknown, а не
  «ожиданий нет»** (fail-closed, класс бага «нечитаемое выглядит как
  чистое»).

## Протокол resume (точный порядок)

1. Предусловие (CAS): текущий `stop.verdict == "needs_human"`, иначе
   `LoopError` — повторный resume после успеха падает явно.
2. Записать immutable evidence возобновления: trace-событие `resumed`
   (`by`, `reason`, `from_verdict`, `max_iterations`, **`iteration`** —
   identity снятого ожидания). Байтовый dedup trace делает повтор
   идемпотентным.
3. Построить новое состояние со `stop: null` и расширенным бюджетом,
   провалидировать против loop-state/v1.
4. Atomic-replace `loop.state`.
5. Только затем продолжать цикл (`forconcept run`).

Отказ на шаге 2–4 оставляет старое ожидание активным; повторный resume с
теми же аргументами идемпотентен (evidence дедуплицируется, replace
доводится).

## Раннер и внедрение зависимостей

- Все три места записи stop (`fail()`, READY, NEEDS_HUMAN) добавляют
  `iteration` и `at: now_iso` (аддитивно).
- `_write_state` → validate-then-atomic-replace против loop-state/v1;
  невалидное — `LoopError`, файл не тронут.
- `contracts_dir` разрешается **один раз в CLI** (`--contracts` или
  `find_contracts_dir(cwd)`) и передаётся явным параметром в
  `init_loop` / `resume_loop` / `run_loop`. Публичные вызыватели передают
  его явно; повторного поиска в глубине write-path нет.

## Загрузчик и классификация

- Файл с именем ровно `loop.state` классифицируется **по имени**: парсится
  как JSON, kind = `loop-state`, без эвристического fallback в другой kind.
- `collect_doc_paths` включает `loop.state` в обход бандла (сейчас
  отсекается по суффиксу).
- `CONTRACT_KINDS` + `loop-state`; в `detect_kind` — ветка `loop_id` →
  `loop-state` (для fixtures и явных путей; коллизий полей нет).

## Кросс-чеки (identity, не только форма)

Новые коды валидатора (действуют при наличии соседей в бандле;
одиночный файл — schema-only):

| Проверка | Суть |
|---|---|
| `LOOPSTATE_PROPOSAL` | `proposal_id` совпадает ровно с одним proposal бандла |
| `LOOPSTATE_IDEA_REF` | `idea_ref` == `idea_ref` этого proposal |
| `LOOPSTATE_IDEA_HASH` | `idea_input_hash` == canonical hash idea-документа бандла |
| `LOOPSTATE_XLOG` | `exchange_log_id` резолвится в ExchangeLog бандла |
| `LOOPSTATE_ITERATION` | `stop.iteration < max_iterations` (итерации 0-based) |

«Terminal сохраняет stop» машинно не проверяется без replay — enforcement
на write-path (предусловие resume), класс tool-enforced.

## Бэкфилл pp-101

`pilot/forconcept/pp-101/loop.state` не имеет `stop.iteration`/`stop.at`.
Значения восстановлены из **immutable evidence**, без оценок:

- `stop.iteration: 2` — trace: вердикт `ready_for_business` на iteration 2.
- `stop.at: "2026-08-12T04:01:21Z"` — ExchangeLog-записи iteration 2 несут
  `at: 2026-08-12T04:01:21Z`; раннер использует один `now_iso` на всю
  инвокацию, stop записан той же инвокацией ⇒ время точное.

Бэкфилл легален: loop-state — projection, не immutable evidence; история
в trace/ExchangeLog не тронута. Migration-evidence оговорка не требуется —
значения точные, не приближённые.

## Тесты

- Fixtures valid: running (`stop: null`), needs_human, ready, failed;
  invalid: пустой `reason`, отсутствующий `at`, неизвестный `verdict`,
  лишнее поле, битый `idea_input_hash`.
- Раннер: stop-запись валидна против схемы; resume следует протоколу
  (evidence раньше replace, CAS-предусловие, идемпотентный повтор);
  запись невалидного состояния отклоняется fail-closed.
- Кросс-чеки: позитив на pp-101, негатив мутациями (чужой proposal_id,
  расходящийся hash, `stop.iteration >= max_iterations`).
- Golden crash/resume тесты обновляются (в trace `resumed` добавилось
  `iteration`; `now_iso` в тестах фиксирован — детерминизм сохраняется).
- `impresario validate` бандла pp-101 зелёный после бэкфилла.

## Хвосты

- `contracts/README.md`: строка таблицы, `LOOP-[0-9]{3,}` в грамматике ID,
  оговорка «JSON-файл `loop.state`, не YAML-документ».
- `TODO.md`: пункт M4 «законтрактовать needs_human» закрывается.
- Follow-up (вне этого шага): handoff dispatcher — «фаза 2 разблокирована,
  вендорите loop-state/v1 @ <commit>» (комментарий в #129 или новый
  inbox-issue).

## Вне скоупа

- `loop-event/v1` (аудит/replay журналом) — до реального потребителя.
- Промоушен trace.jsonl в контракт — trace остаётся внутренним.
- Какие каталоги сканировать — решение владельца dispatcher (фаза 2).
