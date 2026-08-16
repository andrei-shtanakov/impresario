# Prioritizer Prompt Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Харнесс render + ingest для оценщика Stage 4: контракты
`evaluation-brief/v1` и `assessment-answer/v1`, промпт-пак
`prioritizer/v1`, CLI `impresario assess render|ingest`, кросс-чеки
`BRIEF_IDENTITY` и `ASSESS_BRIEF`.

**Architecture:** Новый модуль `src/impresario/harness.py` (identity
brief'а, рендер, двухфазный ingest под single-writer lock); два новых
контракта + опциональный `provenance` в axis-assessment/v1 (расширение
без смены `$id`); loader-детекция по `brief_id` и дискриминатору
`schema_version`; briefs — immutable evidence в `<ws>/briefs/`.

**Tech Stack:** Python 3.11+, jsonschema Draft 2020-12, PyYAML, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-16-prioritizer-prompt-harness-design.md`
— обязательное чтение вместе с задачей.

## Global Constraints

- Только `uv`: `uv run pytest`, `uv run ruff format . && uv run ruff check .`,
  `uv run pyrefly check` — после каждой задачи все три зелёные.
- Line length 88; type hints; docstrings на публичных API.
- Ветка `feat/prioritizer-harness` (существует, спека закоммичена);
  коммитить прямо в неё. Мерж — PR + человек.
- `axis-assessment/v1` менять ТОЛЬКО расширением (опциональный
  `provenance`); прочие существующие схемы не трогать.
- Все hash-поля — формат `^sha256:[0-9a-f]{64}$` (как `input_hash`).
- `brief_id` — `^BRF-[0-9a-f]{12}$`, выводимый; ни timestamp, ни
  случайности нигде в brief.
- Идея в prompt рендерится КАНОНИЧЕСКИМ дампом (`ws.dump_yaml`
  распарсенного дока), не сырыми байтами файла: правка комментария не
  порождает новый brief (identity согласована с canonical input_hash).
- pilot/ не трогать (никаких прогонов по пилоту в тестах — тесты строят
  свои tmp-workspace; исключение: существующие тесты чистоты бандлов).
- Коммиты заканчиваются `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Инварианты: каждый контракт ≥1 valid + ≥1 invalid fixture; каждый
  новый кросс-чек — ломающий тест.

---

### Task 1: Контракты brief/answer, расширение axis-assessment, loader

**Files:**
- Create: `contracts/evaluation-brief/v1/schema.json`
- Create: `contracts/evaluation-brief/v1/fixtures/valid/brf-valid.yaml`
- Create: `contracts/evaluation-brief/v1/fixtures/invalid/brf-bad-id-shape.yaml`
- Create: `contracts/evaluation-brief/v1/fixtures/invalid/brf-missing-prompt-hash.yaml`
- Create: `contracts/evaluation-brief/v1/fixtures/invalid/brf-extra-field.yaml`
- Create: `contracts/assessment-answer/v1/schema.json`
- Create: `contracts/assessment-answer/v1/fixtures/valid/answer-full.yaml`
- Create: `contracts/assessment-answer/v1/fixtures/valid/answer-unknown-axis.yaml`
- Create: `contracts/assessment-answer/v1/fixtures/invalid/answer-no-discriminator.yaml`
- Create: `contracts/assessment-answer/v1/fixtures/invalid/answer-blocker-without-ref.yaml`
- Create: `contracts/assessment-answer/v1/fixtures/invalid/answer-bookkeeping-field.yaml`
- Modify: `contracts/axis-assessment/v1/schema.json` (добавить `provenance`)
- Create: `contracts/axis-assessment/v1/fixtures/valid/assessment-with-provenance.yaml`
- Modify: `src/impresario/loader.py` (CONTRACT_KINDS + detect_kind)
- Test: `tests/test_schema_fixtures.py` (detect_kind-тесты; fixtures подхватятся параметризацией)

**Interfaces:**
- Produces: kinds `"evaluation-brief"` и `"assessment-answer"` в
  `CONTRACT_KINDS` (⇒ `load_validators()` отдаёт валидаторы);
  `detect_kind`: наличие `brief_id` → `evaluation-brief`;
  `schema_version == "assessment-answer/v1"` → `assessment-answer`.

- [ ] **Step 1: Failing-тесты детекции**

В конец `tests/test_schema_fixtures.py`:

```python
def test_detect_kind_evaluation_brief() -> None:
    from impresario.loader import detect_kind

    assert detect_kind({"brief_id": "BRF-0123456789ab"}) == "evaluation-brief"


def test_detect_kind_assessment_answer() -> None:
    from impresario.loader import detect_kind

    assert (
        detect_kind({"schema_version": "assessment-answer/v1"}) == "assessment-answer"
    )
```

- [ ] **Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_schema_fixtures.py -k detect_kind -v`
Expected: FAIL (UnknownContractError / не тот kind).

- [ ] **Step 3: loader**

В `src/impresario/loader.py`: в `CONTRACT_KINDS` после `"loop-state"`
добавить `"evaluation-brief", "assessment-answer",`; в `detect_kind`
ПЕРЕД веткой `if "loop_id" in data:` добавить:

```python
    if "brief_id" in data:
        return "evaluation-brief"
    if data.get("schema_version") == "assessment-answer/v1":
        return "assessment-answer"
```

- [ ] **Step 4: Схема evaluation-brief/v1**

`contracts/evaluation-brief/v1/schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:evaluation-brief:v1",
  "title": "EvaluationBrief",
  "description": "Handoff render → executor промпт-харнесса оценщика (docs/semantics.md, docs/superpowers/specs/2026-08-16-prioritizer-prompt-harness-design.md). Immutable evidence: brief_id контент-адресован (канонический хеш identity-полей, включая prompt_hash), одинаковые входы дают байт-в-байт одинаковый brief; timestamp и случайных ID нет по построению.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "brief_id",
    "idea_ref",
    "input_hash",
    "prompt_version",
    "prompt_pack_hash",
    "policy_version",
    "strategy_hash",
    "standards_hash",
    "prompt_hash",
    "prompt"
  ],
  "properties": {
    "brief_id": {
      "type": "string",
      "pattern": "^BRF-[0-9a-f]{12}$"
    },
    "idea_ref": {
      "type": "string",
      "pattern": "^idea://IDEA-[0-9]{3,}$"
    },
    "input_hash": {
      "$ref": "#/$defs/sha256"
    },
    "prompt_version": {
      "type": "string",
      "minLength": 1
    },
    "prompt_pack_hash": {
      "$ref": "#/$defs/sha256"
    },
    "policy_version": {
      "type": "string",
      "minLength": 1
    },
    "strategy_hash": {
      "$ref": "#/$defs/sha256"
    },
    "standards_hash": {
      "$ref": "#/$defs/sha256"
    },
    "prompt_hash": {
      "$ref": "#/$defs/sha256"
    },
    "prompt": {
      "type": "string",
      "minLength": 1
    }
  },
  "$defs": {
    "sha256": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    }
  }
}
```

- [ ] **Step 5: Схема assessment-answer/v1**

`contracts/assessment-answer/v1/schema.json` (шкала/blocker-условия —
зеркало axis-assessment/v1):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:assessment-answer:v1",
  "title": "AssessmentAnswer",
  "description": "Только суждение LLM-оценщика: оценки по осям, blockers с якорями, rationale, evidence, confidence. Никаких identity/hash/bookkeeping-полей — additionalProperties: false их отвергает (урок friction №15). schema_version — маркер формата (детекция kind), не bookkeeping авторства.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "fit_strategy",
    "fit_market",
    "fit_standards",
    "strategy_blocker",
    "standards_blocker",
    "rationale",
    "evidence_refs",
    "confidence"
  ],
  "properties": {
    "schema_version": {
      "const": "assessment-answer/v1"
    },
    "fit_strategy": {
      "$ref": "#/$defs/axisScore"
    },
    "fit_market": {
      "$ref": "#/$defs/axisScore"
    },
    "fit_standards": {
      "$ref": "#/$defs/axisScore"
    },
    "strategy_blocker": {
      "type": "boolean"
    },
    "strategy_blocker_ref": {
      "type": "string",
      "minLength": 1
    },
    "standards_blocker": {
      "type": "boolean"
    },
    "standards_blocker_ref": {
      "type": "string",
      "minLength": 1
    },
    "rationale": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "fit_strategy": {
          "type": "string",
          "minLength": 1
        },
        "fit_market": {
          "type": "string",
          "minLength": 1
        },
        "fit_standards": {
          "type": "string",
          "minLength": 1
        }
      }
    },
    "evidence_refs": {
      "type": "array",
      "items": {
        "type": "string",
        "minLength": 1
      }
    },
    "confidence": {
      "enum": ["high", "medium", "low"]
    }
  },
  "allOf": [
    {
      "if": {
        "properties": { "strategy_blocker": { "const": true } }
      },
      "then": { "required": ["strategy_blocker_ref"] }
    },
    {
      "if": {
        "properties": { "standards_blocker": { "const": true } }
      },
      "then": { "required": ["standards_blocker_ref"] }
    }
  ],
  "$defs": {
    "axisScore": {
      "oneOf": [
        { "type": "integer", "minimum": 1, "maximum": 5 },
        { "const": "unknown" }
      ]
    }
  }
}
```

