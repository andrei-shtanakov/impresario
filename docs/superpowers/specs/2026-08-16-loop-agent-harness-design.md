# Дизайн: researcher/creator-харнесс forconcept-цикла (stage-brief + step)

Дата: 2026-08-16. Статус: на ревью (вторая половина M2-хвоста; уроки
prioritizer-харнесса и friction №16, №22).

## Проблема

Живых LLM-агентов у forconcept-цикла нет: единственная реализация
`Agent` — `ScriptedAgent` (реплей заранее написанных документов).
Промпты ролей не законтрактованы, `prompt_version` артефактов цикла —
фикция реплея. Нужен путь «живой оценщик ролей» с теми же гарантиями,
что у prioritizer-харнесса: детерминированный render, immutable
evidence, typed ingest, полный provenance.

## Решение: пошаговый brief/step вокруг существующего раннера

Цикл итеративен (ответ researcher'а формирует промпт creator'а), поэтому
харнесс — пошаговый CLI:

- `forconcept brief <ws>` выводит **следующую ожидаемую стадию из
  артефактов** (та же деривация, что у раннера: RP итерации N есть,
  CD нет → creator N) и детерминированно рендерит **StageBrief**;
- исполнитель прогоняет промпт через LLM и получает контент-ответ роли;
- `forconcept step <ws> --brief B --answer A --actor <id> --model <m>`
  валидирует пару и продвигает цикл.

**Ключевой инвариант: раннер — единственный исполнитель семантики.**
step ничего не персистит сам: он собирает полный артефакт (контент из
answer + bookkeeping) и скармливает его существующему `run_loop` через
одноразовый `SingleAnswerAgent`, используя существующие границы
`stop_after` (`research:N` для researcher; `evaluate:N` для creator —
раннер сам проходит validate → apply delta → evaluate → вердикт или
пауза). Валидация, trace, evaluator, fail-closed, crash/resume — всё
остаётся у раннера; `forconcept resume` после `needs_human` стыкуется
без изменений. Evaluator детерминированный — неприкосновенен.

## Контракт stage-brief/v1

`contracts/stage-brief/v1/schema.json`,
`$id: urn:impresario:contract:stage-brief:v1`, домашний стиль. Все поля
обязательны, `additionalProperties: false`:

