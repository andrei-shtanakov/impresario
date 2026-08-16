# Loop Agent Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Researcher/creator-харнесс forconcept-цикла: контракты
`stage-brief/v1`, `research-answer/v1`, `concept-answer/v1`, промпт-паки
двух ролей, граница раннера `iteration:N`, `SingleAnswerAgent`, CLI
`forconcept brief|step`, кросс-чек `ARTIFACT_BRIEF`.

**Architecture:** Новый модуль `src/impresario/loop_harness.py`
(деривация стадии, history-hash, identity/render stage-brief, протокол
step). step ничего не персистит сам — собирает артефакт и скармливает
существующему `run_loop` через `SingleAnswerAgent` с границами
`research:N` / новой `iteration:N`. Briefs — immutable evidence.

**Tech Stack:** Python 3.11+, jsonschema 2020-12, PyYAML, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-16-loop-agent-harness-design.md`
— обязательное чтение вместе с задачей.

## Global Constraints

- Только `uv`; после каждой задачи зелёные: `uv run pytest`,
  `uv run ruff format src tests contracts README.md && uv run ruff check .`
  (формат НЕ по docs/ — голый `ruff format .` портит python-фенсы в
  planах), `uv run pyrefly check`.
- Ветка `feat/loop-agent-harness` (существует, спека закоммичена).
- Существующие схемы менять ТОЛЬКО расширением: research-pack/v1 —
  опциональные `gaps[].answered_by` (паттерн
  `^research-pack://RP-[0-9]{3,}$`) и `provenance`; concept-draft/v1 —
  опциональный `provenance`. Ничего больше.
- Семантика существующих границ `stop_after` раннера не меняется;
  `iteration:N` — единственное изменение раннера.
- Детекция новых kinds — строго по значению `schema_version` (урок
  Task 1 prioritizer-плана).
- pilot/ не трогать; тесты строят tmp-workspace.
- Hash-формат `^sha256:[0-9a-f]{64}$`; `brief_id` stage-brief'а —
  `^SBR-[0-9a-f]{12}$`.
- Коммиты — трейлер `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Инварианты: ≥1 valid + ≥1 invalid fixture на контракт; ломающий тест
  на каждый новый кросс-чек.

---

### Task 1: Контракты stage-brief / research-answer / concept-answer, расширения RP/CD, loader

**Files:**
- Create: `contracts/stage-brief/v1/schema.json` (+ fixtures: valid
  `sbr-valid.yaml`; invalid `sbr-bad-role.yaml`, `sbr-missing-history-hash.yaml`, `sbr-extra-field.yaml`)
- Create: `contracts/research-answer/v1/schema.json` (+ fixtures: valid
  `ra-full.yaml`, `ra-gap-closed.yaml`; invalid `ra-no-discriminator-value.yaml` НЕ создавать (см. прим.), `ra-finding-no-source.yaml`, `ra-bookkeeping-field.yaml`)
- Create: `contracts/concept-answer/v1/schema.json` (+ fixtures: valid
  `ca-full.yaml`, `ca-single-path.yaml`; invalid `ca-empty-delta.yaml`, `ca-bookkeeping-field.yaml`)
- Modify: `contracts/research-pack/v1/schema.json` (gap `answered_by` + top-level `provenance`)
- Modify: `contracts/concept-draft/v1/schema.json` (top-level `provenance`)
- Create: `contracts/research-pack/v1/fixtures/valid/rp-with-provenance.yaml`
- Create: `contracts/concept-draft/v1/fixtures/valid/cd-with-provenance.yaml`
- Modify: `src/impresario/loader.py`
- Test: `tests/test_schema_fixtures.py`

Примечание: fixture «без дискриминатора» невозможна (load_doc не
типизирует) — как в prioritizer-плане, вместо неё targeted-тест
detect_kind (Step 1).

**Interfaces:**
- Produces: kinds `"stage-brief"`, `"research-answer"`,
  `"concept-answer"` в CONTRACT_KINDS; `detect_kind` по значениям
  `schema_version` (`stage-brief/v1` / `research-answer/v1` /
  `concept-answer/v1`). Все последующие задачи полагаются на имена.

- [ ] **Step 1: Failing-тесты детекции**

В конец `tests/test_schema_fixtures.py`:

```python
def test_detect_kind_loop_harness_discriminators() -> None:
    from impresario.loader import UnknownContractError, detect_kind

    assert detect_kind({"schema_version": "stage-brief/v1"}) == "stage-brief"
    assert (
        detect_kind({"schema_version": "research-answer/v1"})
        == "research-answer"
    )
    assert (
        detect_kind({"schema_version": "concept-answer/v1"})
        == "concept-answer"
    )
    with pytest.raises(UnknownContractError):
        detect_kind({"schema_version": "stage-brief/v0"})
```

- [ ] **Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_schema_fixtures.py -k loop_harness -v` → FAIL.

- [ ] **Step 3: loader**

В `CONTRACT_KINDS` после `"assessment-answer"` добавить
`"stage-brief", "research-answer", "concept-answer",`. В `detect_kind`
рядом с веткой assessment-answer:

```python
    schema_version = data.get("schema_version")
    if schema_version == "assessment-answer/v1":
        return "assessment-answer"
    if schema_version == "stage-brief/v1":
        return "stage-brief"
    if schema_version == "research-answer/v1":
        return "research-answer"
    if schema_version == "concept-answer/v1":
        return "concept-answer"
```

(заменив существующую одиночную ветку assessment-answer этим блоком).

- [ ] **Step 4: Схема stage-brief/v1**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:stage-brief:v1",
  "title": "StageBrief",
  "description": "Handoff render → executor для одной стадии forconcept-цикла (docs/superpowers/specs/2026-08-16-loop-agent-harness-design.md). Immutable evidence: brief_id контент-адресован (канонический хеш identity-полей, включая prompt_hash); freshness покрывает все входы промпта (идея, proposal, история). Ни timestamp, ни случайных ID.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "brief_id",
    "loop_id",
    "iteration",
    "role",
    "prompt_version",
    "prompt_pack_hash",
    "idea_input_hash",
    "proposal_hash",
    "history_hash",
    "prompt_hash",
    "prompt"
  ],
  "properties": {
    "schema_version": { "const": "stage-brief/v1" },
    "brief_id": { "type": "string", "pattern": "^SBR-[0-9a-f]{12}$" },
    "loop_id": { "type": "string", "pattern": "^LOOP-[0-9]{3,}$" },
    "iteration": { "type": "integer", "minimum": 0 },
    "role": { "enum": ["researcher", "creator"] },
    "prompt_version": { "type": "string", "minLength": 1 },
    "prompt_pack_hash": { "$ref": "#/$defs/sha256" },
    "idea_input_hash": { "$ref": "#/$defs/sha256" },
    "proposal_hash": { "$ref": "#/$defs/sha256" },
    "history_hash": { "$ref": "#/$defs/sha256" },
    "prompt_hash": { "$ref": "#/$defs/sha256" },
    "prompt": { "type": "string", "minLength": 1 }
  },
  "$defs": {
    "sha256": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" }
  }
}
```

- [ ] **Step 5: Схема research-answer/v1**

Формы полей — дословно из research-pack/v1 (`finding`, `constraint`
скопировать из его `$defs`, включая условие source_ref при
high/medium/low):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:research-answer:v1",
  "title": "ResearchAnswer",
  "description": "Только контент роли researcher: findings, constraints, gaps, brief_for_creator, requests. Bookkeeping (id, refs, iteration, produced_by, produced_at, provenance) авторит step (урок №15). schema_version — маркер формата.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "findings",
    "constraints",
    "gaps",
    "brief_for_creator",
    "requests_to_creator"
  ],
  "properties": {
    "schema_version": { "const": "research-answer/v1" },
    "findings": { "type": "array", "items": { "$ref": "#/$defs/finding" } },
    "constraints": { "type": "array", "items": { "$ref": "#/$defs/constraint" } },
    "gaps": { "type": "array", "items": { "$ref": "#/$defs/gap" } },
    "brief_for_creator": { "type": "string", "minLength": 1 },
    "requests_to_creator": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    }
  },
  "$defs": {
    "finding": { "<": "скопировать $defs.finding из research-pack/v1 дословно" },
    "constraint": { "<": "скопировать $defs.constraint из research-pack/v1 дословно" },
    "gap": {
      "type": "object",
      "additionalProperties": false,
      "required": ["what", "blocks_approval"],
      "properties": {
        "what": { "type": "string", "minLength": 1 },
        "needed": { "type": "string" },
        "blocks_approval": { "type": "boolean" },
        "closed": { "type": "boolean" },
        "answered_by": {
          "type": "string",
          "pattern": "^research-pack://RP-[0-9]{3,}$"
        }
      }
    }
  }
}
```