- [ ] **Step 6: Расширение axis-assessment/v1**

В `contracts/axis-assessment/v1/schema.json` в `properties` (после
`evaluated_at`) добавить — и НИЧЕГО больше не менять:

```json
    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "brief_id",
        "prompt_pack_hash",
        "strategy_hash",
        "standards_hash"
      ],
      "properties": {
        "brief_id": { "type": "string", "pattern": "^BRF-[0-9a-f]{12}$" },
        "prompt_pack_hash": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" },
        "strategy_hash": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" },
        "standards_hash": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" }
      }
    }
```

(`provenance` НЕ добавляется в `required` — расширение, не сужение.)

- [ ] **Step 7: Fixtures**

`evaluation-brief/v1/fixtures/valid/brf-valid.yaml` — согласованный
документ (brief_id намеренно фиктивный, но по паттерну; кросс-чек
identity — Task 4, схема его не считает):

```yaml
brief_id: BRF-0123456789ab
idea_ref: idea://IDEA-001
input_hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
prompt_version: prioritizer/v1
prompt_pack_hash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
policy_version: scoring/v1
strategy_hash: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
standards_hash: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
prompt_hash: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
prompt: |
  Оцени идею по осям. (fixture)
```

Invalid — копии valid с одной поломкой каждая:
- `brf-bad-id-shape.yaml`: `brief_id: BRF-XYZ`
- `brf-missing-prompt-hash.yaml`: удалить `prompt_hash`
- `brf-extra-field.yaml`: добавить `rendered_at: '2026-08-16T00:00:00Z'`

`assessment-answer/v1/fixtures/valid/answer-full.yaml`:

```yaml
schema_version: assessment-answer/v1
fit_strategy: 5
fit_market: 4
fit_standards: 5
strategy_blocker: false
standards_blocker: true
standards_blocker_ref: "standards://ecosystem/STD-6"
rationale:
  fit_strategy: "Прямое попадание в G-5."
  fit_market: "Спрос внутренний, зафиксирован инцидентом."
  fit_standards: "Нарушает STD-6: публичный контур с приватным контентом."
evidence_refs:
  - "strategy://ecosystem/2026/G-5"
  - "standards://ecosystem/STD-6"
confidence: high
```

`answer-unknown-axis.yaml` — как full, но `fit_market: unknown`,
`standards_blocker: false` без ref, rationale.fit_market: "Замеров
внутреннего спроса нет — честный unknown."

Invalid:
- `answer-no-discriminator.yaml`: без `schema_version`
- `answer-blocker-without-ref.yaml`: `standards_blocker: true`, ref удалён
- `answer-bookkeeping-field.yaml`: добавить `input_hash: "sha256:..."`
  (64 hex) — bookkeeping отвергается `additionalProperties`

`axis-assessment/v1/fixtures/valid/assessment-with-provenance.yaml` —
копия существующей valid-fixture assessment'а с добавленным блоком
`provenance` (4 поля по паттернам выше) и
`evaluator.prompt_version: prioritizer/v1`.

- [ ] **Step 8: Прогнать тесты**

Run: `uv run pytest tests/test_schema_fixtures.py -v`
Expected: PASS; в параметрах появились fixtures обоих контрактов и
`assessment-with-provenance`. Существующие valid-fixtures axis-assessment
БЕЗ provenance остались зелёными. Затем
`uv run pytest && uv run ruff format . && uv run ruff check . && uv run pyrefly check`.

- [ ] **Step 9: Commit**

```bash
git add contracts src/impresario/loader.py tests/test_schema_fixtures.py
git commit -m "feat: контракты evaluation-brief/v1 и assessment-answer/v1, provenance в axis-assessment"
```

---

### Task 2: Промпт-пак prioritizer/v1 и поиск каталога prompts

**Files:**
- Create: `prompts/prioritizer/v1/prompt.md`
- Create: `src/impresario/harness.py` (начало: `find_prompts_dir`, `sha256_bytes`)
- Test: `tests/test_harness.py` (новый)

**Interfaces:**
- Produces: `find_prompts_dir(start: Path) -> Path` (walk-up, как
  `find_contracts_dir`; ищет `prompts/prioritizer/v1/prompt.md`);
  `sha256_bytes(data: bytes) -> str` (формат `sha256:<64hex>`);
  константы `PROMPT_VERSION = "prioritizer/v1"`,
  `POLICY_VERSION = "scoring/v1"`.

- [ ] **Step 1: Failing-тесты**

`tests/test_harness.py`:

```python
"""Промпт-харнесс оценщика: identity, render, ingest (spec 2026-08-16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import CONTRACTS_DIR, REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


def test_find_prompts_dir_walks_up() -> None:
    from impresario.harness import find_prompts_dir

    assert find_prompts_dir(REPO_ROOT / "pilot") == PROMPTS_DIR


def test_find_prompts_dir_missing_raises(tmp_path: Path) -> None:
    from impresario.harness import find_prompts_dir

    with pytest.raises(FileNotFoundError):
        find_prompts_dir(tmp_path)


def test_sha256_bytes_format() -> None:
    from impresario.harness import sha256_bytes

    digest = sha256_bytes(b"abc")
    assert digest == (
        "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_prompt_pack_exists_and_carries_placeholders() -> None:
    text = (PROMPTS_DIR / "prioritizer" / "v1" / "prompt.md").read_text(
        encoding="utf-8"
    )
    for token in ("{idea}", "{strategy}", "{standards}"):
        assert token in text
    assert "assessment-answer/v1" in text  # скелет ответа с дискриминатором
```

- [ ] **Step 2: Убедиться, что падают** (нет модуля/файла)

Run: `uv run pytest tests/test_harness.py -v` → FAIL.

- [ ] **Step 3: harness.py (начало)**

```python
"""Prompt harness for the Stage 4 prioritizer: render + ingest.

impresario never calls an LLM. render deterministically builds
EvaluationBrief documents (content-addressed, immutable evidence);
an external executor runs the brief's prompt and returns an
assessment-answer/v1 judgment; ingest validates pairs and materializes
immutable AxisAssessments, authoring every bookkeeping field itself
(spec: docs/superpowers/specs/2026-08-16-prioritizer-prompt-harness-design.md).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

PROMPT_VERSION = "prioritizer/v1"
POLICY_VERSION = "scoring/v1"


class HarnessError(Exception):
    """A typed harness failure (usage, tampering, conflict)."""


def sha256_bytes(data: bytes) -> str:
    """`sha256:<hex>` digest in the contracts' hash format."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def find_prompts_dir(start: Path) -> Path:
    """Walk upward from *start* to find the prompts/ directory."""
    for candidate in (start, *start.resolve().parents):
        prompts = candidate / "prompts"
        if (prompts / "prioritizer" / "v1" / "prompt.md").is_file():
            return prompts
    raise FileNotFoundError(
        f"prompts/ directory with prioritizer/v1 not found above {start}"
    )
```

