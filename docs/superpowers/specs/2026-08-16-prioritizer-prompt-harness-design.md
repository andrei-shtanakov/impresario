# Дизайн: промпт-харнесс оценщика (prioritizer/v1) — уход от manual-v0

Дата: 2026-08-16. Статус: утверждён (M2-хвост, friction №5; уроки №3, №6,
№15, №16).

## Проблема

Оценки RUN-001 авторились LLM без воспроизводимого промпта —
`prompt_version: prioritizer/manual-v0` честно помечает дыру (friction
№5): детерминизм гарантирован от нормализованных assessments вниз
(P-07), но не от идеи вверх. Нет ни законтрактованного промпта, ни
машинной границы между «LLM судит» и «валидатор материализует».

## Решение: render + ingest

impresario **не вызывает LLM**. Харнесс — две детерминированные
половины с машиночитаемым handoff'ом между ними:

- **render** фиксирует и хеширует входы (идея, стратегия, стандарты,
  промпт-пак) и детерминированно строит **EvaluationBrief** — единицу
  работы для любого исполнителя (человек, `claude -p`, будущий
  kapelle-адаптер);
- исполнитель прогоняет промпт brief'а через LLM и получает
  **AssessmentAnswer** — только суждение;
- **ingest** валидирует пары brief+answer и материализует immutable
  AxisAssessment, заполняя bookkeeping-поля сам.

Граница ответственности сохраняется: LLM авторит содержание, валидатор
владеет допустимостью; репо остаётся детерминированным, без сетевых
зависимостей и секретов. Замена исполнителя не меняет ни контрактов, ни
семантики.

Скоуп — только оценщик Stage 4. Researcher/creator-харнесс
forconcept-цикла — отдельный следующий спек на той же основе.

## Контракт evaluation-brief/v1

`contracts/evaluation-brief/v1/schema.json`,
`$id: urn:impresario:contract:evaluation-brief:v1`, домашний стиль
(`additionalProperties: false`, строгие паттерны). Все поля обязательны:

| Поле | Содержание |
|---|---|
| `brief_id` | `^BRF-[0-9a-f]{12}$` — **выводимый** (см. identity ниже) |
| `idea_ref` | `idea://IDEA-…` |
| `input_hash` | канонический хеш карточки (`sha256:…`) |
| `prompt_version` | `prioritizer/v1` |
| `prompt_pack_hash` | sha256 байтов файла промпт-пака |
| `policy_version` | `scoring/v1` |
| `strategy_hash` | sha256 байтов `<ws>/strategy.md` |
| `standards_hash` | sha256 байтов `<ws>/standards.md` |
| `prompt_hash` | sha256 точных UTF-8 байтов поля `prompt` |
| `prompt` | отрендеренный текст промпта целиком |

**Identity детерминирована и покрывает prompt**: `brief_id` = `BRF-` +
первые 12 hex канонического хеша документа `{idea_ref, input_hash,
prompt_version, prompt_pack_hash, policy_version, strategy_hash,
standards_hash, prompt_hash}` (существующий `canonical_doc_hash`).
Без `prompt_hash` в identity подмена текста промпта при сохранённых
остальных полях прошла бы пересчёт — поэтому prompt входит в identity
через свой хеш. Ни timestamp, ни случайного ID: одинаковые входы →
байт-в-байт одинаковый brief.

**Brief — immutable evidence.** `briefs/` не очищается: brief встраивает
отрендеренный промпт — то есть полные байты идеи, стратегии и стандартов
на момент рендера — и потому сам является snapshot'ом своих входов.
Заявление «assessment хранит всё необходимое для воспроизведения»
выполняется через ссылку `provenance.brief_id` → `briefs/<id>.yaml`.
Контент-адресация (identity включает `prompt_hash`) делает перезапись
невозможной по построению: тот же `brief_id` = те же байты;
идемпотентная повторная запись идентичных байтов разрешена, запись
расходящихся байтов под существующим id — typed-ошибка
(`BRIEF_IDENTITY` поймает и руками подделанный файл).
Файл — `briefs/<brief_id в lower case>.yaml`.

## Контракт assessment-answer/v1

