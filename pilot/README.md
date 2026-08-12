# Stage 4 pilot — входные артефакты (M1)

Контентные входы пилота ранжирования: без них `fit_strategy` /
`fit_standards` честно равны `unknown` у всех идей.

| Вход | Файл | Ось |
|------|------|-----|
| Стратегия экосистемы | [strategy.md](./strategy.md) | `fit_strategy` (цели G-1…G-5, ограничения C-1…C-3) |
| Реестр стандартов | [standards.md](./standards.md) | `fit_standards` (STD-1…STD-9) |
| Idea-карточки ×8 | [ideas/](./ideas/) | предмет ранжирования |

## Конвенции ссылок

- `strategy://ecosystem/2026/<anchor>` → якорь в `strategy.md`
  (пример: `strategy://ecosystem/2026/C-3` — запрет agent-authority);
- `standards://ecosystem/<ID>` → стандарт в `standards.md`
  (пример: `standards://ecosystem/STD-6` — публичный контур без
  приватного контента).

Для валидатора это внешние evidence-ссылки: они не разрешаются в bundle и
не считаются ошибкой; их использует rank engine и человек на ревью.
`*_blocker_ref` в assessments должен указывать на конкретный якорь
(C-x / STD-x), не на файл целиком.

## Карточки

Идеи — реальные кандидаты-инициативы экосистемы (источники указаны в
`source.ref`: vault-ноты, роадмапы, закрытые вехи). Все карточки валидны
против `contracts/idea/v1`:

```bash
uv run impresario validate pilot/ideas
```

`business_attractiveness` — pre-triage прикидка автора карточки; в scoring
policy не входит.

## Чего здесь нет (появится в M1)

AxisAssessment-прогон, rank engine, RankedBacklog и typed QG-4 — код M1
(см. [TODO.md](../TODO.md)). Пилотный протокол: LLM предлагает assessments
со ссылками на улики, детерминированный движок считает ранг, человек
решает.
