# TODO — impresario

## M0 — контракты и валидатор (done)

- [ ] Решить судьбу GOV-003 на контент-адресуемых брифах @owner:github:andrei-shtanakov @id:gov003-briefs-exclusion — подключение к governance-гейту (PR #35, влит красным осознанно) дало 8 срабатываний в `pilot/briefs/*.yaml`: брифы цитируют политику `_cowork_output` в прозе, никаких путей не резолвят. **Штатный механизм исключений тут неприменим по построению:** гейт предлагает пометить строку `gov:allow-cowork` или файл `gov:allow-cowork-file`, но брифы несут `input_hash: sha256:…`, и правка текста ломает хеш — «починка» линтера испортила бы артефакт, ради целостности которого он заведён. Варианты: (1) исключения по путям в самом сканере зонтика (`--exclude` / вход `runtime-scan-exclude`) — правильный ответ, но требует нового тега и перепина всех каллеров; (2) `runtime-scan: false` — дёшево, теряет покрытие настоящего кода валидатора; (3) `strict: false`, гейт advisory. Вывод шире репозитория: **где есть хеш содержимого, исключение обязано жить снаружи файла**

- [x] 8 контрактов v1 + fixtures + канонический bundle `pp-001`
- [x] Детерминированный валидатор: schema + 14 кросс-проверок, JSON-отчёт,
  стабильные exit-коды
- [x] 51 тест; ruff, pyrefly

## M1 — Stage 4 pilot (next)

- [x] Входные артефакты: стратегия (`pilot/strategy.md`, G-1…G-5 +
  C-1…C-3), реестр стандартов (`pilot/standards.md`, STD-1…STD-9)
- [x] 8 реальных Idea-карточек (`pilot/ideas/`, валидны против idea/v1)
- [x] Детерминированный rank engine поверх нормализованных AxisAssessment
- [x] `impresario backlog rank` dry-run/`--apply` (CAS: input_hash +
  expected version + монотонный version + immutable run record
  `run-record/v1`)
- [x] Typed QG-4: `impresario backlog select <workspace> <idea>
  --expected-version N --actor <id> --reason <text>`
- [x] Оценочный прогон RUN-001 (8 assessments) + материализация RUN-002:
  `pilot/backlog.yaml` v1 (7 ранжировано, 1 pending, 0 excluded)
- [x] Friction log пилота (`pilot/friction-log.md`, 7 наблюдений)
- [x] **QG-4 закрыт 2026-08-12**: человек (andrei) выбрал IDEA-101
  (Robin full-coverage) — GD-001, backlog v2, карточка `selected`.
  **M1 exit-критерий выполнен**: выбранная идея воспроизводимо получена
  из versioned backlog + human decision evidence.

## M2 — reference forconcept loop

- [x] Reference runner цикла researcher ↔ creator: bounded итерации,
  durable ExchangeLog, idempotency (артефакты = состояние), crash/resume
  на каждой границе (побайтовое равенство с некрашившимся прогоном,
  включая trace), fail-closed на невалидном артефакте, детерминированный
  evaluator; `impresario forconcept init/run`
- [x] Живой прогон LOOP-101 (IDEA-101): 2 итерации → **честный
  `needs_human`** — открытый критичный вопрос (exempt-семантика зеркал)
  принадлежит владельцу robin-runtime; PP-101 v4, история полностью
  восстановима (`pilot/forconcept/pp-101/`)
- [x] **Human-развязка needs_human выполнена 2026-08-12**: решение владельца
  robin-runtime (первоначально «exempt = prograph-vault»; 4-пунктный
  контракт семантики; канонический `_PLAN_EXEMPT` в коде) → `forconcept
  resume` (типизированный, traced) → итерация 3 (RP-503/CD-503, gap
  closed + answered_by) → **PP-101 `ready_for_business` v6**.
  Exempt-часть решения позже скорректирована на стадии 6 — реестр пуст,
  запись 07-26 была отменена 07-30 (см. friction №16); контракт
  семантики и место реестра не менялись
- [x] M2-хвост, prioritizer-половина: промпт-харнесс оценщика (уйти от
  manual-v0) — `impresario assess render|ingest`, immutable
  EvaluationBrief, двухфазный идемпотентный ingest AxisAssessment.
  Спека: docs/superpowers/specs/2026-08-16-prioritizer-prompt-harness-design.md.
  Живой RUN-003 (переоценка pilot прошедшим харнессом) — отдельный
  человеческий акт после мержа
- [x] M2-хвост, researcher/creator-харнесс: промпт-харнесс агентов цикла
  (тот же переход от manual к воспроизводимому `prompt_version`, что и у
  оценщика) — `impresario forconcept brief|step`, immutable `StageBrief`
  (`stage-brief/v1`, идентичность — хеш девяти полей включая
  `prompt_hash`), `research-answer/v1` / `concept-answer/v1`, кросс-чеки
  `BRIEF_IDENTITY` / `ARTIFACT_BRIEF`. `step`: идемпотентность до
  freshness, freshness всех входов брифа, пре-валидация собранного
  артефакта, раннер — единственный исполнитель (граница `research:N` |
  `iteration:N`). Спека:
  docs/superpowers/specs/2026-08-16-loop-agent-harness-design.md. Живой
  прогон цикла живыми researcher/creator — отдельный человеческий акт
  после мержа

## M4 — QG-5 и handoff

- [x] Typed QG-5 (сторона impresario): `impresario gate readiness` +
  `impresario gate decide` — Gate A/B, recycle/hold/kill/resume по таблице
  FSM, readiness = вычисляемое предусловие (blocked → гейт не открывается,
  ложное решение не создаётся), supersedes-цепочка, CAS + lock
- [x] **QG-5 ПРОЙДЕН 2026-08-12 (решения andrei)**: Gate A (GD-001,
  business_owner) → readiness ok → Gate B (GD-002, committee_chair) →
  **PP-101 `approved` v8** — первый approved ProductProposal, полный
  evidence-след Idea → approved. **Стадия 6 РЕАЛИЗОВАНА 2026-08-12**:
  robin-runtime PR #45 — fail-loud на непрорезолвившихся именах,
  канонический `_PLAN_EXEMPT` (пустой: уточнение владельца — exemption
  vault отменён 2026-07-30, см. friction №16); coverage_hit раскрывает
  применённые и неизвестные exemptions всегда, включая полное покрытие
- [x] Входной контракт approved ProductProposal для steward/discovery —
  **ЗАКРЫТ 2026-08-12**: inbox steward#64 (slug `product-proposal-intake`,
  closed as completed) → steward#65 merged `5c702b3` — вендоринг обеих схем @
  `a2672a8` (PIN, copy-integrity + drift-вахта), `steward proposal-intake`
  с evidence-проверкой, живой смоук на PP-101 admit/reject; у steward
  остаётся их приёмка drift-вахты (`impresario-contract-drift-acceptance`)