- [ ] **Step 4: prompt.md**

`prompts/prioritizer/v1/prompt.md` (дословно; плейсхолдеры подменяются
`.replace`, поэтому фигурные скобки в остальном тексте запрещены):

```markdown
# Оценщик идей — prioritizer/v1

Ты — оценщик product-governance контура. Оцени ОДНУ идею по трём осям
против стратегии и реестра стандартов ниже. Твой ответ материализует
детерминированный инструмент; ты авторишь только суждение.

## Правила суждения

1. Шкала осей: целое 1..5 либо строка `unknown`. Если улик нет —
   честный `unknown`, не догадка (замеров нет ≠ спроса нет).
2. Blocker — только доказанный: `strategy_blocker`/`standards_blocker`
   ставь `true` только с конкретной якорной ссылкой в
   `strategy_blocker_ref`/`standards_blocker_ref` вида
   `strategy://ecosystem/2026/C-x` или `standards://ecosystem/STD-x`.
   Ссылка на файл целиком — не якорь. Score ранжирует, blocker
   исключает; это разные утверждения.
3. Evidence: в `evidence_refs` — только реально существующие якоря и
   источники из материалов ниже. Никаких плейсхолдеров, выдуманных
   ссылок и «пример: ...». Пустой список лучше выдуманного.
4. Актуальность: прежде чем цитировать подтверждающее evidence,
   проверь по материалам, нет ли более ПОЗДНЕЙ отменяющей записи;
   решение, отменённое позже, — не evidence.
5. `rationale` по каждой оси — одно-два предложения со ссылками на
   конкретные якоря, без пересказа всей идеи.

## Формат ответа

Верни РОВНО один YAML-документ (без Markdown-ограждений и пояснений):

schema_version: assessment-answer/v1
fit_strategy: <1..5 | unknown>
fit_market: <1..5 | unknown>
fit_standards: <1..5 | unknown>
strategy_blocker: <true | false>
strategy_blocker_ref: "<якорь, только при true>"
standards_blocker: <true | false>
standards_blocker_ref: "<якорь, только при true>"
rationale:
  fit_strategy: "<...>"
  fit_market: "<...>"
  fit_standards: "<...>"
evidence_refs:
  - "<якорь или источник>"
confidence: <high | medium | low>

Не добавляй НИКАКИХ других полей: идентификаторы, хеши и метки времени
авторит инструмент, не ты.

## Идея

{idea}

## Стратегия экосистемы

{strategy}

## Реестр стандартов

{standards}
```

- [ ] **Step 5: Прогнать тесты**

Run: `uv run pytest tests/test_harness.py -v` → PASS; затем полный
`uv run pytest`, ruff, pyrefly.

- [ ] **Step 6: Commit**

```bash
git add prompts src/impresario/harness.py tests/test_harness.py
git commit -m "feat: промпт-пак prioritizer/v1 и каркас harness (поиск prompts, sha256)"
```

---

### Task 3: Identity brief'а и детерминированный render

**Files:**
- Modify: `src/impresario/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: Task 1 kinds/валидаторы; Task 2 helpers;
  `impresario.hashing.canonical_doc_hash`; `impresario.workspace`
  (`dump_yaml`, `write_atomic`); `impresario.loader.load_doc`;
  `impresario.schemas.load_validators`.
- Produces:
  `brief_identity(fields: dict[str, str]) -> str` — `BRF-<12hex>` от
  канонического хеша РОВНО восьми identity-полей;
  `build_brief(idea_doc, *, idea_text, prompt_template, prompt_pack_hash,
  strategy_text, standards_text) -> dict` — полный brief-док;
  `render_briefs(workspace: Path, contracts_dir: Path, prompts_dir: Path,
  *, idea_id: str | None = None) -> dict` — пишет briefs, возвращает
  отчёт `{"ok": True, "briefs": [{"brief_id","idea_ref","path"}...]}`;
  `briefs_dir(workspace) -> Path` (= `workspace / "briefs"`).

- [ ] **Step 1: Failing-тесты**

В `tests/test_harness.py` добавить (фикстура `assess_ws` строит
tmp-workspace: `ideas/idea-001.yaml` — минимальная валидная карточка,
`strategy.md`, `standards.md`):

```python
import yaml

from impresario.loader import load_doc
from impresario.schemas import load_validators


IDEA_DOC = {
    "id": "IDEA-001",
    "title": "Test idea",
    "date": "2026-08-16",
    "source": {"kind": "internal", "ref": "test"},
    "priority": "high",
    "business_attractiveness": 3,
    "status": "new",
    "hypothesis": "h",
}


@pytest.fixture()
def assess_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "ideas").mkdir(parents=True)
    (ws / "ideas" / "idea-001.yaml").write_text(
        yaml.safe_dump(IDEA_DOC, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (ws / "strategy.md").write_text("# Стратегия\nG-1: цель.\n", encoding="utf-8")
    (ws / "standards.md").write_text("# Стандарты\nSTD-1: правило.\n", encoding="utf-8")
    return ws


def test_brief_identity_depends_on_prompt_hash() -> None:
    from impresario.harness import brief_identity

    fields = {
        "idea_ref": "idea://IDEA-001",
        "input_hash": "sha256:" + "a" * 64,
        "prompt_version": "prioritizer/v1",
        "prompt_pack_hash": "sha256:" + "b" * 64,
        "policy_version": "scoring/v1",
        "strategy_hash": "sha256:" + "c" * 64,
        "standards_hash": "sha256:" + "d" * 64,
        "prompt_hash": "sha256:" + "e" * 64,
    }
    base = brief_identity(fields)
    assert base.startswith("BRF-") and len(base) == 16
    changed = brief_identity({**fields, "prompt_hash": "sha256:" + "f" * 64})
    assert changed != base  # подмена промпта меняет identity


def test_render_is_deterministic_and_valid(assess_ws: Path) -> None:
    from impresario.harness import render_briefs

    report1 = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report1["ok"] and len(report1["briefs"]) == 1
    path = Path(report1["briefs"][0]["path"])
    bytes1 = path.read_bytes()

    report2 = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report2["briefs"] == report1["briefs"]
    assert path.read_bytes() == bytes1  # байтовый no-op

    doc = load_doc(path)
    assert doc.kind == "evaluation-brief"
    validators = load_validators(CONTRACTS_DIR)
    from impresario.schemas import check_schema

    assert check_schema(doc, validators) == []


def test_render_new_id_on_idea_change_keeps_old_brief(assess_ws: Path) -> None:
    from impresario.harness import render_briefs

    first = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    old_id = first["briefs"][0]["brief_id"]

    idea_path = assess_ws / "ideas" / "idea-001.yaml"
    changed = dict(IDEA_DOC, hypothesis="h2")
    idea_path.write_text(
        yaml.safe_dump(changed, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    second = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    new_id = second["briefs"][0]["brief_id"]
    assert new_id != old_id
    assert (assess_ws / "briefs" / f"{old_id.lower()}.yaml").exists()


def test_render_comment_only_edit_is_noop(assess_ws: Path) -> None:
    from impresario.harness import render_briefs

    first = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    idea_path = assess_ws / "ideas" / "idea-001.yaml"
    idea_path.write_text(
        "# комментарий\n" + idea_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    second = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert second["briefs"] == first["briefs"]


def test_render_refuses_divergent_bytes_under_same_id(assess_ws: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    path = Path(report["briefs"][0]["path"])
    tampered = path.read_text(encoding="utf-8").replace(
        "prioritizer/v1", "prioritizer/v1 "
    )
    path.write_text(tampered, encoding="utf-8")
    with pytest.raises(HarnessError, match="diverg"):
        render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
```