| Поле | Содержание |
|---|---|
| `schema_version` | `const: "stage-brief/v1"` — дискриминатор (детекция по значению; `brief_id`-эвристика занята evaluation-brief'ом) |
| `brief_id` | `^SBR-[0-9a-f]{12}$` — выводимый |
| `loop_id` | `^LOOP-[0-9]{3,}$` |
| `iteration` | integer ≥ 0 |
| `role` | `enum: ["researcher", "creator"]` |
| `prompt_version` | `researcher/v1` \| `creator/v1` |
| `prompt_pack_hash` | sha256 байтов файла пака |
| `idea_input_hash` | канонический хеш идеи цикла (`idea.yaml` workspace) |
| `proposal_hash` | канонический хеш текущего `proposal.yaml` |
| `history_hash` | хеш истории RP/CD (см. ниже) |
| `prompt_hash` | sha256 UTF-8 байтов поля `prompt` |
| `prompt` | отрендеренный текст целиком |

**Freshness покрывает все входы промпта**: идея (`idea_input_hash`),
proposal (`proposal_hash`) и история (`history_hash`) — brief, чей любой
вход изменился, отвергается step'ом. Хеш `loop.state` в identity
сознательно не входит: промпт не содержит ни бюджета итераций, ни
stop-полей, а живое состояние step сверяет структурной проверкой стадии;
resume, расширивший бюджет между brief и step, brief не устаревает.

**История детерминирована**: порядок — `(iteration, role, id)`, где
role упорядочена как `researcher < creator`. `history_hash` =
канонический хеш документа
`{"history": [{iteration, role, id, hash: <канонический хеш артефакта>}...]}`
в этом порядке. Тот же порядок используется при рендере `{history}` в
промпт.

**Identity**: `brief_id` = `SBR-` + первые 12 hex канонического хеша
всех полей, кроме `schema_version`, `brief_id` и `prompt` (то есть
включая `prompt_hash` — подмена текста промпта меняет identity; урок
обоих ревью prioritizer-харнесса). Ни timestamp, ни случайности.
Briefs — immutable evidence в `<ws>/briefs/` (файл
`<brief_id lower>.yaml`): контент-адресация, идемпотентная перезапись
идентичных байтов, typed-отказ на расходящихся.

## Контракты ответов

Только контент роли, `additionalProperties: false`, свой
`schema_version`-дискриминатор; bookkeeping LLM не авторит (№15).
Формы полей зеркалят research-pack/v1 и concept-draft/v1.

**`research-answer/v1`** (`const: "research-answer/v1"`): `findings[]`
(claim / source_ref / confidence), `constraints[]`, `gaps[]`
(what, blocks_approval, опционально closed + answered_by — закрытие
прежних пробелов с evidence), `brief_for_creator` (непустой),
`requests_to_creator[]`.

**`concept-answer/v1`** (`const: "concept-answer/v1"`): `value_prop`,
`alternatives[]` (direction/summary), `chosen_direction`
(direction/why), `business_models[]`, `assumptions[]`
(text, blocks_approval, опционально answered_by),
`requests_to_researcher[]`, `proposal_delta` (непустой), опционально
`single_path_justification`.

Bookkeeping авторит step: `id` (следующий свободный `RP-NNN`/`CD-NNN`
workspace), `idea_ref`/`proposal_ref` из loop.state, `iteration` из
brief'а, `based_on_research` (пин на RP той же итерации — для CD),
`produced_by {kind: agent, id: actor, model, prompt_version}`,
`produced_at` = now вызова, `provenance` (см. валидатор).

## Промпт-паки

`prompts/researcher/v1/prompt.md` и `prompts/creator/v1/prompt.md` — по
файлу на роль; плейсхолдеры `{idea}`, `{proposal}`, `{history}`;
подстановка однопроходная (`re.sub` по трём токенам — урок Copilot);
скелет ответа каждой роли пинуется тестом к схеме (урок F4).

Правила researcher: честные gaps с `blocks_approval`; закрытие gap
только с `answered_by`-evidence; **прежде чем цитировать подтверждающее
evidence — искать более позднюю отменяющую запись** (№16 — родная роль
урока); запрет выдуманных `source_ref` (№15). Правила creator: ≥3
альтернатив либо явное `single_path_justification` (bundle-чек
`ALTERNATIVES_MISSING` уже enforce'ит); честные assumptions;
концентрированный `proposal_delta`; ответы на `requests_to_creator`.

## CLI: forconcept brief

```
impresario forconcept brief <ws> [--prompts DIR] [--contracts DIR]
```

Деривация следующей стадии из артефактов workspace (терминальный цикл /
ожидание evaluator-only шагов → typed-ответ «нет ожидаемого вызова
агента»); рендер brief'а; validate-then-atomic в `<ws>/briefs/`;
JSON-отчёт `{brief_id, role, iteration, path}`. Повторный вызов на
неизменённом workspace — байтовый no-op.

## CLI: forconcept step

```
impresario forconcept step <ws> --brief <path> --answer <path> \
    --actor <id> --model <m> [--prompts DIR] [--contracts DIR]
```

Протокол (порядок нормативный):

1. Brief: схема + двухслойный пересчёт identity (`prompt_hash` от байтов
   prompt; `brief_id` от identity-полей).
2. **Идемпотентность — ДО freshness** (после успешного шага workspace
   уже продвинулся, и потреблённый brief иначе был бы отвергнут как
   stale): найти артефакт workspace с `provenance.brief_id ==
   brief.brief_id`. Найден → кандидат из answer сравнивается с ним по
   всем полям, кроме `id` и `produced_at`: идентичный
   answer/actor/model → **no-op** (исходные id и produced_at
   сохраняются, JSON-отчёт со ссылкой на существующий артефакт);
   расхождение → typed `STEP_CONFLICT`, ничего не запускается.
3. Только для непотреблённого brief'а — **freshness + структурная
   проверка пары**: `(loop_id, iteration, role)` brief'а == текущая
   выведенная стадия workspace, И `idea_input_hash` / `proposal_hash` /
   `history_hash` == пересчёту от текущего workspace. Любое расхождение
   — typed `STALE_BRIEF`. В каждый момент валиден ровно один brief —
   класс friction №22 закрыт структурно.
4. Answer: схема контракта, соответствующего роли brief'а.
5. Материализация полного артефакта + запуск раннера:
   `run_loop(ws, SingleAnswerAgent(doc), stop_after=research:N |
   evaluate:N)`. Невалидный собранный артефакт отвергает сам раннер
   (fail-closed, verdict=failed не персистится харнессом — семантика
   раннера не дублируется). Отчёт: артефакт, вердикт/пауза раннера,
   следующая ожидаемая стадия (или terminal).

`SingleAnswerAgent` — реализация `Agent`, отдающая документ ровно для
`(role, iteration)` и типизированно падающая на любом другом вызове
(до второго вызова дело не доходит благодаря `stop_after`).

## Валидатор

- Loader: kinds `stage-brief`, `research-answer`, `concept-answer` — по
  значению `schema_version`.
- `BRIEF_IDENTITY` расширяется на stage-brief (та же двухслойная
  логика; у каждого вида briefs — свой набор identity-полей).
- research-pack/v1 и concept-draft/v1 расширяются опциональным
  `provenance {brief_id: ^SBR-…, prompt_pack_hash}` (расширение без
  смены `$id`; step заполняет всегда, ScriptedAgent-артефакты и история
  без него валидны).
- Кросс-чек `ARTIFACT_BRIEF` (аналог ASSESS_BRIEF): `provenance.brief_id`
  артефакта резолвится ровно в один stage-brief бандла (дубль/отсутствие
  — находка); `prompt_pack_hash` и `prompt_version`
  (`produced_by.prompt_version`) совпадают с brief'ом; `loop_id` brief'а
  совпадает с loop.state бандла, `iteration`/`role` — с артефактом.
  Артефакты без `provenance` пропускаются.

## Тесты

- Fixtures-инварианты трёх новых контрактов; расширения rp/cd —
  старые fixtures валидны, новые с provenance валидны.
- Ломающие тесты `BRIEF_IDENTITY` (stage-brief, оба слоя) и
  `ARTIFACT_BRIEF` (висячий/дублирующийся brief, расходящийся hash,
  несовпадающая роль/итерация).
- **Oracle-тест эквивалентности** (не байт-равенства: step добавляет
  `provenance` и другой `produced_by`, что меняет артефакты и их хеши в
  trace): пошаговое прохождение happy-сценария через brief/step с
  контентом HAPPY_SCRIPT как answers эквивалентно прямому
  `run_loop`+ScriptedAgent по: (а) содержательным полям RP/CD (модуло
  produced_by/produced_at/provenance/id); (б) применённым proposal
  delta; (в) последовательности стадий; (г) итоговому verdict и
  loop.state (модуло хеш-поля, зависящие от артефактов); (д)
  trace-семантике с исключением ожидаемо различающихся
  provenance/hash-полей.
- Freshness: изменение идеи / proposal / появление нового RP при том же
  proposal → `STALE_BRIEF`.
- Идемпотентность: повтор step с тем же brief+answer после продвижения
  workspace → no-op с сохранением id/produced_at; другой answer/actor →
  `STEP_CONFLICT`.
- Mis-pairing: creator-brief при ожидаемом researcher → `STALE_BRIEF`.
- Цепочка `needs_human` → `forconcept resume` → step итерации N+1.
- Детерминизм brief (двойной рендер байт-в-байт; порядок history
  `(iteration, role, id)` стабилен).
- CLI-тесты обеих команд, включая typed-ошибки exit 2.

## Вне скоупа

- Вендоринг паков и контрактов в kapelle (handoff после мержа).
- Envelope для async-исполнителя.
- LLM-вызовы из impresario; изменения evaluator и семантики раннера.
- Изменения prioritizer-харнесса.

## Закрытие

После мержа: TODO M2-хвост закрывается целиком; живой прогон цикла по
идее из backlog v3 — отдельный человеческий акт (QG-4 select + init +
brief/step-итерации).
