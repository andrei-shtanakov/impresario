# TODO — impresario

## M0 — контракты и валидатор (done)

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
  robin-runtime (exempt = prograph-vault; 4-пунктный контракт семантики;
  канонический `_PLAN_EXEMPT` в коде) → `forconcept resume` (типизированный,
  traced) → итерация 3 (RP-503/CD-503, gap closed + answered_by) →
  **PP-101 `ready_for_business` v6**
- [ ] M2-хвост: промпт-харнесс оценщика/агентов (уйти от manual-v0)

## M4 — QG-5 и handoff

- [x] Typed QG-5 (сторона impresario): `impresario gate readiness` +
  `impresario gate decide` — Gate A/B, recycle/hold/kill/resume по таблице
  FSM, readiness = вычисляемое предусловие (blocked → гейт не открывается,
  ложное решение не создаётся), supersedes-цепочка, CAS + lock
- [x] **QG-5 ПРОЙДЕН 2026-08-12 (решения andrei)**: Gate A (GD-001,
  business_owner) → readiness ok → Gate B (GD-002, committee_chair) →
  **PP-101 `approved` v8** — первый approved ProductProposal, полный
  evidence-след Idea → approved. **Стадия 6 разблокирована**: реализация
  fail-loud + `_PLAN_EXEMPT` + постоянного раскрытия применённых и
  неизвестных exemptions в дайджесте robin-runtime (scope в CD-503)
- [ ] Входной контракт approved ProductProposal для steward/discovery
- [ ] dispatcher/Robin: read-only `product_proposal/gate_waiting` observation

## M3 — Kapelle battle-test

- [ ] Kapelle как execution backend цикла: вендорить пинованные копии
  contracts + reference runner как oracle (см. kapelle battle-testing трек;
  урок M2: различать terminal verdict и retryable-инфраструктуру)
- [x] Зарегистрировать репо в списке зеркал Robin — robin-runtime PR #44
  (после мержа: клонировать зеркало на VPS руками, CD этого не делает)