- [ ] **Step 2: Убедиться, что падают** → FAIL (нет функций).

- [ ] **Step 3: Реализация**

Дополнить `src/impresario/harness.py`:

```python
from typing import Any

from . import workspace as ws
from .hashing import canonical_doc_hash
from .loader import load_doc
from .schemas import check_schema, load_validators

_IDENTITY_FIELDS = (
    "idea_ref",
    "input_hash",
    "prompt_version",
    "prompt_pack_hash",
    "policy_version",
    "strategy_hash",
    "standards_hash",
    "prompt_hash",
)


def briefs_dir(workspace: Path) -> Path:
    """Immutable evidence directory of rendered briefs."""
    return workspace / "briefs"


def brief_identity(fields: dict[str, str]) -> str:
    """Derived brief id: canonical hash of exactly the identity fields.

    prompt_hash is part of the tuple on purpose: without it a tampered
    prompt with untouched sibling fields would pass the recompute
    (spec review, 2026-08-16).
    """
    identity = {name: fields[name] for name in _IDENTITY_FIELDS}
    return "BRF-" + canonical_doc_hash(identity).removeprefix("sha256:")[:12]


def build_brief(
    idea_doc: dict[str, Any],
    *,
    idea_text: str,
    prompt_template: str,
    prompt_pack_hash: str,
    strategy_text: str,
    standards_text: str,
) -> dict[str, Any]:
    """A complete, schema-valid EvaluationBrief document (no I/O)."""
    prompt = (
        prompt_template.replace("{idea}", idea_text)
        .replace("{strategy}", strategy_text)
        .replace("{standards}", standards_text)
    )
    fields = {
        "idea_ref": f"idea://{idea_doc['id']}",
        "input_hash": canonical_doc_hash(idea_doc),
        "prompt_version": PROMPT_VERSION,
        "prompt_pack_hash": prompt_pack_hash,
        "policy_version": POLICY_VERSION,
        "strategy_hash": sha256_bytes(strategy_text.encode("utf-8")),
        "standards_hash": sha256_bytes(standards_text.encode("utf-8")),
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    return {"brief_id": brief_identity(fields), **fields, "prompt": prompt}


def render_briefs(
    workspace: Path,
    contracts_dir: Path,
    prompts_dir: Path,
    *,
    idea_id: str | None = None,
) -> dict[str, Any]:
    """Deterministically render briefs for the workspace's idea cards.

    Re-running on unchanged inputs is a byte-level no-op; a changed
    input yields a NEW brief while the old one stays (immutable
    evidence). An existing file whose bytes diverge from the fresh
    render under the same id is tampering — a typed error, no write.
    """
    pack_path = prompts_dir / "prioritizer" / "v1" / "prompt.md"
    prompt_template = pack_path.read_text(encoding="utf-8")
    prompt_pack_hash = sha256_bytes(pack_path.read_bytes())
    strategy_text = (workspace / "strategy.md").read_text(encoding="utf-8")
    standards_text = (workspace / "standards.md").read_text(encoding="utf-8")
    validators = load_validators(contracts_dir)

    idea_paths = sorted((workspace / "ideas").glob("*.yaml"))
    briefs: list[dict[str, str]] = []
    for idea_path in idea_paths:
        idea = load_doc(idea_path)
        if idea.kind != "idea":
            continue
        if idea_id is not None and idea.data.get("id") != idea_id:
            continue
        brief = build_brief(
            idea.data,
            idea_text=ws.dump_yaml(idea.data),
            prompt_template=prompt_template,
            prompt_pack_hash=prompt_pack_hash,
            strategy_text=strategy_text,
            standards_text=standards_text,
        )
        findings = check_schema(
            Doc(path=briefs_dir(workspace), kind="evaluation-brief", data=brief),
            validators,
        )
        if findings:
            raise HarnessError(
                "refusing to write invalid brief: "
                + "; ".join(f.message for f in findings)
            )
        path = briefs_dir(workspace) / f"{brief['brief_id'].lower()}.yaml"
        content = ws.dump_yaml(brief)
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise HarnessError(
                    f"{path}: existing brief bytes diverge from a fresh "
                    "render under the same brief_id (tampering?)"
                )
        else:
            ws.write_atomic(path, content)
        briefs.append(
            {
                "brief_id": brief["brief_id"],
                "idea_ref": brief["idea_ref"],
                "path": str(path),
            }
        )
    return {"ok": True, "briefs": briefs}
```

(Импорт: `from .loader import Doc, load_doc` вверху модуля.)

- [ ] **Step 4: Прогнать тесты** → PASS все новые + полный сьют, ruff,
  pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/harness.py tests/test_harness.py