`$id: urn:impresario:contract:assessment-answer:v1`. **Только суждение**,
`additionalProperties: false` — схема отвергает любые
identity/hash/bookkeeping-поля (урок №15: LLM не авторит улики учёта):

| Поле | Содержание |
|---|---|
| `schema_version` | `const: "assessment-answer/v1"` — обязательный дискриминатор (детекция kind без хрупкой эвристики по набору полей) |
| `fit_strategy`, `fit_market`, `fit_standards` | та же шкала и `unknown`-семантика, что в axis-assessment/v1 |
| `strategy_blocker`, `standards_blocker` | boolean; при `true` обязателен соответствующий `*_blocker_ref` с якорем `strategy://…`/`standards://…` (условная схема, как в axis-assessment) |
| `rationale` | по осям, непустые строки |
| `evidence_refs` | список непустых строк |
| `confidence` | как в axis-assessment |

`schema_version` — не bookkeeping авторства: это маркер формата,
который модель воспроизводит по инструкции промпта.

**Связь answer↔brief** — явная CLI-пара `--brief X --answer Y`,
заполняется исполнителем, не моделью. `STALE_INPUT` проверяет **brief
против текущей карточки** (не answer против brief — answer намеренно
не несёт identity). Envelope с `brief_ref` для асинхронного бэкенда —
задокументированное будущее расширение: отдельный новый контракт
(исполнитель-authored), существующие brief/answer не меняются.

## Расширение axis-assessment/v1 (без смены $id)

Опциональный объект `provenance` (`additionalProperties: false`):
`{brief_id, prompt_pack_hash, strategy_hash, standards_hash}`.
Добавление опционального поля расширяет множество валидных документов —
допустимо без смены идентификатора; старые assessments валидны, харнесс
заполняет всегда. Вместе с immutable brief это даёт полный provenance:
из assessment восстанавливается brief, из brief — точные входы.

## Промпт-пак prompts/prioritizer/v1

Один файл `prompts/prioritizer/v1/prompt.md`: шаблон с плейсхолдерами
`{idea}`, `{strategy}`, `{standards}` + инструкции суждения + требуемый
скелет ответа (валидный против assessment-answer/v1, включая
`schema_version`). `prompt_pack_hash` = sha256 байтов файла. Правка
промпта = новый каталог версии (`prioritizer/v2`), как у контрактов;
каталог `prompts/` ищется вверх от cwd, как `contracts/`
(`--prompts DIR` переопределяет).

В инструкции зашиты уроки пилота: честный `unknown` вместо догадки при
отсутствии улик (№6); blocker только с конкретным якорем, не с файлом
целиком (№3-конвенция); запрет плейсхолдеров и выдуманных ссылок в
evidence (№15); требование искать более позднее отменяющее evidence, а
не останавливаться на первом подтверждающем (№16).

## CLI: assess render

```
impresario assess render <ws> [--idea IDEA-XXX] [--prompts DIR] [--contracts DIR]
```

Читает карточки `<ws>/ideas/` (или одну), `<ws>/strategy.md`,
`<ws>/standards.md`, промпт-пак; строит briefs; пишет
validate-then-atomic в `<ws>/briefs/`; JSON-отчёт со списком
`{brief_id, idea_ref, path}`. Полностью детерминирован: повторный
запуск на неизменённых входах — байтовый no-op (существующие файлы с
теми же байтами не трогаются). Изменилась карточка/стратегия/промпт —
появляется **новый** brief с новым id; старый остаётся (immutable
evidence прошлых рендеров).

## CLI: assess ingest

```
impresario assess ingest <ws> --run-id RUN-XXX --actor <id> --model <m> \
    (--brief <path> --answer <path>)...
```

**Двухфазный протокол под single-writer lock** (весь вызов — одна
блокировка, как rank/select):

Фаза 1 — валидация **всех** пар, ни одной записи:
1. brief: схема + пересчёт `brief_id` (несовпадение — typed-ошибка);
2. `STALE_INPUT`: `brief.input_hash` == текущий канонический хеш
   карточки `brief.idea_ref` в workspace;