(Строки-«скопировать» — инструкция, не литерал: подставить реальные
JSON-объекты из research-pack/v1 перед записью.)

- [ ] **Step 6: Схема concept-answer/v1**

Формы — дословно из concept-draft/v1 (`assumption` из его `$defs`;
alternatives/chosen_direction — их формы):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:concept-answer:v1",
  "title": "ConceptAnswer",
  "description": "Только контент роли creator. Bookkeeping (id, refs, iteration, based_on_research, produced_by, produced_at, provenance) авторит step. schema_version — маркер формата.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "schema_version",
    "value_prop",
    "alternatives",
    "chosen_direction",
    "business_models",
    "assumptions",
    "requests_to_researcher",
    "proposal_delta"
  ],
  "properties": {
    "schema_version": { "const": "concept-answer/v1" },
    "value_prop": { "type": "string", "minLength": 1 },
    "alternatives": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["direction", "summary"],
        "properties": {
          "direction": { "type": "string", "minLength": 1 },
          "summary": { "type": "string", "minLength": 1 }
        }
      }
    },
    "chosen_direction": {
      "type": "object",
      "additionalProperties": false,
      "required": ["direction", "why"],
      "properties": {
        "direction": { "type": "string", "minLength": 1 },
        "why": { "type": "string", "minLength": 1 },
        "tentative": { "type": "boolean" }
      }
    },
    "business_models": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "assumptions": { "type": "array", "items": { "$ref": "#/$defs/assumption" } },
    "requests_to_researcher": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "proposal_delta": { "type": "string", "minLength": 1 },
    "single_path_justification": { "type": "string", "minLength": 1 }
  },
  "$defs": {
    "assumption": { "<": "скопировать $defs.assumption из concept-draft/v1 дословно" }
  }
}
```

- [ ] **Step 7: Расширения research-pack/v1 и concept-draft/v1**

research-pack/v1: в `$defs.gap.properties` (или где определён gap —
свериться со схемой; gap описан inline в `properties.gaps.items` —
проверить) добавить:

```json
        "answered_by": {
          "type": "string",
          "pattern": "^research-pack://RP-[0-9]{3,}$"
        }
```

В оба контракта (research-pack/v1 и concept-draft/v1) в `properties`
добавить (НЕ в required):

```json
    "provenance": {
      "type": "object",
      "additionalProperties": false,
      "required": ["brief_id", "prompt_pack_hash"],
      "properties": {
        "brief_id": { "type": "string", "pattern": "^SBR-[0-9a-f]{12}$" },
        "prompt_pack_hash": { "type": "string", "pattern": "^sha256:[0-9a-f]{64}$" }
      }
    }
```

- [ ] **Step 8: Fixtures**

`sbr-valid.yaml` (brief_id фиктивный по паттерну; identity-пересчёт —
дело кросс-чека Task 6, не схемы):

```yaml
schema_version: stage-brief/v1
brief_id: SBR-0123456789ab
loop_id: LOOP-001
iteration: 0
role: researcher
prompt_version: researcher/v1
prompt_pack_hash: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
idea_input_hash: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
proposal_hash: "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
history_hash: "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
prompt_hash: "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
prompt: |
  Исследуй идею. (fixture)