git commit -m "feat: identity brief'а (prompt_hash в кортеже) и детерминированный render"
```

---

### Task 4: Кросс-чеки BRIEF_IDENTITY и ASSESS_BRIEF

**Files:**
- Modify: `src/impresario/checks.py`
- Test: `tests/test_bundle_checks.py`

**Interfaces:**
- Consumes: `harness.brief_identity`, `harness.sha256_bytes`
  (импортировать в checks.py из `.harness` — модуль без тяжёлых
  зависимостей, цикла импорта нет: harness не импортирует checks).
- Produces: `check_briefs(docs) -> list[Finding]` (код `BRIEF_IDENTITY`),
  `check_assessment_provenance(docs) -> list[Finding]` (код
  `ASSESS_BRIEF`); оба в `run_bundle_checks`.

- [ ] **Step 1: Failing-тесты**

В `tests/test_bundle_checks.py`:

```python
def _brief_doc() -> Doc:
    from impresario.harness import brief_identity, sha256_bytes

    prompt = "оцени идею\n"
    fields = {
        "idea_ref": "idea://IDEA-001",
        "input_hash": "sha256:" + "a" * 64,
        "prompt_version": "prioritizer/v1",
        "prompt_pack_hash": "sha256:" + "b" * 64,
        "policy_version": "scoring/v1",
        "strategy_hash": "sha256:" + "c" * 64,
        "standards_hash": "sha256:" + "d" * 64,
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    data = {"brief_id": brief_identity(fields), **fields, "prompt": prompt}
    return Doc(path=Path("brf.yaml"), kind="evaluation-brief", data=data)


def test_brief_identity_clean(bundle: list[Doc]) -> None:
    assert "BRIEF_IDENTITY" not in _codes([*bundle, _brief_doc()])


def test_brief_identity_tampered_prompt(bundle: list[Doc]) -> None:
    doc = _brief_doc()
    data = dict(doc.data, prompt=doc.data["prompt"] + "инъекция\n")
    docs = [*bundle, Doc(path=doc.path, kind=doc.kind, data=data)]
    assert "BRIEF_IDENTITY" in _codes(docs)  # шаг 1: prompt_hash ≠ байты


def test_brief_identity_tampered_field(bundle: list[Doc]) -> None:
    doc = _brief_doc()
    data = dict(doc.data, policy_version="scoring/v2")
    docs = [*bundle, Doc(path=doc.path, kind=doc.kind, data=data)]
    assert "BRIEF_IDENTITY" in _codes(docs)  # шаг 2: brief_id ≠ пересчёт


def _assessment_with_provenance(brief: Doc) -> Doc:
    data = {
        "assessment_id": "ASMT-900",
        "idea_ref": brief.data["idea_ref"],
        "run_id": "RUN-900",
        "input_hash": brief.data["input_hash"],
        "policy_version": "scoring/v1",
        "evidence_refs": [],
        "fit_strategy": 4,
        "fit_market": 4,
        "fit_standards": 4,
        "strategy_blocker": False,
        "standards_blocker": False,
        "confidence": "medium",
        "evaluator": {
            "kind": "agent",
            "id": "claude",
            "model": "m",
            "prompt_version": brief.data["prompt_version"],
        },
        "evaluated_at": "2026-08-16T12:00:00Z",
        "provenance": {
            "brief_id": brief.data["brief_id"],
            "prompt_pack_hash": brief.data["prompt_pack_hash"],
            "strategy_hash": brief.data["strategy_hash"],
            "standards_hash": brief.data["standards_hash"],
        },
    }
    return Doc(path=Path("asmt-900.yaml"), kind="axis-assessment", data=data)


def test_assess_brief_clean(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    docs = [*bundle, brief, _assessment_with_provenance(brief)]
    assert "ASSESS_BRIEF" not in _codes(docs)


def test_assess_brief_dangling(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    docs = [*bundle, _assessment_with_provenance(brief)]  # brief не включён
    assert "ASSESS_BRIEF" in _codes(docs)


def test_assess_brief_hash_mismatch(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    asmt = _assessment_with_provenance(brief)
    data = dict(asmt.data)
    data["provenance"] = dict(data["provenance"], strategy_hash="sha256:" + "9" * 64)
    docs = [*bundle, brief, Doc(path=asmt.path, kind=asmt.kind, data=data)]
    assert "ASSESS_BRIEF" in _codes(docs)


def test_assess_brief_input_hash_mismatch(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    asmt = _assessment_with_provenance(brief)
    data = dict(asmt.data, input_hash="sha256:" + "9" * 64)
    docs = [*bundle, brief, Doc(path=asmt.path, kind=asmt.kind, data=data)]
    assert "ASSESS_BRIEF" in _codes(docs)


def test_assess_brief_skips_manual_v0(bundle: list[Doc]) -> None:
    brief = _brief_doc()
    asmt = _assessment_with_provenance(brief)
    data = {k: v for k, v in asmt.data.items() if k != "provenance"}
    docs = [*bundle, Doc(path=asmt.path, kind=asmt.kind, data=data)]
    assert "ASSESS_BRIEF" not in _codes(docs)
```

- [ ] **Step 2: Убедиться, что падают** → FAIL (кодов нет).

- [ ] **Step 3: Реализация в checks.py**

Перед `run_bundle_checks`:

```python
def check_briefs(docs: list[Doc]) -> list[Finding]:
    """BRIEF_IDENTITY: prompt_hash matches the prompt bytes, and
    brief_id matches the recompute over the identity fields (incl.
    prompt_hash) — both layers, per the spec review 2026-08-16."""
    from .harness import brief_identity, sha256_bytes

    findings: list[Finding] = []
    for doc in docs:
        if doc.kind != "evaluation-brief":
            continue
        data = doc.data
        prompt = data.get("prompt")
        actual_prompt_hash = (
            sha256_bytes(prompt.encode("utf-8")) if isinstance(prompt, str) else None
        )
        if actual_prompt_hash != data.get("prompt_hash"):
            findings.append(
                Finding(
                    code="BRIEF_IDENTITY",
                    path=str(doc.path),
                    message="prompt_hash does not match the prompt bytes",
                )
            )
            continue
        try:
            expected = brief_identity(data)
        except KeyError as exc:
            findings.append(
                Finding(
                    code="BRIEF_IDENTITY",
                    path=str(doc.path),
                    message=f"missing identity field {exc}",
                )
            )
            continue
        if expected != data.get("brief_id"):
            findings.append(
                Finding(
                    code="BRIEF_IDENTITY",
                    path=str(doc.path),
                    message=(
                        f"brief_id {data.get('brief_id')} != recomputed {expected}"
                    ),
                )
            )
    return findings


def check_assessment_provenance(docs: list[Doc]) -> list[Finding]:
    """ASSESS_BRIEF: the assessment -> brief chain holds in the bundle.

    Assessments without provenance (manual-v0 and older) are skipped.
    brief_id stays a plain id (no new ref scheme) — the resolution is
    explicit here.
    """
    findings: list[Finding] = []
    briefs = {d.data.get("brief_id"): d for d in docs if d.kind == "evaluation-brief"}
    for doc in docs:
        if doc.kind != "axis-assessment":
            continue
        provenance = doc.data.get("provenance")
        if not isinstance(provenance, dict):
            continue

        def err(message: str, *, _path: str = str(doc.path)) -> None:
            findings.append(Finding(code="ASSESS_BRIEF", path=_path, message=message))

        brief = briefs.get(provenance.get("brief_id"))
        if brief is None:
            err(
                f"provenance.brief_id {provenance.get('brief_id')} does not "
                "resolve to an EvaluationBrief in this bundle"
            )
            continue
        for field in ("prompt_pack_hash", "strategy_hash", "standards_hash"):
            if provenance.get(field) != brief.data.get(field):
                err(f"provenance.{field} != brief {field}")
        if doc.data.get("input_hash") != brief.data.get("input_hash"):
            err("assessment input_hash != brief input_hash")
        evaluator = doc.data.get("evaluator") or {}
        if evaluator.get("prompt_version") != brief.data.get("prompt_version"):
            err("evaluator.prompt_version != brief prompt_version")
    return findings
```

В `run_bundle_checks` перед `return`:

```python
    findings.extend(check_briefs(docs))
    findings.extend(check_assessment_provenance(docs))
```

В `_KIND_TO_SCHEME` добавить псевдосхемы для known-set (не разрешимые,
как run/loop):

```python
    # brief:// / answer:// are NOT resolvable ref schemes; known-set only.
    "evaluation-brief": "brief",
    "assessment-answer": "answer",
```

и в `_ID_FIELDS` добавить `"brief_id"` (перед `"id"` не обязательно —
кортеж расширить: `("loop_id", "brief_id", "id", ...)`).

- [ ] **Step 4: Прогнать тесты** → PASS все; полный сьют, ruff, pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/checks.py tests/test_bundle_checks.py
git commit -m "feat: кросс-чеки BRIEF_IDENTITY (двухслойный) и ASSESS_BRIEF"
```

---

### Task 5: Двухфазный ingest

**Files:**
- Modify: `src/impresario/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: Task 3 (`render_briefs`, `brief_identity`, `briefs_dir`);
  `ws.single_writer_lock`, `ws.next_id`, `ws.assessments_dir`,
  `ws.write_atomic`, `ws.dump_yaml`, `ws.WorkspaceError`.
- Produces: `ingest_pairs(workspace, contracts_dir, *, run_id, actor,
  model, pairs: list[tuple[Path, Path]], now_iso: str) -> dict` —
  отчёт `{"ok": True, "written": [...], "noop": [...]}`; typed-ошибки
  `HarnessError` с текстами, содержащими `STALE_INPUT` /
  `ASSESS_CONFLICT` / `BRIEF_IDENTITY` соответственно.

- [ ] **Step 1: Failing-тесты**

В `tests/test_harness.py` (хелпер: `_good_answer()` возвращает dict как
`answer-full.yaml` из Task 1, но без standards_blocker: `False/False`
без ref'ов; `_do_render(ws)` — рендер и возврат пути brief'а;
`_write_answer(tmp_path, data)` — dump в yaml, возврат пути):

```python
NOW = "2026-08-16T12:00:00Z"


def _good_answer() -> dict:
    return {
        "schema_version": "assessment-answer/v1",
        "fit_strategy": 5,
        "fit_market": "unknown",
        "fit_standards": 4,
        "strategy_blocker": False,
        "standards_blocker": False,
        "rationale": {
            "fit_strategy": "Прямое попадание в G-1.",
            "fit_market": "Замеров нет — честный unknown.",
            "fit_standards": "Соответствует STD-1.",
        },
        "evidence_refs": ["strategy://ecosystem/2026/G-1"],
        "confidence": "medium",
    }


def _ingest(ws_path: Path, pairs: list[tuple[Path, Path]], **kw):
    from impresario.harness import ingest_pairs

    defaults = dict(
        run_id="RUN-100", actor="claude", model="claude-fable-5", now_iso=NOW
    )
    defaults.update(kw)
    return ingest_pairs(ws_path, CONTRACTS_DIR, pairs=pairs, **defaults)


def test_ingest_happy_materializes_valid_assessment(
    assess_ws: Path, tmp_path: Path
) -> None:
    from impresario.cli import validate_paths
    from impresario.harness import render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    answer_path = tmp_path / "answer.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = _ingest(assess_ws, [(brief_path, answer_path)])
    assert result["ok"] and len(result["written"]) == 1

    asmt = load_doc(Path(result["written"][0]["path"]))
    assert asmt.kind == "axis-assessment"
    assert asmt.data["assessment_id"] == "ASMT-001"
    assert asmt.data["run_id"] == "RUN-100"
    assert asmt.data["input_hash"] == load_doc(brief_path).data["input_hash"]
    assert asmt.data["evaluator"] == {
        "kind": "agent",
        "id": "claude",
        "model": "claude-fable-5",
        "prompt_version": "prioritizer/v1",
    }
    assert asmt.data["provenance"]["brief_id"] == report["briefs"][0]["brief_id"]
    # собственный выход проходит контракты и бандл-чеки workspace
    bundle = validate_paths([assess_ws], CONTRACTS_DIR, bundle=True)
    assert bundle.ok, [f"{f.code}: {f.message}" for f in bundle.errors]


def test_ingest_stale_input(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    idea_path = assess_ws / "ideas" / "idea-001.yaml"
    idea_path.write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, hypothesis="changed"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(HarnessError, match="STALE_INPUT"):
        _ingest(assess_ws, [(brief_path, answer_path)])
    assert not list((assess_ws / "assessments").glob("*.yaml"))


def test_ingest_tampered_brief(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    doc = yaml.safe_load(brief_path.read_text(encoding="utf-8"))
    doc["prompt"] += "инъекция\n"
    tampered = tmp_path / "brief.yaml"
    tampered.write_text(yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(HarnessError, match="BRIEF_IDENTITY"):
        _ingest(assess_ws, [(tampered, answer_path)])


def test_ingest_invalid_answer_writes_nothing(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    bad = dict(_good_answer(), input_hash="sha256:" + "a" * 64)  # bookkeeping
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(HarnessError):
        _ingest(assess_ws, [(brief_path, answer_path)])
    assert not list((assess_ws / "assessments").glob("*.yaml"))


def test_ingest_idempotent_retry_and_conflict(assess_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError, render_briefs

    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    brief_path = Path(report["briefs"][0]["path"])
    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    first = _ingest(assess_ws, [(brief_path, answer_path)])
    written_path = Path(first["written"][0]["path"])
    bytes_before = written_path.read_bytes()

    retry = _ingest(
        assess_ws, [(brief_path, answer_path)], now_iso="2026-08-16T13:00:00Z"
    )
    assert retry["written"] == [] and len(retry["noop"]) == 1
    assert written_path.read_bytes() == bytes_before  # первый evaluated_at жив

    divergent = dict(_good_answer(), confidence="low")
    answer2 = tmp_path / "b.yaml"
    answer2.write_text(yaml.safe_dump(divergent, allow_unicode=True), encoding="utf-8")
    with pytest.raises(HarnessError, match="ASSESS_CONFLICT"):
        _ingest(assess_ws, [(brief_path, answer2)])
    with pytest.raises(HarnessError, match="ASSESS_CONFLICT"):
        _ingest(assess_ws, [(brief_path, answer_path)], actor="другой")


def test_ingest_phase1_error_writes_nothing_for_any_pair(
    assess_ws: Path, tmp_path: Path
) -> None:
    """Вторая пара бита → не записана и первая (двухфазность)."""
    from impresario.harness import HarnessError, render_briefs

    (assess_ws / "ideas" / "idea-002.yaml").write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, id="IDEA-002", title="Second"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert len(report["briefs"]) == 2
    good_answer = tmp_path / "good.yaml"
    good_answer.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    bad_answer = tmp_path / "bad.yaml"
    bad_answer.write_text("schema_version: assessment-answer/v1\n", encoding="utf-8")
    pairs = [
        (Path(report["briefs"][0]["path"]), good_answer),
        (Path(report["briefs"][1]["path"]), bad_answer),
    ]
    with pytest.raises(HarnessError):
        _ingest(assess_ws, pairs)
    assert not list((assess_ws / "assessments").glob("*.yaml"))


def test_ingest_recovery_after_partial_write(
    assess_ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сбой между записями пар: повтор дозаписывает без дублей."""
    import impresario.harness as harness_mod
    from impresario.harness import render_briefs

    (assess_ws / "ideas" / "idea-002.yaml").write_text(
        yaml.safe_dump(
            dict(IDEA_DOC, id="IDEA-002", title="Second"),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    report = render_briefs(assess_ws, CONTRACTS_DIR, PROMPTS_DIR)
    answers = []
    for i in (0, 1):
        p = tmp_path / f"a{i}.yaml"
        p.write_text(
            yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
        )
        answers.append(p)
    pairs = [
        (Path(report["briefs"][0]["path"]), answers[0]),
        (Path(report["briefs"][1]["path"]), answers[1]),
    ]

    original = harness_mod._write_assessment
    calls = {"n": 0}

    def flaky(path, content):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated crash mid commit phase")
        original(path, content)

    monkeypatch.setattr(harness_mod, "_write_assessment", flaky)
    with pytest.raises(OSError):
        _ingest(assess_ws, pairs)
    assert len(list((assess_ws / "assessments").glob("*.yaml"))) == 1

    monkeypatch.setattr(harness_mod, "_write_assessment", original)
    result = _ingest(assess_ws, pairs)
    assert len(result["noop"]) == 1 and len(result["written"]) == 1
    assert len(list((assess_ws / "assessments").glob("*.yaml"))) == 2
```

- [ ] **Step 2: Убедиться, что падают** → FAIL.

- [ ] **Step 3: Реализация ingest в harness.py**

```python
def _write_assessment(path: Path, content: str) -> None:
    """Seam for crash-simulation tests; delegates to atomic write."""
    ws.write_atomic(path, content)


def _load_yaml(path: Path) -> dict[str, Any]:
    doc = load_doc(path)
    return doc.data


def _candidate_assessment(
    brief: dict[str, Any],
    answer: dict[str, Any],
    *,
    run_id: str,
    actor: str,
    model: str,
) -> dict[str, Any]:
    """AxisAssessment without assessment_id/evaluated_at (identity-free)."""
    candidate: dict[str, Any] = {
        "idea_ref": brief["idea_ref"],
        "run_id": run_id,
        "input_hash": brief["input_hash"],
        "policy_version": brief["policy_version"],
        "evidence_refs": answer["evidence_refs"],
        "fit_strategy": answer["fit_strategy"],
        "fit_market": answer["fit_market"],
        "fit_standards": answer["fit_standards"],
        "strategy_blocker": answer["strategy_blocker"],
        "standards_blocker": answer["standards_blocker"],
        "rationale": answer["rationale"],
        "confidence": answer["confidence"],
        "evaluator": {
            "kind": "agent",
            "id": actor,
            "model": model,
            "prompt_version": brief["prompt_version"],
        },
        "provenance": {
            "brief_id": brief["brief_id"],
            "prompt_pack_hash": brief["prompt_pack_hash"],
            "strategy_hash": brief["strategy_hash"],
            "standards_hash": brief["standards_hash"],
        },
    }
    for key in ("strategy_blocker_ref", "standards_blocker_ref"):
        if key in answer:
            candidate[key] = answer[key]
    return candidate


def _strip_identity(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k not in ("assessment_id", "evaluated_at")}


def ingest_pairs(
    workspace: Path,
    contracts_dir: Path,
    *,
    run_id: str,
    actor: str,
    model: str,
    pairs: list[tuple[Path, Path]],
    now_iso: str,
) -> dict[str, Any]:
    """Two-phase ingest under the single-writer lock (spec §assess ingest).

    Phase 1 validates EVERY pair (brief schema + identity recompute,
    STALE_INPUT against the current card, answer schema, in-call
    duplicates, (run_id, brief_id) idempotency/conflicts) and writes
    nothing on any failure. Phase 2 materializes the whole set;
    a crash mid-phase is recovered by re-running the same call —
    already-written pairs become no-ops.
    """
    try:
        with ws.single_writer_lock(workspace):
            return _ingest_locked(
                workspace,
                contracts_dir,
                run_id=run_id,
                actor=actor,
                model=model,
                pairs=pairs,
                now_iso=now_iso,
            )
    except ws.WorkspaceError as exc:
        raise HarnessError(str(exc)) from exc


def _ingest_locked(
    workspace: Path,
    contracts_dir: Path,
    *,
    run_id: str,
    actor: str,
    model: str,
    pairs: list[tuple[Path, Path]],
    now_iso: str,
) -> dict[str, Any]:
    from .loader import Doc

    validators = load_validators(contracts_dir)
    existing_docs = (
        [load_doc(p) for p in sorted(ws.assessments_dir(workspace).glob("*.yaml"))]
        if ws.assessments_dir(workspace).is_dir()
        else []
    )
    existing_by_key = {
        (d.data.get("run_id"), (d.data.get("provenance") or {}).get("brief_id")): d
        for d in existing_docs
        if d.kind == "axis-assessment"
    }

    seen_brief_ids: set[str] = set()
    to_write: list[dict[str, Any]] = []
    noops: list[dict[str, str]] = []

    # -------- фаза 1: только чтение и проверки --------
    for brief_path, answer_path in pairs:
        brief_doc = load_doc(brief_path)
        if brief_doc.kind != "evaluation-brief":
            raise HarnessError(f"{brief_path}: not an evaluation-brief")
        findings = check_schema(brief_doc, validators)
        if findings:
            raise HarnessError(
                f"{brief_path}: invalid brief: "
                + "; ".join(f.message for f in findings)
            )
        brief = brief_doc.data
        if sha256_bytes(brief["prompt"].encode("utf-8")) != brief["prompt_hash"]:
            raise HarnessError(
                f"{brief_path}: BRIEF_IDENTITY: prompt bytes do not match prompt_hash"
            )
        if brief_identity(brief) != brief["brief_id"]:
            raise HarnessError(
                f"{brief_path}: BRIEF_IDENTITY: brief_id does not match the recompute"
            )
        if brief["brief_id"] in seen_brief_ids:
            raise HarnessError(f"duplicate brief {brief['brief_id']} in one invocation")
        seen_brief_ids.add(brief["brief_id"])

        idea_id = brief["idea_ref"].removeprefix("idea://")
        # Карточку ищем по её собственному id, не по имени файла:
        # имена файлов в workspace не законтрактованы.
        idea_docs = [
            d
            for d in (
                load_doc(p) for p in sorted(ws.ideas_dir(workspace).glob("*.yaml"))
            )
            if d.kind == "idea" and d.data.get("id") == idea_id
        ]
        if len(idea_docs) != 1:
            raise HarnessError(
                f"STALE_INPUT: {brief['idea_ref']} resolves to "
                f"{len(idea_docs)} card(s) in workspace (expected exactly 1)"
            )
        current_hash = canonical_doc_hash(idea_docs[0].data)
        if current_hash != brief["input_hash"]:
            raise HarnessError(
                f"STALE_INPUT: {brief['idea_ref']} changed since the brief "
                f"was rendered ({current_hash} != {brief['input_hash']})"
            )

        answer_doc = load_doc(answer_path)
        if answer_doc.kind != "assessment-answer":
            raise HarnessError(f"{answer_path}: not an assessment-answer")
        findings = check_schema(answer_doc, validators)
        if findings:
            raise HarnessError(
                f"{answer_path}: invalid answer: "
                + "; ".join(f.message for f in findings)
            )

        candidate = _candidate_assessment(
            brief, answer_doc.data, run_id=run_id, actor=actor, model=model
        )
        existing = existing_by_key.get((run_id, brief["brief_id"]))
        if existing is not None:
            if _strip_identity(existing.data) == candidate:
                noops.append(
                    {
                        "brief_id": brief["brief_id"],
                        "assessment_id": existing.data["assessment_id"],
                        "path": str(existing.path),
                    }
                )
                continue
            raise HarnessError(
                f"ASSESS_CONFLICT: ({run_id}, {brief['brief_id']}) already "
                f"materialized as {existing.data['assessment_id']} with a "
                "different answer/actor/model"
            )
        to_write.append(candidate)

    # -------- фаза 2: материализация набора --------
    existing_ids = {
        d.data["assessment_id"] for d in existing_docs if d.kind == "axis-assessment"
    }
    validator = validators["axis-assessment"]
    written: list[dict[str, str]] = []
    for candidate in to_write:
        assessment_id = ws.next_id("ASMT", existing_ids=existing_ids)
        existing_ids.add(assessment_id)
        full = {
            "assessment_id": assessment_id,
            **candidate,
            "evaluated_at": now_iso,
        }
        errors = sorted(validator.iter_errors(full), key=lambda e: list(e.path))
        if errors:
            raise HarnessError(
                "refusing to write invalid assessment: "
                + "; ".join(e.message for e in errors)
            )
        path = ws.assessments_dir(workspace) / f"{assessment_id.lower()}.yaml"
        _write_assessment(path, ws.dump_yaml(full))
        written.append(
            {
                "brief_id": candidate["provenance"]["brief_id"],
                "assessment_id": assessment_id,
                "path": str(path),
            }
        )
    return {"ok": True, "written": written, "noop": noops}
```

Примечание: `Doc` в импортах не нужен, если не используется — не
добавлять мёртвый импорт (ruff).

- [ ] **Step 4: Прогнать тесты** → PASS новые; полный сьют, ruff, pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/harness.py tests/test_harness.py
git commit -m "feat: двухфазный ingest — идемпотентность (run_id, brief_id), ASSESS_CONFLICT, recovery"
```

---

### Task 6: CLI assess render/ingest + документация

**Files:**
- Modify: `src/impresario/cli.py`
- Modify: `README.md` (раздел про харнесс + коды + счётчик тестов)
- Modify: `docs/semantics.md` (короткий раздел «Промпт-харнесс оценщика»)
- Modify: `TODO.md` (M2-хвост: prioritizer-половина закрыта)
- Modify: `pilot/friction-log.md` (в №5 дописать отметку о закрытии)
- Test: `tests/test_harness.py` (CLI-тесты)

**Interfaces:**
- Consumes: `harness.render_briefs`, `harness.ingest_pairs`,
  `harness.find_prompts_dir`, `harness.HarnessError`.
- Produces: подкоманды `impresario assess render|ingest`; JSON-отчёт в
  stdout; exit 0/2 (2 — usage/typed-ошибка, как у прочих команд:
  свериться с тем, как cli.py мапит LoopError/WorkspaceError, и
  сделать так же для HarnessError).

- [ ] **Step 1: Failing CLI-тесты**

```python
def test_cli_assess_render_and_ingest(assess_ws: Path, tmp_path: Path, capsys) -> None:
    import json as jsonlib

    from impresario.cli import main

    code = main(["assess", "render", str(assess_ws)])
    out = jsonlib.loads(capsys.readouterr().out)
    assert code == 0 and out["ok"] and len(out["briefs"]) == 1

    answer_path = tmp_path / "a.yaml"
    answer_path.write_text(
        yaml.safe_dump(_good_answer(), allow_unicode=True), encoding="utf-8"
    )
    code = main(
        [
            "assess",
            "ingest",
            str(assess_ws),
            "--run-id",
            "RUN-100",
            "--actor",
            "claude",
            "--model",
            "claude-fable-5",
            "--brief",
            out["briefs"][0]["path"],
            "--answer",
            str(answer_path),
        ]
    )
    out2 = jsonlib.loads(capsys.readouterr().out)
    assert code == 0 and out2["ok"] and len(out2["written"]) == 1


def test_cli_assess_ingest_error_is_exit_2(
    assess_ws: Path, tmp_path: Path, capsys
) -> None:
    from impresario.cli import main

    code = main(
        [
            "assess",
            "ingest",
            str(assess_ws),
            "--run-id",
            "RUN-100",
            "--actor",
            "a",
            "--model",
            "m",
            "--brief",
            str(tmp_path / "нет.yaml"),
            "--answer",
            str(tmp_path / "нет2.yaml"),
        ]
    )
    assert code == 2
```

(При написании свериться с существующими CLI-тестами в
`tests/test_loop.py` — как они читают stdout/exit; повторить идиому.
Если ошибки других команд печатают JSON `{"ok": false, "error": ...}` —
сделать так же.)

- [ ] **Step 2: Убедиться, что падают** → FAIL (нет подкоманды).

- [ ] **Step 3: Реализация в cli.py**

Парсер (рядом с другими подкомандами; `--brief`/`--answer` —
`action="append"`, количество обязано совпадать):

```python
    assess = subparsers.add_parser(
        "assess", help="prompt harness: render briefs / ingest answers"
    )
    assess_sub = assess.add_subparsers(dest="assess_command", required=True)
    a_render = assess_sub.add_parser(
        "render", help="deterministically render evaluation briefs"
    )
    a_render.add_argument("workspace", type=Path)
    a_render.add_argument("--idea", default=None)
    a_render.add_argument("--prompts", type=Path, default=None)
    a_render.add_argument("--contracts", type=Path, default=None)
    a_ingest = assess_sub.add_parser(
        "ingest", help="validate brief+answer pairs and materialize assessments"
    )
    a_ingest.add_argument("workspace", type=Path)
    a_ingest.add_argument("--run-id", required=True)
    a_ingest.add_argument("--actor", required=True)
    a_ingest.add_argument("--model", required=True)
    a_ingest.add_argument("--brief", action="append", required=True, type=Path)
    a_ingest.add_argument("--answer", action="append", required=True, type=Path)
    a_ingest.add_argument("--contracts", type=Path, default=None)
```

Обработчик (по образцу forconcept-ветки: try/except с JSON-ошибкой и
exit 2; `contracts` резолвится как у других команд через
`find_contracts_dir`, prompts — через `find_prompts_dir(workspace)` при
отсутствии `--prompts`; `now_iso` — тем же источником времени, что у
resume/gate — свериться и переиспользовать):

```python
if args.command == "assess":
    from .harness import (
        HarnessError,
        find_prompts_dir,
        ingest_pairs,
        render_briefs,
    )

    try:
        contracts = args.contracts or find_contracts_dir(args.workspace)
        if args.assess_command == "render":
            prompts = args.prompts or find_prompts_dir(args.workspace)
            report = render_briefs(
                args.workspace, contracts, prompts, idea_id=args.idea
            )
        else:
            if len(args.brief) != len(args.answer):
                raise HarnessError("--brief and --answer must come in pairs")
            report = ingest_pairs(
                args.workspace,
                contracts,
                run_id=args.run_id,
                actor=args.actor,
                model=args.model,
                pairs=list(zip(args.brief, args.answer, strict=True)),
                now_iso=_now_iso(),
            )
    except (HarnessError, FileNotFoundError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return EXIT_USAGE
    print(json.dumps(report, ensure_ascii=False))
    return 0
```

(`_now_iso` — использовать фактическое имя источника времени в cli.py;
если его нет — взять то, чем пользуется ветка forconcept resume.)

- [ ] **Step 4: Документация**

- `README.md`: раздел «Промпт-харнесс оценщика (prioritizer/v1)» после
  Stage 4: три команды (`assess render`, внешний LLM-вызов,
  `assess ingest`), ссылка на спеку; в таблицу кодов — строки
  `BRIEF_IDENTITY` («prompt_hash или brief_id брифа не совпадают с
  пересчётом») и `ASSESS_BRIEF` («цепь assessment → brief нарушена:
  висячий provenance.brief_id или расходящиеся хеши/версии»); счётчик
  тестов обновить фактическим числом из `uv run pytest`.
- `docs/semantics.md`: короткий раздел «Промпт-харнесс оценщика»
  (render+ingest, brief — immutable evidence, identity с prompt_hash,
  идемпотентность (run_id, brief_id), двухфазный ingest; ссылка на
  спеку).
- `TODO.md`: пункт M2-хвоста разбить: `[x]` prioritizer-половина
  (ссылка на спеку, «живой RUN-003 — отдельный человеческий акт»),
  `[ ]` researcher/creator-харнесс.
- `pilot/friction-log.md` №5: дописать в конец записи строку
  «**Закрыто (prioritizer) 2026-08-16:** харнесс render+ingest,
  prompt_version `prioritizer/v1`; см. спеку
  2026-08-16-prioritizer-prompt-harness-design.md. Живой RUN-003 — за
  человеком.» (append к записи — это living-лог, добавление отметки о
  закрытии — установленный паттерн).

- [ ] **Step 5: Прогнать всё**

`uv run pytest` (взять счётчик для README), ruff, pyrefly,
`uv run impresario validate contracts/examples/pp-001`,
`uv run impresario validate pilot/forconcept/pp-101`, плюс smoke:
`uv run impresario assess render pilot 2>/dev/null | head -c 200`
(должен выдать JSON с 8 briefs) — и **удалить** созданный
`pilot/briefs/` перед коммитом (`git status` чист: прогон по пилоту —
человеческий акт после мержа, тут только smoke):

```bash
rm -rf pilot/briefs
git status --short  # пусто, кроме задуманных файлов
```

- [ ] **Step 6: Commit**

```bash
git add src/impresario/cli.py tests/test_harness.py README.md docs/semantics.md TODO.md pilot/friction-log.md
git commit -m "feat: CLI assess render/ingest + документация харнесса"
```

---

### Task 7: Финальная верификация и PR

- [ ] **Step 1: Полная верификация**

```bash
uv run ruff format . && uv run ruff check .
uv run pyrefly check
uv run pytest
uv run impresario validate contracts/examples/pp-001
uv run impresario validate pilot/forconcept/pp-101
git status --short  # чисто
```

- [ ] **Step 2: Push и PR**

```bash
git push -u origin feat/prioritizer-harness
gh pr create --title "feat: промпт-харнесс оценщика prioritizer/v1 (render + ingest)" --body "Уход от manual-v0 (M2-хвост, friction №5): контракты evaluation-brief/v1 (immutable evidence, контент-адресованный brief_id с prompt_hash в identity) и assessment-answer/v1 (только суждение, дискриминатор schema_version), опциональный provenance в axis-assessment/v1 (расширение без смены \$id), промпт-пак prompts/prioritizer/v1 с уроками пилота (№3/№6/№15/№16), CLI assess render (детерминированный, байтовый no-op) и assess ingest (двухфазный под lock, идемпотентность (run_id, brief_id), ASSESS_CONFLICT, документированный recovery), кросс-чеки BRIEF_IDENTITY (двухслойный) и ASSESS_BRIEF.

Спека: docs/superpowers/specs/2026-08-16-prioritizer-prompt-harness-design.md

Живой RUN-003 — отдельный человеческий акт после мержа.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 3: Доложить** — ссылка на PR, мерж за человеком, после
  мержа доступен RUN-003 (`assess render pilot` → LLM → `assess ingest`).
