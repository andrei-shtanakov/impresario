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
- [ ] **QG-4: человек выбирает идею** — `impresario backlog select pilot
  IDEA-… --expected-version 1 --actor … --reason …` (агент не выбирает)

## M2 — reference forconcept loop

- [ ] Reference runner цикла researcher ↔ creator (bounded 2–3 итерации,
  durable ExchangeLog, idempotency keys, crash/resume, golden traces)

## M3+ — интеграция экосистемы

- [ ] Kapelle как execution backend цикла (вендорит пинованные копии
  contracts; см. kapelle battle-testing трек)
- [ ] Входной контракт approved ProductProposal для steward/discovery
- [ ] dispatcher/Robin: read-only `product_proposal/gate_waiting` observation
- [x] Зарегистрировать репо в списке зеркал Robin — robin-runtime PR #44
  (после мержа: клонировать зеркало на VPS руками, CD этого не делает)