```

Invalid: `sbr-bad-role.yaml` (`role: evaluator`),
`sbr-missing-history-hash.yaml` (без history_hash),
`sbr-extra-field.yaml` (+`rendered_at`).

`ra-full.yaml`: полный контент (finding с source_ref + confidence high;
constraint kind internal; gap открытый blocks_approval true;
brief_for_creator; один request). `ra-gap-closed.yaml`: gap с
`closed: true` и `answered_by: "research-pack://RP-001"`. Invalid:
`ra-finding-no-source.yaml` (finding confidence high БЕЗ source_ref),
`ra-bookkeeping-field.yaml` (+`id: RP-001`).

`ca-full.yaml`: 3 альтернативы, chosen, assumption blocks_approval true,
delta. `ca-single-path.yaml`: 1 альтернатива +
`single_path_justification`. Invalid: `ca-empty-delta.yaml`
(`proposal_delta: ""`), `ca-bookkeeping-field.yaml` (+`produced_at`).

`rp-with-provenance.yaml` / `cd-with-provenance.yaml`: копии
существующих valid-fixtures + блок `provenance` (+ у rp — gap с
`answered_by`).

- [ ] **Step 9: Прогнать всё**

`uv run pytest tests/test_schema_fixtures.py -v` (новые параметры
появились, старые valid RP/CD без provenance зелёные) → полный сьют,
ruff (scoped), pyrefly.

- [ ] **Step 10: Commit**

```bash
git add contracts src/impresario/loader.py tests/test_schema_fixtures.py
git commit -m "feat: контракты stage-brief/research-answer/concept-answer, расширения RP/CD"
```

---

### Task 2: Промпт-паки researcher/v1 и creator/v1

**Files:**
- Create: `prompts/researcher/v1/prompt.md`, `prompts/creator/v1/prompt.md`
- Test: `tests/test_loop_harness.py` (новый)

**Interfaces:**
- Produces: два пака с плейсхолдерами `{idea}` `{proposal}` `{history}`
  и скелетами ответов; тест-пины скелетов к схемам.

- [ ] **Step 1: Failing-тесты**

`tests/test_loop_harness.py`:

```python
"""Researcher/creator-харнесс цикла (spec 2026-08-16-loop-agent-harness)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import CONTRACTS_DIR, REPO_ROOT

PROMPTS_DIR = REPO_ROOT / "prompts"


@pytest.mark.parametrize("role", ["researcher", "creator"])
def test_role_prompt_pack_placeholders(role: str) -> None:
    text = (PROMPTS_DIR / role / "v1" / "prompt.md").read_text(encoding="utf-8")
    for token in ("{idea}", "{proposal}", "{history}"):
        assert token in text
    assert f"{role}-answer/v1".replace("researcher", "research").replace(
        "creator", "concept"
    ) in text


@pytest.mark.parametrize(
    ("role", "contract"),
    [("researcher", "research-answer"), ("creator", "concept-answer")],
)
def test_role_prompt_pins_answer_schema(role: str, contract: str) -> None:
    schema = json.loads(
        (CONTRACTS_DIR / contract / "v1" / "schema.json").read_text(
            encoding="utf-8"
        )
    )
    text = (PROMPTS_DIR / role / "v1" / "prompt.md").read_text(encoding="utf-8")
    for field in schema["required"]:
        assert field in text, f"{role} prompt missing required field {field}"
```

- [ ] **Step 2: Убедиться, что падают** → FAIL (файлов нет).

- [ ] **Step 3: prompt.md ×2**

`prompts/researcher/v1/prompt.md` (плейсхолдеры подменяются однопроходно;
других фигурных скобок в файле быть не должно):

```markdown
# Researcher — forconcept-цикл — researcher/v1

Ты — researcher двухагентного цикла product-governance. Твоя задача на
эту итерацию: собрать research pack по идее с учётом текущего proposal
и всей истории цикла ниже. Ответ материализует детерминированный
инструмент; ты авторишь только контент.

## Правила

1. Findings: каждое утверждение с confidence high/medium/low обязано
   иметь конкретный `source_ref`; без источника — только
   `confidence: unknown`. Выдуманные и «примерные» ссылки запрещены;
   лучше честный пробел, чем правдоподобная выдумка.
2. Актуальность: прежде чем цитировать подтверждающее evidence,
   проверь по материалам, нет ли более ПОЗДНЕЙ отменяющей записи;
   отменённое позже решение — не evidence.
3. Gaps: честно фиксируй пробелы; `blocks_approval: true` — только для
   действительно блокирующих. Закрывать прежний gap можно только с
   `closed: true` и `answered_by` — ссылкой на research pack, где лежит
   ответ.
4. Отработай запросы creator'а из истории (requests_to_researcher его
   последнего concept draft), если они есть.
5. `brief_for_creator` — концентрированная выжимка для creator'а, не
   пересказ всего пака.

## Формат ответа

Верни РОВНО один YAML-документ (без Markdown-ограждений):

schema_version: research-answer/v1
findings:
  - claim: "<...>"
    source_ref: "<источник>"
    confidence: <high | medium | low | unknown>
constraints:
  - kind: <regulatory | standard | strategy | internal | other>
    statement: "<...>"
    source_ref: "<источник, опционально>"
gaps:
  - what: "<...>"
    blocks_approval: <true | false>
brief_for_creator: "<...>"
requests_to_creator:
  - "<...>"

Не добавляй других полей: идентификаторы, ссылки на proposal, номера
итераций и метки времени авторит инструмент, не ты.

## Идея

{idea}

## Текущий proposal

{proposal}

## История цикла (research packs и concept drafts по порядку)

{history}
```

`prompts/creator/v1/prompt.md` — той же структуры; правила creator:
(1) ≥3 содержательных альтернатив, либо одна + явный
`single_path_justification`; (2) assumptions честные, `blocks_approval`
только для блокирующих, `answered_by` — только со ссылкой на research
pack, реально отвечающий на допущение; (3) `proposal_delta` —
концентрированное изменение proposal, не пересказ; (4) отработай
`requests_to_creator` из свежего research pack; (5) `value_prop` —
одна-две фразы ценности. Скелет ответа — все required-поля
concept-answer/v1 (`schema_version: concept-answer/v1`, value_prop,
alternatives (direction/summary), chosen_direction (direction/why),
business_models, assumptions (text/blocks_approval), 
requests_to_researcher, proposal_delta; упомянуть опциональные
`single_path_justification`, `answered_by`, `tentative`). Плейсхолдеры
`{idea}` `{proposal}` `{history}` в том же порядке.

- [ ] **Step 4: Прогнать** → PASS; полный сьют, ruff (scoped), pyrefly.

- [ ] **Step 5: Commit**

```bash
git add prompts tests/test_loop_harness.py
git commit -m "feat: промпт-паки researcher/v1 и creator/v1 со скелетами, пинованными к схемам"
```

---

### Task 3: Граница раннера iteration:N и SingleAnswerAgent

**Files:**
- Modify: `src/impresario/loop.py` (одна вставка после NEEDS_HUMAN-ветки)
- Modify: `src/impresario/agents.py` (SingleAnswerAgent)
- Modify: `src/impresario/cli.py` (help-строка stop-after — упомянуть iteration:N)
- Test: `tests/test_loop.py`, `tests/test_loop_harness.py`

**Interfaces:**
- Produces: `stop_after=f"iteration:{N}"` — пауза ПОСЛЕ полного
  evaluate-перехода (терминальные вердикты материализованы и возвращены
  как есть; continue → `LoopResult(verdict=PAUSED)` перед researcher
  N+1); `SingleAnswerAgent(role: str, iteration: int, doc: dict)` —
  `Agent`, отдающий doc ровно для (role, iteration), typed `AgentError`
  на любом другом вызове.

- [ ] **Step 1: Failing-тесты**

В `tests/test_loop.py`:

```python
def test_stop_after_iteration_boundary(loop_ws: Path) -> None:
    """iteration:N — пауза ПОСЛЕ evaluate: continue → paused перед
    researcher N+1; терминальный вердикт возвращается материализованным."""
    from impresario.loop import run_loop
    from impresario.agents import ScriptedAgent

    result = run_loop(
        loop_ws,
        CONTRACTS_DIR,
        ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW,
        stop_after="iteration:0",
    )
    assert result.verdict == "paused"
    # continue-вердикт итерации 0 уже в trace, delta применена
    events = [e["event"] for e in _trace_events(loop_ws)]
    assert "verdict" in events and "delta_applied" in events
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"] is None  # не терминальная пауза

    # терминальная итерация: iteration:1 у HAPPY возвращает READY
    result = run_loop(
        loop_ws,
        CONTRACTS_DIR,
        ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW,
        stop_after="iteration:1",
    )
    assert result.verdict == "ready_for_business"
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"]["verdict"] == "ready_for_business"  # материализован


def test_single_answer_agent_contract() -> None:
    from impresario.agents import AgentError, SingleAnswerAgent

    doc = {"id": "RP-001"}
    agent = SingleAnswerAgent("researcher", 0, doc)
    assert agent.produce("researcher", 0) is doc
    with pytest.raises(AgentError, match="researcher.*1"):
        agent.produce("researcher", 1)
    with pytest.raises(AgentError, match="creator"):
        agent.produce("creator", 0)
```

- [ ] **Step 2: Убедиться, что падают** → FAIL.

- [ ] **Step 3: Реализация**

`loop.py`: в теле итерации, ПОСЛЕ ветки `if verdict == NEEDS_HUMAN: ...
return` (обе терминальные ветки возвращаются раньше и границы не
касаются), добавить последней строкой тела:

```python
        # iteration:N pauses AFTER the full evaluate transition (spec
        # 2026-08-16-loop-agent-harness): terminal verdicts returned
        # above are already materialized; a continue verdict pauses
        # right before the next iteration's researcher call — the
        # boundary step(creator) needs. evaluate:N (the crash-test
        # boundary BEFORE terminal effects) is intentionally unchanged.
        if stop_after == f"iteration:{iteration}":
            return paused(iteration)
```

`agents.py`:

```python
class SingleAnswerAgent:
    """Serves exactly one pre-built artifact for one (role, iteration).

    The step harness feeds the runner through this agent so the runner
    stays the sole executor of loop semantics; any unexpected call is a
    typed error (unreachable under the harness's stop_after boundaries).
    """

    def __init__(self, role: str, iteration: int, doc: dict[str, Any]) -> None:
        self._role = role
        self._iteration = iteration
        self._doc = doc

    def produce(self, role: str, iteration: int) -> dict[str, Any]:
        """Return the single answer document or fail typed."""
        if role != self._role or iteration != self._iteration:
            raise AgentError(
                f"single-answer agent holds {self._role}:{self._iteration}, "
                f"got unexpected call {role}:{iteration}"
            )
        return self._doc
```

`cli.py`: в help `--stop-after` forconcept run добавить `iteration:N`.

- [ ] **Step 4: Прогнать** — новые + ВСЕ существующие loop-тесты
  (семантика evaluate:N не изменилась) → полный сьют, ruff, pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/loop.py src/impresario/agents.py src/impresario/cli.py tests/test_loop.py
git commit -m "feat: граница раннера iteration:N (после terminal effects) и SingleAnswerAgent"
```

---

### Task 4: loop_harness — деривация стадии, history-hash, identity и render stage-brief

**Files:**
- Create: `src/impresario/loop_harness.py`
- Test: `tests/test_loop_harness.py`

**Interfaces:**
- Consumes: `harness.sha256_bytes`, `harness.find_prompts_dir`,
  `harness.HarnessError` (переиспользовать — не дублировать);
  `hashing.canonical_doc_hash`; `loop._docs_of_kind`,
  `loop._find_iteration`, `loop.state_path` (внутрипакетный импорт —
  допустим, зафиксировать комментарием); `workspace.dump_yaml/write_atomic`.
- Produces:
  `derive_next_call(workspace, contracts_dir) -> tuple[str, int]` —
  (role, iteration) следующего ожидаемого вызова агента; typed
  `HarnessError` с маркерами `TERMINAL` / `NEEDS_HUMAN` /
  `EVALUATOR_PENDING`, когда вызова агента нет;
  `history_entries(workspace) -> list[dict]` (порядок (iteration, role,
  id), researcher < creator) и `history_hash(entries) -> str`;
  `stage_brief_identity(fields) -> str` (`SBR-<12hex>`);
  `render_stage_brief(workspace, contracts_dir, prompts_dir) -> dict`
  (отчёт `{brief_id, role, iteration, path}`); `loop_briefs_dir(ws)`.

- [ ] **Step 1: Failing-тесты**

В `tests/test_loop_harness.py` (фикстура `loop_ws` реэкспортируется из
tests/test_loop.py — импортировать как в test_gates.py; HAPPY_SCRIPT,
STUCK_SCRIPT, `_run`, NOW — оттуда же):

```python
from .test_loop import (  # noqa: F401 - fixture reuse
    HAPPY_SCRIPT,
    NOW,
    STUCK_SCRIPT,
    loop_ws,
)
from .test_loop import _run as run_scripted


def test_derive_next_call_walks_the_stages(loop_ws: Path) -> None:
    from impresario.harness import HarnessError
    from impresario.loop import run_loop
    from impresario.agents import ScriptedAgent
    from impresario.loop_harness import derive_next_call

    assert derive_next_call(loop_ws, CONTRACTS_DIR) == ("researcher", 0)

    run_loop(
        loop_ws, CONTRACTS_DIR, ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW, stop_after="research:0",
    )
    assert derive_next_call(loop_ws, CONTRACTS_DIR) == ("creator", 0)

    run_loop(
        loop_ws, CONTRACTS_DIR, ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW, stop_after="iteration:0",
    )
    assert derive_next_call(loop_ws, CONTRACTS_DIR) == ("researcher", 1)


def test_derive_next_call_terminal_and_hold(loop_ws: Path) -> None:
    from impresario.harness import HarnessError
    from impresario.loop_harness import derive_next_call

    result = run_scripted(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    with pytest.raises(HarnessError, match="NEEDS_HUMAN"):
        derive_next_call(loop_ws, CONTRACTS_DIR)


def test_derive_next_call_evaluator_pending(loop_ws: Path) -> None:
    """cd есть, evaluate не прошёл (пауза concept:0) — вызова агента нет."""
    from impresario.harness import HarnessError
    from impresario.loop import run_loop
    from impresario.agents import ScriptedAgent
    from impresario.loop_harness import derive_next_call

    run_loop(
        loop_ws, CONTRACTS_DIR, ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW, stop_after="concept:0",
    )
    with pytest.raises(HarnessError, match="EVALUATOR_PENDING"):
        derive_next_call(loop_ws, CONTRACTS_DIR)


def test_history_order_and_hash_deterministic(loop_ws: Path) -> None:
    from impresario.loop_harness import history_entries, history_hash

    run_scripted(loop_ws, HAPPY_SCRIPT)
    entries = history_entries(loop_ws)
    keys = [(e["iteration"], e["role"], e["id"]) for e in entries]
    assert keys == sorted(
        keys, key=lambda k: (k[0], 0 if k[1] == "researcher" else 1, k[2])
    )
    assert history_hash(entries) == history_hash(history_entries(loop_ws))


def test_render_stage_brief_deterministic_and_valid(loop_ws: Path) -> None:
    from impresario.loader import load_doc
    from impresario.loop_harness import render_stage_brief
    from impresario.schemas import check_schema, load_validators

    report1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report1["role"] == "researcher" and report1["iteration"] == 0
    path = Path(report1["path"])
    bytes1 = path.read_bytes()
    report2 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert report2 == report1 and path.read_bytes() == bytes1

    doc = load_doc(path)
    assert doc.kind == "stage-brief"
    assert check_schema(doc, load_validators(CONTRACTS_DIR)) == []
```

- [ ] **Step 2: Убедиться, что падают** → FAIL (модуля нет).

- [ ] **Step 3: Реализация loop_harness.py**

```python
"""Stage harness for the forconcept loop: brief rendering + step ingest.

The runner (impresario.loop) stays the sole executor of loop semantics;
this module derives the next expected agent call from the workspace
artifacts (the same evidence the runner reads), renders a content-
addressed StageBrief, and — in step — assembles a full artifact from an
executor's answer and feeds it back through run_loop via
SingleAnswerAgent (spec:
docs/superpowers/specs/2026-08-16-loop-agent-harness-design.md).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import workspace as ws
from .harness import HarnessError, sha256_bytes
from .hashing import canonical_doc_hash
from .loader import Doc, load_doc

# Внутрипакетные приватные хелперы раннера: деривация обязана читать
# ровно те же артефакты тем же способом, что и run_loop.
from .loop import _docs_of_kind, _find_iteration, state_path
from .schemas import check_schema, load_validators

ROLE_ORDER = {"researcher": 0, "creator": 1}
ROLE_PROMPT_VERSIONS = {"researcher": "researcher/v1", "creator": "creator/v1"}

_STAGE_IDENTITY_FIELDS = (
    "loop_id",
    "iteration",
    "role",
    "prompt_version",
    "prompt_pack_hash",
    "idea_input_hash",
    "proposal_hash",
    "history_hash",
    "prompt_hash",
)


def loop_briefs_dir(workspace: Path) -> Path:
    """Immutable evidence directory of rendered stage briefs."""
    return workspace / "briefs"


def _read_state(workspace: Path, contracts_dir: Path) -> dict[str, Any]:
    import json

    state = json.loads(state_path(workspace).read_text(encoding="utf-8"))
    validator = load_validators(contracts_dir)["loop-state"]
    errors = sorted(validator.iter_errors(state), key=lambda e: list(e.path))
    if errors:
        raise HarnessError(
            f"{state_path(workspace)}: invalid loop-state: "
            + "; ".join(e.message for e in errors)
        )
    return state


def derive_next_call(workspace: Path, contracts_dir: Path) -> tuple[str, int]:
    """(role, iteration) следующего ожидаемого вызова агента.

    Той же логикой, что раннер: RP итерации нет — researcher; CD нет —
    creator; оба есть, но evaluate-переход не завершён — EVALUATOR_PENDING
    (продвижение — forconcept run/step, не brief). Терминальный stop —
    TERMINAL; needs_human — NEEDS_HUMAN (путь resume).
    """
    state = _read_state(workspace, contracts_dir)
    stop = state.get("stop")
    if stop is not None:
        if stop.get("verdict") == "needs_human":
            raise HarnessError(
                "NEEDS_HUMAN: loop is holding for a human; use "
                "`forconcept resume` before the next brief"
            )
        raise HarnessError(
            f"TERMINAL: loop already stopped with {stop.get('verdict')}"
        )
    proposal = load_doc(workspace / "proposal.yaml")
    delta_log = (proposal.data.get("content") or {}).get("delta_log") or []
    applied = {entry.get("iteration") for entry in delta_log}
    for iteration in range(int(state["max_iterations"])):
        rps = _docs_of_kind(workspace, "research-pack")
        if _find_iteration(rps, iteration) is None:
            return ("researcher", iteration)
        cds = _docs_of_kind(workspace, "concept-draft")
        if _find_iteration(cds, iteration) is None:
            return ("creator", iteration)
        if iteration not in applied:
            raise HarnessError(
                f"EVALUATOR_PENDING: iteration {iteration} has both "
                "artifacts but the delta is not applied; advance with "
                "`forconcept run` (or step) — no agent call is pending"
            )
    raise HarnessError(
        "EVALUATOR_PENDING: all iterations have artifacts but the loop "
        "has no verdict; advance with `forconcept run`"
    )
```

Примечание к деривации: случай «оба артефакта есть, delta применена, но
вердикт итерации не вынесен» в файловом раннере не существует отдельно
от «вынесен continue» (evaluate и запись вердикта — один прогон
`run_loop`), поэтому ветка после `applied`-проверки продолжает цикл —
continue-итерация означает следующий researcher.

```python
def history_entries(workspace: Path) -> list[dict[str, Any]]:
    """RP/CD история в детерминированном порядке (iteration, role, id)."""
    entries: list[tuple[tuple[int, int, str], Doc]] = []
    for kind, role in (("research-pack", "researcher"), ("concept-draft", "creator")):
        for doc in _docs_of_kind(workspace, kind):
            entries.append(
                (
                    (
                        int(doc.data.get("iteration", 0)),
                        ROLE_ORDER[role],
                        str(doc.data.get("id", "")),
                    ),
                    doc,
                )
            )
    entries.sort(key=lambda pair: pair[0])
    return [
        {
            "iteration": key[0],
            "role": "researcher" if key[1] == 0 else "creator",
            "id": key[2],
            "hash": canonical_doc_hash(doc.data),
            "doc": doc.data,
        }
        for key, doc in entries
    ]


def history_hash(entries: list[dict[str, Any]]) -> str:
    """Канонический хеш упорядоченной истории (без самих документов)."""
    return canonical_doc_hash(
        {
            "history": [
                {k: e[k] for k in ("iteration", "role", "id", "hash")}
                for e in entries
            ]
        }
    )


def stage_brief_identity(fields: dict[str, Any]) -> str:
    """SBR-<12hex> от ровно девяти identity-полей (включая prompt_hash)."""
    identity = {name: fields[name] for name in _STAGE_IDENTITY_FIELDS}
    return "SBR-" + canonical_doc_hash(identity).removeprefix("sha256:")[:12]


def render_stage_brief(
    workspace: Path, contracts_dir: Path, prompts_dir: Path
) -> dict[str, Any]:
    """Детерминированный рендер brief'а следующей ожидаемой стадии."""
    role, iteration = derive_next_call(workspace, contracts_dir)
    state = _read_state(workspace, contracts_dir)
    pack_path = prompts_dir / role / "v1" / "prompt.md"
    pack_raw = pack_path.read_bytes()
    template = pack_raw.decode("utf-8")

    idea = load_doc(workspace / "idea.yaml")
    proposal = load_doc(workspace / "proposal.yaml")
    entries = history_entries(workspace)
    history_text = (
        "\n\n".join(
            f"### {e['role']} — итерация {e['iteration']} — {e['id']}\n\n"
            + ws.dump_yaml(e["doc"])
            for e in entries
        )
        or "(история пуста — первая стадия цикла)"
    )
    substitutions = {
        "idea": ws.dump_yaml(idea.data),
        "proposal": ws.dump_yaml(proposal.data),
        "history": history_text,
    }
    prompt = re.sub(
        r"\{(idea|proposal|history)\}",
        lambda m: substitutions[m.group(1)],
        template,
    )
    fields: dict[str, Any] = {
        "loop_id": state["loop_id"],
        "iteration": iteration,
        "role": role,
        "prompt_version": ROLE_PROMPT_VERSIONS[role],
        "prompt_pack_hash": sha256_bytes(pack_raw),
        "idea_input_hash": canonical_doc_hash(idea.data),
        "proposal_hash": canonical_doc_hash(proposal.data),
        "history_hash": history_hash(entries),
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    brief = {
        "schema_version": "stage-brief/v1",
        "brief_id": stage_brief_identity(fields),
        **fields,
        "prompt": prompt,
    }
    validators = load_validators(contracts_dir)
    findings = check_schema(
        Doc(
            path=loop_briefs_dir(workspace) / f"{brief['brief_id'].lower()}.yaml",
            kind="stage-brief",
            data=brief,
        ),
        validators,
    )
    if findings:
        raise HarnessError(
            "refusing to write invalid stage brief: "
            + "; ".join(f.message for f in findings)
        )
    path = loop_briefs_dir(workspace) / f"{brief['brief_id'].lower()}.yaml"
    content = ws.dump_yaml(brief)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise HarnessError(
                f"{path}: existing brief bytes diverge from a fresh render "
                "under the same brief_id (tampering?)"
            )
    else:
        ws.write_atomic(path, content)
    return {
        "brief_id": brief["brief_id"],
        "role": role,
        "iteration": iteration,
        "path": str(path),
    }
```

- [ ] **Step 4: Прогнать** → PASS; полный сьют, ruff (scoped), pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/loop_harness.py tests/test_loop_harness.py
git commit -m "feat: loop_harness — деривация стадии, history-hash, render stage-brief"
```

---

### Task 5: Протокол step + oracle-тест эквивалентности

**Files:**
- Modify: `src/impresario/loop_harness.py`
- Test: `tests/test_loop_harness.py`

**Interfaces:**
- Consumes: Task 3 (`SingleAnswerAgent`, `iteration:N`), Task 4.
- Produces: `step_loop(workspace, contracts_dir, prompts_dir, *,
  brief_path, answer_path, actor, model, now_iso) -> dict` — отчёт
  `{"artifact": {...id, path}, "runner": {verdict, iteration},
  "noop": bool}`; typed-маркеры `STALE_BRIEF` / `STEP_CONFLICT` в
  текстах ошибок.

- [ ] **Step 1: Failing-тесты**

```python
RA_CONTENT_IT0 = {
    "schema_version": "research-answer/v1",
    "findings": [
        {"claim": "claim", "source_ref": "ref://x", "confidence": "high"}
    ],
    "constraints": [],
    "gaps": [{"what": "critical gap", "blocks_approval": True}],
    "brief_for_creator": "brief",
    "requests_to_creator": [],
}

CA_CONTENT_IT0 = {
    "schema_version": "concept-answer/v1",
    "value_prop": "value",
    "alternatives": [
        {"direction": "a", "summary": "s"},
        {"direction": "b", "summary": "s"},
        {"direction": "c", "summary": "s"},
    ],
    "chosen_direction": {"direction": "a", "why": "w"},
    "business_models": ["m"],
    "assumptions": [{"text": "critical assumption", "blocks_approval": True}],
    "requests_to_researcher": ["check the gap"],
    "proposal_delta": "delta 0",
}


def _write_yaml(path: Path, data: dict) -> Path:
    import yaml as _yaml

    path.write_text(
        _yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _step(ws_path: Path, brief: Path, answer: Path, **kw):
    from impresario.loop_harness import step_loop

    defaults = dict(actor="claude", model="claude-fable-5", now_iso=NOW)
    defaults.update(kw)
    return step_loop(
        ws_path, CONTRACTS_DIR, PROMPTS_DIR,
        brief_path=brief, answer_path=answer, **defaults,
    )


def test_step_researcher_then_creator_advances(loop_ws: Path, tmp_path: Path) -> None:
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    out = _step(loop_ws, Path(r1["path"]), ans)
    assert out["runner"]["verdict"] == "paused"
    rp = load_doc(Path(out["artifact"]["path"]))
    assert rp.kind == "research-pack" and rp.data["iteration"] == 0
    assert rp.data["provenance"]["brief_id"] == r1["brief_id"]
    assert rp.data["produced_by"] == {
        "kind": "agent", "id": "claude",
        "model": "claude-fable-5", "prompt_version": "researcher/v1",
    }

    r2 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    assert r2["role"] == "creator" and r2["iteration"] == 0
    ans2 = _write_yaml(tmp_path / "ca.yaml", CA_CONTENT_IT0)
    out2 = _step(loop_ws, Path(r2["path"]), ans2)
    # continue-вердикт итерации 0: paused перед researcher 1
    assert out2["runner"]["verdict"] == "paused"
    cd = load_doc(Path(out2["artifact"]["path"]))
    assert cd.data["based_on_research"]["ref"].startswith("research-pack://RP-")


def test_step_idempotent_retry_before_freshness(loop_ws: Path, tmp_path: Path) -> None:
    """Потреблённый brief повторно — no-op, хотя workspace продвинулся."""
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    first = _step(loop_ws, Path(r1["path"]), ans)
    artifact_path = Path(first["artifact"]["path"])
    bytes_before = artifact_path.read_bytes()

    retry = _step(
        loop_ws, Path(r1["path"]), ans, now_iso="2026-08-16T20:00:00Z"
    )
    assert retry["noop"] is True
    assert artifact_path.read_bytes() == bytes_before  # id/produced_at живы

    divergent = dict(RA_CONTENT_IT0, brief_for_creator="другой")
    ans2 = _write_yaml(tmp_path / "ra2.yaml", divergent)
    with pytest.raises(HarnessError, match="STEP_CONFLICT"):
        _step(loop_ws, Path(r1["path"]), ans2)


def test_step_stale_brief_and_mispairing(loop_ws: Path, tmp_path: Path) -> None:
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    # продвигаем workspace ДРУГИМ путём (scripted), brief r1 не потреблён
    from impresario.loop import run_loop
    from impresario.agents import ScriptedAgent

    run_loop(
        loop_ws, CONTRACTS_DIR, ScriptedAgent(HAPPY_SCRIPT),
        now_iso=NOW, stop_after="research:0",
    )
    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    with pytest.raises(HarnessError, match="STALE_BRIEF"):
        _step(loop_ws, Path(r1["path"]), ans)


def test_step_prevalidates_assembled_artifact(loop_ws: Path, tmp_path: Path) -> None:
    """Невалидная сборка — typed-ошибка step'а, loop.state не тронут."""
    from impresario.harness import HarnessError
    from impresario.loop_harness import render_stage_brief

    r1 = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
    bad = dict(RA_CONTENT_IT0)
    bad["gaps"] = [
        {"what": "g", "blocks_approval": True, "closed": True,
         "answered_by": "not-a-ref"}
    ]
    ans = _write_yaml(tmp_path / "ra.yaml", bad)
    with pytest.raises(HarnessError):
        _step(loop_ws, Path(r1["path"]), ans)
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"] is None  # никакого verdict=failed


def test_step_oracle_equivalence_happy(loop_ws: Path, tmp_path: Path) -> None:
    """Пошаговый happy эквивалентен ScriptedAgent-прогону (спека: не
    байт-равенство — модуло produced_by/produced_at/provenance/хеши)."""
    from impresario.loop import init_loop, run_loop
    from impresario.agents import ScriptedAgent
    from impresario.loop_harness import render_stage_brief

    # Эталонный workspace: тот же init, что в фикстуре loop_ws
    # (свериться с tests/test_loop.py и продублировать аргументы —
    # idea-файл, loop_id="LOOP-001", proposal/exchange ids,
    # max_iterations=2, now_iso=NOW).
    ref_ws = tmp_path / "ref"
    idea_file = tmp_path / "idea-source.yaml"
    idea_file.write_text(
        (loop_ws / "idea.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    init_loop(
        ref_ws, idea_file, CONTRACTS_DIR,
        loop_id="LOOP-001", proposal_id="PP-001",
        exchange_log_id="XL-001", max_iterations=2, now_iso=NOW,
    )
    scripted = run_loop(
        ref_ws, CONTRACTS_DIR, ScriptedAgent(HAPPY_SCRIPT), now_iso=NOW
    )
    assert scripted.verdict == "ready_for_business"

    # step-сторона: 4 стадии через brief/step (RA/CA итераций 0 и 1 —
    # контент из HAPPY_SCRIPT без bookkeeping), до терминального вердикта.
    answers = {
        ("researcher", 0): RA_CONTENT_IT0,
        ("creator", 0): CA_CONTENT_IT0,
        ("researcher", 1): RA_CONTENT_IT1,
        ("creator", 1): CA_CONTENT_IT1,
    }
    last = None
    for n in range(4):
        r = render_stage_brief(loop_ws, CONTRACTS_DIR, PROMPTS_DIR)
        ans = _write_yaml(
            tmp_path / f"a{n}.yaml", answers[(r["role"], r["iteration"])]
        )
        last = _step(loop_ws, Path(r["path"]), ans)
    assert last is not None and last["runner"]["verdict"] == "ready_for_business"

    # Обязательные сравнения loop_ws (step) vs ref_ws (scripted):
    # (а) контент RP/CD: dict-сравнение после удаления produced_by,
    #     produced_at, provenance у step-артефактов и produced_by,
    #     produced_at у scripted (id сравнивать — совпадают: RP-001...);
    # (б) delta_log proposal'ов равны;
    # (в) последовательность событий trace (поле event) равна;
    # (г) вердикты равны (ready_for_business) и loop.state равны модуло
    #     ничего (идея та же => idea_input_hash тот же; stop равны);
    # (д) события artifact_written равны модуло output_hash.
```

Сравнения (а)-(д) реализовать полностью (это тело теста после цикла
выше). Константы RA_CONTENT_IT1/CA_CONTENT_IT1 определить рядом с
IT0-вариантами: контент итерации 1 из HAPPY_SCRIPT — то же с
`gaps: [{"what": "critical gap", "blocks_approval": true, "closed": true}]`,
`assumptions: [{"text": "critical assumption", "blocks_approval": true,
"answered_by": "research-pack://RP-002"}]`, `requests_to_creator: []`,
`requests_to_researcher: []`, `proposal_delta: "delta 1"` — свериться с
`_rp/_cd` в tests/test_loop.py и снять контент оттуда, отбросив
bookkeeping.

- [ ] **Step 2: Убедиться, что падают** → FAIL.

- [ ] **Step 3: Реализация step_loop**

В `loop_harness.py` (нормативный порядок — спека, §forconcept step):

```python
def _assemble_artifact(
    brief: dict[str, Any],
    answer: dict[str, Any],
    workspace: Path,
    contracts_dir: Path,
    *,
    actor: str,
    model: str,
    now_iso: str,
) -> dict[str, Any]:
    """Полный RP/CD: контент из answer + bookkeeping из brief/loop.state."""
    state = _read_state(workspace, contracts_dir)
    role = brief["role"]
    if role == "researcher":
        kind, prefix = "research-pack", "RP"
    else:
        kind, prefix = "concept-draft", "CD"
    existing = {
        d.data["id"] for d in _docs_of_kind(workspace, kind)
    }
    artifact_id = ws.next_id(prefix, existing_ids=existing)
    content = {k: v for k, v in answer.items() if k != "schema_version"}
    doc: dict[str, Any] = {
        "id": artifact_id,
        "idea_ref": state["idea_ref"],
        "proposal_ref": f"proposal://{state['proposal_id']}",
        "iteration": brief["iteration"],
        **content,
        "produced_by": {
            "kind": "agent",
            "id": actor,
            "model": model,
            "prompt_version": brief["prompt_version"],
        },
        "produced_at": now_iso,
        "provenance": {
            "brief_id": brief["brief_id"],
            "prompt_pack_hash": brief["prompt_pack_hash"],
        },
    }
    if role == "creator":
        rps = _docs_of_kind(workspace, "research-pack")
        rp = _find_iteration(rps, brief["iteration"])
        if rp is None:
            raise HarnessError(
                "STALE_BRIEF: no research pack for the brief's iteration"
            )
        doc["based_on_research"] = {
            "ref": f"research-pack://{rp.data['id']}",
            "iteration": brief["iteration"],
        }
    return doc
```

```python
def step_loop(
    workspace: Path,
    contracts_dir: Path,
    prompts_dir: Path,
    *,
    brief_path: Path,
    answer_path: Path,
    actor: str,
    model: str,
    now_iso: str,
) -> dict[str, Any]:
    """Нормативный протокол шага (спека): brief → идемпотентность →
    freshness → answer → пре-валидация сборки → раннер."""
    from .agents import SingleAnswerAgent
    from .loop import run_loop

    validators = load_validators(contracts_dir)

    # 1. Brief: схема + двухслойный пересчёт identity.
    brief_doc = load_doc(brief_path)
    if brief_doc.kind != "stage-brief":
        raise HarnessError(f"{brief_path}: not a stage-brief")
    findings = check_schema(brief_doc, validators)
    if findings:
        raise HarnessError(
            f"{brief_path}: invalid brief: "
            + "; ".join(f.message for f in findings)
        )
    brief = brief_doc.data
    if sha256_bytes(brief["prompt"].encode("utf-8")) != brief["prompt_hash"]:
        raise HarnessError(
            f"{brief_path}: BRIEF_IDENTITY: prompt bytes do not match "
            "prompt_hash"
        )
    if stage_brief_identity(brief) != brief["brief_id"]:
        raise HarnessError(
            f"{brief_path}: BRIEF_IDENTITY: brief_id does not match the "
            "recompute"
        )

    role = brief["role"]
    kind = "research-pack" if role == "researcher" else "concept-draft"

    # 2. Идемпотентность — ДО freshness (спека: потреблённый brief после
    # продвижения workspace иначе был бы отвергнут как stale).
    answer_doc = load_doc(answer_path)
    expected_answer_kind = (
        "research-answer" if role == "researcher" else "concept-answer"
    )
    consumed = next(
        (
            d
            for d in _docs_of_kind(workspace, kind)
            if (d.data.get("provenance") or {}).get("brief_id")
            == brief["brief_id"]
        ),
        None,
    )
    if consumed is not None:
        if answer_doc.kind != expected_answer_kind:
            raise HarnessError(f"{answer_path}: not a {expected_answer_kind}")
        candidate = _assemble_artifact(
            brief, answer_doc.data, workspace, contracts_dir,
            actor=actor, model=model, now_iso=now_iso,
        )
        existing_cmp = {
            k: v
            for k, v in consumed.data.items()
            if k not in ("id", "produced_at")
        }
        candidate_cmp = {
            k: v
            for k, v in candidate.items()
            if k not in ("id", "produced_at")
        }
        if existing_cmp == candidate_cmp:
            return {
                "ok": True,
                "noop": True,
                "artifact": {
                    "id": consumed.data["id"],
                    "path": str(consumed.path),
                },
                "runner": None,
            }
        raise HarnessError(
            f"STEP_CONFLICT: brief {brief['brief_id']} already consumed as "
            f"{consumed.data['id']} with a different answer/actor/model"
        )

    # 3. Freshness + структурная проверка пары.
    expected_role, expected_iteration = derive_next_call(
        workspace, contracts_dir
    )
    state = _read_state(workspace, contracts_dir)
    idea = load_doc(workspace / "idea.yaml")
    proposal = load_doc(workspace / "proposal.yaml")
    fresh = {
        "loop_id": state["loop_id"],
        "iteration": expected_iteration,
        "role": expected_role,
        "idea_input_hash": canonical_doc_hash(idea.data),
        "proposal_hash": canonical_doc_hash(proposal.data),
        "history_hash": history_hash(history_entries(workspace)),
    }
    for field, value in fresh.items():
        if brief.get(field) != value:
            raise HarnessError(
                f"STALE_BRIEF: {field} of the brief does not match the "
                f"workspace's current expected stage ({brief.get(field)!r} "
                f"!= {value!r})"
            )

    # 4. Answer: схема роли.
    if answer_doc.kind != expected_answer_kind:
        raise HarnessError(f"{answer_path}: not a {expected_answer_kind}")
    findings = check_schema(answer_doc, validators)
    if findings:
        raise HarnessError(
            f"{answer_path}: invalid answer: "
            + "; ".join(f.message for f in findings)
        )

    # 5. Пре-валидация полностью собранного артефакта: путь раннера для
    # невалидного артефакта персистит терминальный failed — слишком
    # разрушительно для ошибки ingest; раннер остаётся defense-in-depth.
    artifact = _assemble_artifact(
        brief, answer_doc.data, workspace, contracts_dir,
        actor=actor, model=model, now_iso=now_iso,
    )
    findings = check_schema(
        Doc(path=workspace / f"{artifact['id'].lower()}.yaml",
            kind=kind, data=artifact),
        validators,
    )
    if findings:
        raise HarnessError(
            "refusing to run: assembled artifact is invalid: "
            + "; ".join(f.message for f in findings)
        )

    # 6. Раннер — единственный исполнитель.
    stop_after = (
        f"research:{expected_iteration}"
        if role == "researcher"
        else f"iteration:{expected_iteration}"
    )
    result = run_loop(
        workspace,
        contracts_dir,
        SingleAnswerAgent(role, expected_iteration, artifact),
        now_iso=now_iso,
        stop_after=stop_after,
    )
    return {
        "ok": True,
        "noop": False,
        "artifact": {
            "id": artifact["id"],
            "path": str(workspace / f"{artifact['id'].lower()}.yaml"),
        },
        "runner": {"verdict": result.verdict, "iteration": result.iteration},
    }
```

(`run_loop` сигнатуру свериться с loop.py: позиционные
`workspace, contracts_dir, agent`, именованные `now_iso`, `stop_after`.)

- [ ] **Step 4: Прогнать** — все новые (включая полностью написанный
  oracle-тест) + полный сьют, ruff (scoped), pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/loop_harness.py tests/test_loop_harness.py
git commit -m "feat: step_loop — идемпотентность до freshness, пре-валидация, раннер как исполнитель"
```

---

### Task 6: Кросс-чеки — BRIEF_IDENTITY для stage-brief и ARTIFACT_BRIEF

**Files:**
- Modify: `src/impresario/checks.py`
- Test: `tests/test_bundle_checks.py`

**Interfaces:**
- Consumes: `loop_harness.stage_brief_identity`, `harness.sha256_bytes`.
- Produces: `check_briefs` покрывает оба вида briefs (два слоя у
  каждого; identity-поля свои); `check_artifact_provenance(docs)` —
  код `ARTIFACT_BRIEF`; wiring в `run_bundle_checks`; `_KIND_TO_SCHEME`
  + `_ID_FIELDS` для новых kinds (псевдосхемы known-set, не ref-схемы).

- [ ] **Step 1: Failing-тесты**

В `tests/test_bundle_checks.py` (по образцу `_brief_doc`):

```python
def _stage_brief_doc() -> Doc:
    from impresario.harness import sha256_bytes
    from impresario.loop_harness import stage_brief_identity

    prompt = "исследуй\n"
    fields = {
        "loop_id": "LOOP-001",
        "iteration": 0,
        "role": "researcher",
        "prompt_version": "researcher/v1",
        "prompt_pack_hash": "sha256:" + "b" * 64,
        "idea_input_hash": "sha256:" + "a" * 64,
        "proposal_hash": "sha256:" + "c" * 64,
        "history_hash": "sha256:" + "d" * 64,
        "prompt_hash": sha256_bytes(prompt.encode("utf-8")),
    }
    data = {
        "schema_version": "stage-brief/v1",
        "brief_id": stage_brief_identity(fields),
        **fields,
        "prompt": prompt,
    }
    return Doc(path=Path("sbr.yaml"), kind="stage-brief", data=data)


def test_stage_brief_identity_clean_and_tampered(bundle: list[Doc]) -> None:
    good = _stage_brief_doc()
    assert "BRIEF_IDENTITY" not in _codes([*bundle, good])
    t1 = Doc(path=good.path, kind=good.kind,
             data=dict(good.data, prompt=good.data["prompt"] + "x"))
    assert "BRIEF_IDENTITY" in _codes([*bundle, t1])
    t2 = Doc(path=good.path, kind=good.kind,
             data=dict(good.data, role="creator"))
    assert "BRIEF_IDENTITY" in _codes([*bundle, t2])


def _rp_with_provenance(brief: Doc) -> Doc:
    data = {
        "id": "RP-900",
        "idea_ref": "idea://IDEA-001",
        "iteration": 0,
        "findings": [],
        "constraints": [],
        "gaps": [],
        "brief_for_creator": "b",
        "requests_to_creator": [],
        "produced_by": {
            "kind": "agent", "id": "claude", "model": "m",
            "prompt_version": brief.data["prompt_version"],
        },
        "produced_at": "2026-08-16T12:00:00Z",
        "provenance": {
            "brief_id": brief.data["brief_id"],
            "prompt_pack_hash": brief.data["prompt_pack_hash"],
        },
    }
    return Doc(path=Path("rp-900.yaml"), kind="research-pack", data=data)


def test_artifact_brief_clean(bundle: list[Doc]) -> None:
    brief = _stage_brief_doc()
    docs = [*bundle, brief, _rp_with_provenance(brief)]
    assert "ARTIFACT_BRIEF" not in _codes(docs)


def test_artifact_brief_dangling_and_mismatches(bundle: list[Doc]) -> None:
    brief = _stage_brief_doc()
    rp = _rp_with_provenance(brief)
    # висячий brief
    assert "ARTIFACT_BRIEF" in _codes([*bundle, rp])
    # расходящийся prompt_pack_hash
    d = dict(rp.data)
    d["provenance"] = dict(d["provenance"], prompt_pack_hash="sha256:" + "9" * 64)
    assert "ARTIFACT_BRIEF" in _codes(
        [*bundle, brief, Doc(path=rp.path, kind=rp.kind, data=d)]
    )
    # несовпадающая итерация артефакта с brief'ом
    d2 = dict(rp.data, iteration=1)
    assert "ARTIFACT_BRIEF" in _codes(
        [*bundle, brief, Doc(path=rp.path, kind=rp.kind, data=d2)]
    )
    # артефакт без provenance пропускается
    d3 = {k: v for k, v in rp.data.items() if k != "provenance"}
    assert "ARTIFACT_BRIEF" not in _codes(
        [*bundle, Doc(path=rp.path, kind=rp.kind, data=d3)]
    )
```

- [ ] **Step 2: Убедиться, что падают** → FAIL.

- [ ] **Step 3: Реализация**

`check_briefs`: обобщить на два kinds — по kind выбрать identity-функцию
(`harness.brief_identity` для evaluation-brief;
`loop_harness.stage_brief_identity` для stage-brief); двухслойная
логика (prompt_hash → identity) одинаковая; сообщения включают kind.

`check_artifact_provenance` — по образцу `check_assessment_provenance`
(группировка stage-briefs по brief_id; `!=1` — ambiguity-находка,
`continue`; сравнение `provenance.prompt_pack_hash`, а также
`produced_by.prompt_version == brief.prompt_version`,
`doc.iteration == brief.iteration`, роль:
`doc.kind == "research-pack"` ⇔ `brief.role == "researcher"`,
`doc.kind == "concept-draft"` ⇔ `brief.role == "creator"`; если в
bundle есть loop-state — `brief.loop_id` совпадает с его `loop_id`).
Применяется к kinds research-pack/concept-draft с непустым `provenance`.

`_KIND_TO_SCHEME`: `"stage-brief": "sbrief"`, `"research-answer":
"ranswer"`, `"concept-answer": "canswer"` (known-set-only; комментарий
как у brief/answer). `_ID_FIELDS`: `brief_id` уже есть (stage-brief
использует его же — конфликтов нет: kind различает).

Wiring: `findings.extend(check_artifact_provenance(docs))` в
`run_bundle_checks`.

- [ ] **Step 4: Прогнать** — новые + существующие BRIEF_IDENTITY-тесты
  evaluation-brief (не сломались) + pp-001/pp-101 чисты → полный сьют,
  ruff, pyrefly.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/checks.py tests/test_bundle_checks.py
git commit -m "feat: BRIEF_IDENTITY для stage-brief и кросс-чек ARTIFACT_BRIEF"
```

---

### Task 7: CLI forconcept brief/step + документация

**Files:**
- Modify: `src/impresario/cli.py`
- Modify: `README.md`, `docs/semantics.md`, `TODO.md`
- Test: `tests/test_loop_harness.py`

**Interfaces:**
- Consumes: `loop_harness.render_stage_brief` / `step_loop`,
  `harness.find_prompts_dir`, `HarnessError`.
- Produces: `impresario forconcept brief <ws> [--prompts] [--contracts]`
  и `impresario forconcept step <ws> --brief --answer --actor --model
  [--prompts] [--contracts]`; JSON-отчёты; typed-ошибки → JSON
  `{"ok": false, "error": ...}` + EXIT_USAGE. Except-кортеж — как у
  `_run_assess` (HarnessError, FileNotFoundError, OSError,
  UnknownContractError, yaml.YAMLError, UnicodeDecodeError) — свериться
  и повторить дословно; резолюция contracts/prompts от `Path.cwd()`
  (идиома репо).

- [ ] **Step 1: Failing CLI-тесты**

```python
def test_cli_forconcept_brief_and_step(loop_ws: Path, tmp_path: Path, capsys) -> None:
    from impresario.cli import main

    code = main(["forconcept", "brief", str(loop_ws)])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["role"] == "researcher"

    ans = _write_yaml(tmp_path / "ra.yaml", RA_CONTENT_IT0)
    code = main(
        [
            "forconcept", "step", str(loop_ws),
            "--brief", out["path"], "--answer", str(ans),
            "--actor", "claude", "--model", "claude-fable-5",
        ]
    )
    out2 = json.loads(capsys.readouterr().out)
    assert code == 0 and out2["ok"] and out2["runner"]["verdict"] == "paused"


def test_cli_forconcept_step_typed_error_is_exit_2(loop_ws: Path, tmp_path: Path, capsys) -> None:
    from impresario.cli import main

    code = main(
        [
            "forconcept", "step", str(loop_ws),
            "--brief", str(tmp_path / "нет.yaml"),
            "--answer", str(tmp_path / "нет2.yaml"),
            "--actor", "a", "--model", "m",
        ]
    )
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["ok"] is False
```

Запуск тестов CLI требует cwd=repo root (резолюция от cwd) — как в
существующих CLI-тестах; свериться и повторить их идиому.

- [ ] **Step 2: Убедиться, что падают** → FAIL.

- [ ] **Step 3: CLI**

В подкоманды `forconcept` добавить `brief` и `step` (парсер по образцу
`assess`); обработчик — try/except с тем же кортежем исключений, что у
`_run_assess`, `now_iso` — тем же источником, что у resume.

- [ ] **Step 4: Документация**

- README: раздел «Живые агенты цикла (researcher/v1, creator/v1)» после
  forconcept: последовательность brief → LLM → step, ссылка на спеку;
  строка `ARTIFACT_BRIEF` в таблицу кодов («цепь артефакт → stage-brief
  нарушена»); упоминание stage-brief/answer контрактов в
  contracts/README.md (таблица + грамматика `SBR-`); счётчик тестов —
  фактический.
- docs/semantics.md: короткий раздел «Харнесс агентов цикла»
  (brief/step, freshness всех входов, идемпотентность до freshness,
  раннер — единственный исполнитель, граница iteration:N).
- TODO.md: M2-хвост закрыт целиком (`[x]` researcher/creator-половина,
  ссылка на спеку; «живой прогон цикла — человеческий акт после мержа»).

- [ ] **Step 5: Прогнать всё** — полный сьют (счётчик для README), ruff
  (scoped), pyrefly, `uv run impresario validate contracts/examples/pp-001`
  и `pilot/forconcept/pp-101` — exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/impresario/cli.py tests/test_loop_harness.py README.md docs/semantics.md TODO.md contracts/README.md
git commit -m "feat: CLI forconcept brief/step + документация харнесса агентов"
```

---

### Task 8: Финальная верификация и PR

- [ ] **Step 1: Полная верификация**

```bash
uv run ruff format src tests contracts README.md && uv run ruff check .
uv run pyrefly check
uv run pytest
uv run impresario validate contracts/examples/pp-001
uv run impresario validate pilot/forconcept/pp-101
git status --short  # чисто
```

- [ ] **Step 2: Push и PR**

```bash
git push -u origin feat/loop-agent-harness
gh pr create --title "feat: researcher/creator-харнесс forconcept-цикла (stage-brief + step)" --body "Вторая половина M2-хвоста: живые LLM-агенты цикла через brief/step. Контракты stage-brief/v1 (freshness всех входов промпта: идея+proposal+история; identity с prompt_hash), research-answer/v1 и concept-answer/v1 (только контент, дискриминаторы); расширения research-pack (gaps[].answered_by, provenance) и concept-draft (provenance); промпт-паки researcher/v1 и creator/v1 с уроками пилота; граница раннера iteration:N (после terminal effects) и SingleAnswerAgent — раннер остаётся единственным исполнителем семантики; протокол step: идемпотентность до freshness, structural-проверка пары (закрывает класс friction №22), пре-валидация сборки (никакого verdict=failed на ошибке ingest); кросс-чеки BRIEF_IDENTITY (stage-brief) и ARTIFACT_BRIEF; oracle-тест эквивалентности step-прогона scripted-прогону.

Спека: docs/superpowers/specs/2026-08-16-loop-agent-harness-design.md

Живой прогон цикла по идее из backlog v3 — отдельный человеческий акт после мержа.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 3: Доложить** — ссылка на PR, мерж за человеком; после
  мержа M2-хвост закрыт целиком, доступен живой цикл
  (QG-4 select → forconcept init → brief/step-итерации).