3. answer: схема (дискриминатор, шкалы, условные blocker-ref'ы);
4. дубликаты внутри вызова: две пары с одним `brief_id` — ошибка;
5. **identity/idempotency**: ключ материализации —
   `(run_id, brief_id)`. Если assessment с таким ключом уже существует
   (поиск по `run_id` + `provenance.brief_id` в `assessments/`):
   кандидат сравнивается с существующим по всем полям, кроме
   `assessment_id` и `evaluated_at`. Совпадение → пара помечается
   no-op (первый `evaluated_at` сохраняется). Расхождение (другой
   answer, actor или model) → typed `ASSESS_CONFLICT`, весь вызов
   отклоняется.

Любая ошибка фазы 1 — **ничего не записано**.

Фаза 2 — материализация всего набора: на каждую не-no-op пару
`assessment_id` = следующий свободный `ASMT-NNN` (детерминирован
состоянием workspace под lock'ом), `evaluated_at` = now вызова,
`evaluator {kind: agent, id: actor, model, prompt_version}` из CLI и
brief'а, `provenance` из brief'а; validate-then-atomic write;
собственный выход проходит контракты.

**Recovery при сбое посреди фазы 2** (транзакции на несколько файлов
нет — вместо неё документированная идемпотентность): каждая записанная
пара уже полна и валидна; повторный запуск того же вызова проходит
фазу 1, находит записанные пары по `(run_id, brief_id)` → no-op, и
дописывает остаток. Частично материализованный RUN дозаписывается, не
дублируется.

## Валидатор

- Loader: kind `evaluation-brief` (по `brief_id`), kind
  `assessment-answer` (по `schema_version` — дискриминатор, не
  эвристика по набору полей); оба в `CONTRACT_KINDS`.
- Кросс-чек `BRIEF_IDENTITY` — два шага: (1) `prompt_hash` равен
  sha256 фактических UTF-8 байтов поля `prompt`; (2) `brief_id` равен
  пересчёту канонического хеша identity-полей, включая `prompt_hash`.
  Подделка любого из слоёв — находка.
- Кросс-чек `ASSESS_BRIEF` — цепь assessment → brief tool-enforced:
  `provenance.brief_id` резолвится ровно в один EvaluationBrief бандла;
  `provenance`-хеши (`prompt_pack_hash`, `strategy_hash`,
  `standards_hash`) совпадают с полями brief'а; `input_hash` и
  `evaluator.prompt_version` самого assessment также совпадают с
  brief'ом. `brief_id` остаётся plain id (новая ref-схема не вводится —
  проверка явная); assessment без `provenance` (manual-v0 и старые)
  чек пропускает.
- Answers в bundle schema-only; кросс-объектных проверок не имеют
  (answer намеренно без identity).

## Тесты

- Fixtures ≥1 valid / ≥1 invalid на оба новых контракта (invalid answer:
  лишнее bookkeeping-поле; blocker без ref; без `schema_version`);
  fixture axis-assessment с `provenance` + существующие без него валидны.
- Ломающие тесты `BRIEF_IDENTITY` (оба шага: порча prompt при верном
  brief_id; порча identity-поля) и `ASSESS_BRIEF` (висячий
  provenance.brief_id; расходящийся хеш; расходящийся
  input_hash/prompt_version).
- Golden-детерминизм render: двойной прогон байт-в-байт; пин `brief_id`
  на фиксированных входах; изменение карточки → новый id, старый brief
  нетронут.
- Ingest: happy (полный RUN на ≥2 идеях); `STALE_INPUT`; порченый
  `brief_id`; невалидный answer; `ASSESS_CONFLICT` (retry с другим
  answer/actor/model); идемпотентный retry (no-op, первый `evaluated_at`
  сохранён); recovery — симуляция сбоя между записями пар, повторный
  вызов дозаписывает без дублей; фаза-1-ошибка в одной паре → ничего не
  записано.
- CLI-тесты обеих команд; бандл pp-001 и пилот pp-101 остаются чистыми.

## Вне скоупа

- Живой RUN-003 — человеческий акт после мержа, не часть задачи.
- Envelope-контракт асинхронного исполнителя.
- Researcher/creator-харнесс forconcept-цикла (следующий спек).
- Изменения rank engine и scoring policy.

## Закрытие

После мержа: TODO M2-хвост сужается до researcher/creator-части;
friction №5 получает отметку о закрытии prioritizer-половины.