- [x] dispatcher/Robin: read-only `product_proposal/gate_waiting` observation —
  фаза 1 доставлена и принята (dispatcher PR #132/#133); фаза 2
  (`needs_human`) доставлена (dispatcher#136 закрыт, их PR #137; parity —
  PR #138); **фаза 3 (`qg4_backlog` wait) ЗАКРЫТА 2026-08-17**:
  dispatcher#154 closed as completed — slug
  `product-proposal-qg4-backlog-wait`, реализация dispatcher PR #155
  (merged), все четыре условия готовности закрыты тестами на пинованной
  копии живого зеркала (пин `a9d11fa`), вендорены `ranked-backlog/v1` и
  `loop-resume-decision/v1` (5 контрактов под одним пином), строго
  read-only
- [x] **Сигнал `needs_human` законтрактован (loop-state/v1)**: `loop.state`
  промоутирован в контракт (projection, не журнал; identity
  `(loop_id, stop.iteration)`, freshness `stop.at`, terminal сохраняет
  stop), write-path validate-then-atomic-replace, resume — CAS +
  identity-dedup evidence, 5 кросс-чеков `LOOPSTATE_*`, бэкфилл pp-101 из
  immutable evidence; семантика — docs/semantics.md «Состояние цикла».
  Спека: docs/superpowers/specs/2026-08-12-loop-state-contract-design.md.
  **Влит 2026-08-12** (PR #12, merge `51e3103`, ревью Copilot отработано);
  follow-up выполнен: handoff dispatcher#136 подан

## PP-103 — третий полный прогон конвейера (IDEA-103)

- [x] **PP-103 approved 2026-08-17** — полный evidence-след за один день:
  QG-4 select IDEA-103 (GD-003, backlog v5; PR #28) → живой
  researcher/creator-цикл, 2 итерации → ready_for_business (PR #29) →
  Gate A (GD-001, business_owner; PR #30) → Gate B (GD-002,
  committee_chair; PR #31) → **approved v7**. Концепт: «последняя миля
  ADR-ECO-003b» (полный model-layer сервис отклонён по §1.5 и D5; hold
  отклонён). Бандл `pilot/forconcept/pp-103/`, 14 артефактов, валиден
- [x] arbiter: mcp-валидация agents.toml против user-config каталога + provider-swap смоук (acceptance (a)+(c) PP-103) @blocked_by:arbiter#72 @id:pp103-acceptance-arbiter
  **Доставлено 2026-08-17** (arbiter PR #73): `catalog_guard.rs` — сервер при
  старте валидирует `agents.toml` против user-config каталога
  (`$ATP_CATALOG` → XDG), fail-loud на невалидной паре (Check 5),
  warn-and-start при отсутствии каталога; смоук
  `orchestrator/tests/test_provider_swap_smoke.py` — retire X + promote Y
  только правкой каталога переключает `route_task` X → Y при байтово
  неизменном потребителе. Оба пункта arbiter закрыты
  (`@id:arbiter-mcp-catalog-loader`, `@id:approved-pp-103-catalog-last-mile`)
- [x] devtools: conformance трёх загрузчиков каталога под одним owner-путём, SSOT-фикстуры пином (acceptance (b) PP-103) @blocked_by:devtools#43 @id:pp103-acceptance-devtools
  **Доставлено 2026-08-17** (devtools PR #44/#45/#46, `@id:catalog-conformance-single-owner`):
  набор `contracts/catalog-conformance-fixtures/v1` опубликован с пином и
  manifest'ом; потребители подключены (maestro #188-цепочка, arbiter #74/#76),
  аддитивное расширение v1 закрыто (devtools#47), машиночитаемый словарь
  enum'ов — devtools#51. Acceptance (b) PP-103 выполнен

## M3 — Kapelle battle-test

- [x] **Kapelle как execution backend цикла — ЗАКРЫТ 2026-08-16**:
  вендоринг восьми контрактов @ merge `8082e53` (PIN + drift-вахта),
  resume-адаптер как чистый консьюмер LRD (kapelle TASK-106, PR #21),
  полная parity-матрица по golden-oracle (happy / needs-human / resume /
  invalid-artifact / crash; kapelle PR #22/#23) и fault-матрица всех
  шести обязательных точек (TASK-107, PR #25). Урок M2 подтвердился
  буквально: battle-test поймал 6+ реальных дефектов — сводка
  `pilot/friction-log.md` №17–21; семантический ruling (dangling
  supersedes = отказ потребления) закреплён в docs/semantics.md.
  Остаток за kapelle: reserve для review в конфиге контура (№21)
- [x] Зарегистрировать репо в списке зеркал Robin — robin-runtime PR #44
  (после мержа: клонировать зеркало на VPS руками, CD этого не делает)
- [x] **impresario#14 закрыт (сторона impresario)**: контракт
  `loop-resume-decision/v1` — immutable авторизация resume ожидания
  `(loop_id, iteration)`; producer/consumer-роли, single-writer lock на
  consume-переходе, кросс-чеки `LRD_*`, бэкфилл LRD-001 для pp-101.
  Спека: docs/superpowers/specs/2026-08-15-loop-resume-decision-design.md.
  **Влит 2026-08-16** (PR #16, merge `8082e53`, оба замечания Copilot
  отработаны); follow-up выполнен: ответ в impresario#14 с пин-коммитом
  `8082e53` и чек-листом консьюмера — вендоринг за kapelle
