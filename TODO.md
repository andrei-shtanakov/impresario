# TODO — impresario

## M0 — контракты и валидатор (done)

- [x] 8 контрактов v1 + fixtures + канонический bundle `pp-001`
- [x] Детерминированный валидатор: schema + 14 кросс-проверок, JSON-отчёт,
  стабильные exit-коды
- [x] 51 тест; ruff, pyrefly

## M1 — Stage 4 pilot (next)

- [ ] Входные артефакты: стратегия предприятия, реестр стандартов
  (без них `fit_strategy`/`fit_standards` = unknown у всех идей)
- [ ] 5–10 реальных Idea-карточек
- [ ] Детерминированный rank engine поверх нормализованных AxisAssessment
- [ ] `impresario backlog rank --dry-run / --apply` (CAS: input_hash +
  expected version + монотонный version + immutable run record)
- [ ] Typed QG-4: `impresario backlog select <backlog> <idea>
  --expected-version N --actor <id> --reason <text>`
- [ ] Friction log пилота

## M2 — reference forconcept loop

- [ ] Reference runner цикла researcher ↔ creator (bounded 2–3 итерации,
  durable ExchangeLog, idempotency keys, crash/resume, golden traces)

## M3+ — интеграция экосистемы

- [ ] Kapelle как execution backend цикла (вендорит пинованные копии
  contracts; см. kapelle battle-testing трек)
- [ ] Входной контракт approved ProductProposal для steward/discovery
- [ ] dispatcher/Robin: read-only `product_proposal/gate_waiting` observation
- [ ] Зарегистрировать репо в списке зеркал Robin (урок: список слеп к
  новым/переименованным репо молча)
