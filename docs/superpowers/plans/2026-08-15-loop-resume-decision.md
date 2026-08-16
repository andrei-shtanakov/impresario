# loop-resume-decision/v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Контракт `loop-resume-decision/v1` — immutable авторизация resume
одного ожидания `needs_human` — плюс переход reference runner'а на него
(producer-протокол под lock), кросс-чеки валидатора и бэкфилл pp-101.

**Architecture:** Новая схема в `contracts/`, ветвление loader по префиксу
`decision_id`, 4 новых кросс-чека в `checks.py` (active-set по допустимым
рёбрам supersedes), переписанный `resume_loop()` в `loop.py` (single-writer
lock на весь consume-переход, LRD — источник истины, не аргументы вызова),
фильтр kind в `gate.py`, бэкфилл `pilot/forconcept/pp-101/decisions/lrd-001.yaml`.

**Tech Stack:** Python 3.11+, jsonschema (Draft 2020-12), PyYAML, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-15-loop-resume-decision-design.md`
— план аргументирует от спеки; исполнитель читает обе.

## Global Constraints

- Только `uv`: `uv run pytest`, `uv run ruff format . && uv run ruff check .`,
  `uv run pyrefly check` — после каждой задачи, все три зелёные.
- Line length 88; type hints обязательны; docstrings на публичных API.
- Ветка: `feat/loop-resume-decision` (уже существует, спека закоммичена).
  Мерж — только через PR, мержит человек.
- Существующие схемы НЕ менять (правка без смены `$id` допустима только без
  сужения множества валидных документов — здесь не требуется вовсе).
- `pilot/` — immutable evidence: единственное допустимое изменение —
  **добавление** нового файла `decisions/lrd-001.yaml` (бэкфилл). Ни trace,
  ни loop.state, ни существующие артефакты не трогать.
- Коммит-сообщения заканчиваются `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Инвариант покрытия: каждый новый кросс-чек имеет ломающий тест; у контракта
  ≥1 валидная и ≥1 невалидная fixture.

---

### Task 1: Схема loop-resume-decision/v1, fixtures, loader

**Files:**
- Create: `contracts/loop-resume-decision/v1/schema.json`
- Create: `contracts/loop-resume-decision/v1/fixtures/valid/lrd-001.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/valid/lrd-002-supersedes.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/invalid/lrd-non-human-actor.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/invalid/lrd-empty-reason.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/invalid/lrd-extra-field.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/invalid/lrd-zero-budget.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/invalid/lrd-foreign-supersedes.yaml`
- Create: `contracts/loop-resume-decision/v1/fixtures/invalid/lrd-missing-iteration.yaml`
- Modify: `src/impresario/loader.py:12-23` (CONTRACT_KINDS), `:65-85` (detect_kind)
- Test: `tests/test_schema_fixtures.py` (параметризация подхватит fixtures сама; добавить тесты detect_kind)

**Interfaces:**
- Produces: kind `"loop-resume-decision"` в `CONTRACT_KINDS`; `detect_kind()`
  возвращает его для документов с `decision_id` на `LRD-`;
  `load_validators()` начинает отдавать `validators["loop-resume-decision"]`
  автоматически (итерирует CONTRACT_KINDS). Все последующие задачи полагаются
  на это имя kind.

- [ ] **Step 1: Написать failing-тесты определения kind**

В конец `tests/test_schema_fixtures.py`:

```python
def test_detect_kind_lrd_prefix() -> None:
    from impresario.loader import detect_kind

    assert (
        detect_kind({"decision_id": "LRD-001", "subject": {}}) == "loop-resume-decision"
    )


def test_detect_kind_gd_prefix_stays_gate_decision() -> None:
    from impresario.loader import detect_kind

    assert detect_kind({"decision_id": "GD-001"}) == "gate-decision"
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `uv run pytest tests/test_schema_fixtures.py -k detect_kind -v`
Expected: FAIL — `test_detect_kind_lrd_prefix` даёт `"gate-decision"`.

- [ ] **Step 3: Ветвление loader + регистрация kind**

В `src/impresario/loader.py` добавить в `CONTRACT_KINDS` (после
`"gate-decision"`):

```python
    "gate-decision",
    "loop-resume-decision",
    "run-record",
```

и заменить ветку в `detect_kind`:

```python
    if "decision_id" in data:
        raw_decision_id = data["decision_id"]
        if isinstance(raw_decision_id, str) and raw_decision_id.startswith("LRD-"):
            return "loop-resume-decision"
        return "gate-decision"
```

- [ ] **Step 4: Написать схему**

`contracts/loop-resume-decision/v1/schema.json` — домашний стиль (как у
gate-decision/loop-state):

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:loop-resume-decision:v1",
  "title": "LoopResumeDecision",
  "description": "Immutable авторизация возобновления одного конкретного ожидания needs_human цикла researcher ↔ creator (docs/semantics.md, «Состояние цикла»). Authority — человек (schema-enforced: decided_by.kind = human). Исправление/перекрытие — только новой записью со ссылкой supersedes; старая запись не правится. Consumer (внешний backend) решений не создаёт: отсутствие активного решения — fail-closed отказ.",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "decision_id",
    "subject",
    "new_max_iterations",
    "decided_by",
    "decided_at",
    "reason"
  ],
  "properties": {
    "decision_id": {
      "type": "string",
      "pattern": "^LRD-[0-9]{3,}$"
    },
    "subject": {
      "type": "object",
      "additionalProperties": false,
      "required": ["loop_id", "iteration"],
      "properties": {
        "loop_id": {
          "type": "string",
          "pattern": "^LOOP-[0-9]{3,}$"
        },
        "iteration": {
          "type": "integer",
          "minimum": 0
        }
      }
    },
    "new_max_iterations": {
      "type": "integer",
      "minimum": 1
    },
    "decided_by": {
      "type": "object",
      "additionalProperties": false,
      "required": ["kind", "id"],
      "properties": {
        "kind": {
          "enum": ["human"]
        },
        "id": {
          "type": "string",
          "minLength": 1
        }
      }
    },
    "decided_at": {
      "$ref": "#/$defs/timestamp"
    },
    "reason": {
      "type": "string",
      "minLength": 1
    },
    "supersedes": {
      "type": "string",
      "pattern": "^loop-resume-decision://LRD-[0-9]{3,}$"
    }
  },
  "$defs": {
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]+)?Z$"
    }
  }
}
```

Перед записью сверить форму `decided_by` с
`contracts/gate-decision/v1/schema.json` и повторить её дословно.

- [ ] **Step 5: Fixtures**

`fixtures/valid/lrd-001.yaml`:

```yaml
decision_id: LRD-001
subject:
  loop_id: LOOP-101
  iteration: 1
new_max_iterations: 3
decided_by:
  kind: human
  id: andrei
decided_at: '2026-08-12T04:01:21Z'
reason: owner resolved the blocking exempt semantics
```

`fixtures/valid/lrd-002-supersedes.yaml`:

```yaml
decision_id: LRD-002
subject:
  loop_id: LOOP-101
  iteration: 1
new_max_iterations: 4
decided_by:
  kind: human
  id: andrei
decided_at: '2026-08-12T05:00:00Z'
reason: corrects LRD-001 with a wider budget
supersedes: loop-resume-decision://LRD-001
```

Invalid — каждая копия lrd-001 с одной поломкой:
- `lrd-non-human-actor.yaml`: `decided_by: {kind: agent, id: bot}`
- `lrd-empty-reason.yaml`: `reason: ''`
- `lrd-extra-field.yaml`: добавить строку `comment: extra`
- `lrd-zero-budget.yaml`: `new_max_iterations: 0`
- `lrd-foreign-supersedes.yaml`: `supersedes: gate-decision://GD-001`
- `lrd-missing-iteration.yaml`: у `subject` оставить только `loop_id`

- [ ] **Step 6: Прогнать тесты**

Run: `uv run pytest tests/test_schema_fixtures.py -v`
Expected: PASS, в выводе появились параметры
`loop-resume-decision/valid/...` и `.../invalid/...`; оба detect_kind-теста
зелёные. Затем `uv run pyrefly check` и
`uv run ruff format . && uv run ruff check .`.

- [ ] **Step 7: Commit**

```bash
git add contracts/loop-resume-decision src/impresario/loader.py tests/test_schema_fixtures.py
git commit -m "feat: контракт loop-resume-decision/v1 — схема, fixtures, детекция kind по префиксу LRD"
```

---

### Task 2: gate.py — фильтр kind в _decisions (регрессия от LRD-файлов)

**Files:**
- Modify: `src/impresario/gate.py:56-60` (`_decisions`)
- Test: `tests/test_gates.py`

Причина: `_decisions()` грузит **все** `*.yaml` из `decisions/`; LRD-документ
там даст kind `loop-resume-decision`, а `decide()`/`readiness()` обращаются к
`d.data["subject"]["ref"]`, которого у LRD нет — KeyError. Гейтовая логика
должна видеть только gate-decision.

**Interfaces:**
- Consumes: kind `"loop-resume-decision"` из Task 1.
- Produces: `_decisions()` возвращает только `Doc` с kind `"gate-decision"`.

- [ ] **Step 1: Failing-тест**

В конец `tests/test_gates.py`:

```python
def test_lrd_file_in_decisions_dir_does_not_break_gates(ready_ws: Path) -> None:
    """LoopResumeDecision в decisions/ невидим для гейтовой логики."""
    decisions = ready_ws / "decisions"
    decisions.mkdir(exist_ok=True)
    (decisions / "lrd-001.yaml").write_text(
        yaml.safe_dump(
            {
                "decision_id": "LRD-001",
                "subject": {"loop_id": "LOOP-001", "iteration": 1},
                "new_max_iterations": 3,
                "decided_by": {"kind": "human", "id": "andrei"},
                "decided_at": T0,
                "reason": "resume authorization, not a gate decision",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    ok, reasons = readiness(ready_ws)
    assert ok, reasons
    version = load_doc(ready_ws / "proposal.yaml").data["version"]
    report, record = _decide(
        ready_ws,
        T1,
        gate_id="qg5_business",
        decision="approve",
        expected_version=version,
        role="business_owner",
    )
    assert report.ok, [f.message for f in report.errors]
    assert record is not None and record["decision_id"] == "GD-001"
```

- [ ] **Step 2: Убедиться, что падает**

Run: `uv run pytest tests/test_gates.py::test_lrd_file_in_decisions_dir_does_not_break_gates -v`
Expected: FAIL (KeyError `'ref'` либо иная ошибка на LRD-документе).

- [ ] **Step 3: Фильтр kind**

В `src/impresario/gate.py` заменить тело `_decisions`:

```python
def _decisions(workspace: Path) -> list[Doc]:
    directory = ws.decisions_dir(workspace)
    if not directory.is_dir():
        return []
    # decisions/ also holds loop-resume-decision records (resume
    # authorizations); gate logic must only ever see gate decisions.
    docs = (load_doc(p) for p in sorted(directory.glob("*.yaml")))
    return [doc for doc in docs if doc.kind == "gate-decision"]
```

- [ ] **Step 4: Прогнать тесты**

Run: `uv run pytest tests/test_gates.py -v`
Expected: PASS все. Затем pyrefly + ruff.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/gate.py tests/test_gates.py
git commit -m "fix: гейтовая логика фильтрует decisions/ по kind — LRD-файлы ей невидимы"
```

---

### Task 3: Кросс-чеки LRD_* и девятая ссылочная схема

**Files:**
- Modify: `src/impresario/checks.py:13-16` (`_REF_RE`), `:18-33`
  (`_KIND_TO_SCHEME`), новый `check_loop_resume_decisions` перед
  `run_bundle_checks`, wiring в `run_bundle_checks`
- Test: `tests/test_bundle_checks.py`

**Interfaces:**
- Consumes: kind `"loop-resume-decision"` (Task 1).
- Produces: коды `LRD_LOOP`, `LRD_BUDGET`, `LRD_SUPERSEDES`, `LRD_DUP`;
  `loop-resume-decision://LRD-…` резолвится в `check_refs` (значит, висячий
  `supersedes` даёт `REF_DANGLING`). Функция
  `check_loop_resume_decisions(docs: list[Doc]) -> list[Finding]`.

- [ ] **Step 1: Failing-тесты**

В конец `tests/test_bundle_checks.py` (используют синтетические Doc — LRD-чеки
не зависят от файлов):

```python
def _lrd(
    decision_id: str,
    *,
    iteration: int = 1,
    budget: int = 3,
    supersedes: str | None = None,
    loop_id: str = "LOOP-001",
) -> Doc:
    data: dict[str, Any] = {
        "decision_id": decision_id,
        "subject": {"loop_id": loop_id, "iteration": iteration},
        "new_max_iterations": budget,
        "decided_by": {"kind": "human", "id": "andrei"},
        "decided_at": "2026-08-12T04:01:21Z",
        "reason": "r",
    }
    if supersedes is not None:
        data["supersedes"] = supersedes
    return Doc(
        path=Path(f"{decision_id.lower()}.yaml"),
        kind="loop-resume-decision",
        data=data,
    )


def _loop_state(loop_id: str = "LOOP-001") -> Doc:
    return Doc(
        path=Path("loop.state"),
        kind="loop-state",
        data={
            "loop_id": loop_id,
            "idea_ref": "idea://IDEA-001",
            "idea_input_hash": "sha256:" + "0" * 64,
            "proposal_id": "PP-001",
            "exchange_log_id": "XL-001",
            "max_iterations": 3,
            "stop": None,
        },
    )


def test_lrd_loop_unresolved(bundle: list[Doc]) -> None:
    docs = [*bundle, _lrd("LRD-001", loop_id="LOOP-999")]
    assert "LRD_LOOP" in _codes(docs)


def test_lrd_budget_below_iteration_floor(bundle: list[Doc]) -> None:
    docs = [*bundle, _loop_state(), _lrd("LRD-001", iteration=2, budget=3)]
    assert "LRD_BUDGET" in _codes(docs)  # needs >= iteration + 2 = 4


def test_lrd_self_supersedes(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001", supersedes="loop-resume-decision://LRD-001"),
    ]
    codes = _codes(docs)
    assert "LRD_SUPERSEDES" in codes
    # недопустимое ребро не деактивирует единственное решение
    assert "LRD_DUP" not in codes


def test_lrd_supersedes_cycle(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001", supersedes="loop-resume-decision://LRD-002"),
        _lrd("LRD-002", supersedes="loop-resume-decision://LRD-001"),
    ]
    assert "LRD_SUPERSEDES" in _codes(docs)


def test_lrd_foreign_identity_supersedes(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001", iteration=0),
        _lrd("LRD-002", iteration=1, supersedes="loop-resume-decision://LRD-001"),
    ]
    assert "LRD_SUPERSEDES" in _codes(docs)


def test_lrd_duplicate_active(bundle: list[Doc]) -> None:
    docs = [*bundle, _loop_state(), _lrd("LRD-001"), _lrd("LRD-002", budget=4)]
    assert "LRD_DUP" in _codes(docs)


def test_lrd_chain_single_active_is_clean(bundle: list[Doc]) -> None:
    """A <- B <- C: активна только C, нарушений нет."""
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-001"),
        _lrd("LRD-002", budget=4, supersedes="loop-resume-decision://LRD-001"),
        _lrd("LRD-003", budget=5, supersedes="loop-resume-decision://LRD-002"),
    ]
    codes = _codes(docs)
    assert not codes & {"LRD_SUPERSEDES", "LRD_DUP", "LRD_LOOP", "LRD_BUDGET"}


def test_lrd_dangling_supersedes_is_ref_dangling(bundle: list[Doc]) -> None:
    docs = [
        *bundle,
        _loop_state(),
        _lrd("LRD-002", supersedes="loop-resume-decision://LRD-999"),
    ]
    assert "REF_DANGLING" in _codes(docs)
```

Вверху файла дополнить импорт: `from pathlib import Path`.

Примечание: `bundle` (pp-001) не содержит loop-state; `_loop_state()` даёт
LRD-чекам разрешимый loop. `check_loop_states` для него чист: `stop: null`
пропускает XLOG/ITERATION-ветки, а `LOOPSTATE_PROPOSAL` не сработает, потому
что PP-001 в bundle ровно один и idea_ref совпадает — если
`test_lrd_chain_single_active_is_clean` всё же увидит `LOOPSTATE_*`-шум,
проверять только LRD-коды (как в приведённом asserting-стиле через `codes &`).

- [ ] **Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_bundle_checks.py -k lrd -v`
Expected: FAIL — коды не появляются (чеков ещё нет).

- [ ] **Step 3: Реализация**

В `src/impresario/checks.py`:

`_REF_RE` — добавить схему:

```python
_REF_RE = re.compile(
    r"^(idea|assessment|backlog|research-pack|concept-draft"
    r"|exchange-log|proposal|gate-decision|loop-resume-decision)://\S+$"
)
```

`_KIND_TO_SCHEME` — после `"gate-decision"`:

```python
    "loop-resume-decision": "loop-resume-decision",
```

Перед `run_bundle_checks` добавить:

```python
def _lrd_identity(doc: Doc) -> tuple[Any, Any]:
    subject = doc.data.get("subject") or {}
    return (subject.get("loop_id"), subject.get("iteration"))


def check_loop_resume_decisions(docs: list[Doc]) -> list[Finding]:
    """LoopResumeDecision: loop resolution, budget floor, active-set.

    Active-set is computed over admissible supersedes edges only: an edge
    is admissible when it resolves within the bundle to a decision of the
    same identity and is neither a self-loop nor part of a cycle.
    Inadmissible edges are findings and never deactivate anything (spec:
    docs/superpowers/specs/2026-08-15-loop-resume-decision-design.md).
    Dangling supersedes is REF_DANGLING territory (check_refs), not ours.
    """
    findings: list[Finding] = []
    lrds = [d for d in docs if d.kind == "loop-resume-decision"]
    if not lrds:
        return findings
    loops = [d for d in docs if d.kind == "loop-state"]

    def err(doc: Doc, code: str, message: str) -> None:
        findings.append(Finding(code=code, path=str(doc.path), message=message))

    for doc in lrds:
        loop_id, iteration = _lrd_identity(doc)
        matching = [d for d in loops if d.data.get("loop_id") == loop_id]
        if len(matching) != 1:
            err(
                doc,
                "LRD_LOOP",
                f"subject.loop_id {loop_id} matches {len(matching)} "
                "loop-state doc(s) in bundle (expected exactly 1)",
            )
        floor = int(iteration or 0) + 2
        if int(doc.data.get("new_max_iterations") or 0) < floor:
            err(
                doc,
                "LRD_BUDGET",
                f"new_max_iterations {doc.data.get('new_max_iterations')} < "
                f"subject.iteration + 2 = {floor} (needs_human at 0-based "
                "iteration i means budget i+1 was exhausted)",
            )

    by_id = {
        d.data["decision_id"]: d
        for d in lrds
        if isinstance(d.data.get("decision_id"), str)
    }
    edges: dict[str, str] = {}
    for doc in lrds:
        raw = doc.data.get("supersedes")
        if not isinstance(raw, str):
            continue
        src_id = doc.data.get("decision_id")
        target_id = raw.removeprefix("loop-resume-decision://")
        target = by_id.get(target_id)
        if target is None or not isinstance(src_id, str):
            continue  # dangling ref: REF_DANGLING owns that finding
        if target_id == src_id:
            err(doc, "LRD_SUPERSEDES", f"{src_id} supersedes itself")
            continue
        if _lrd_identity(target) != _lrd_identity(doc):
            err(
                doc,
                "LRD_SUPERSEDES",
                f"{src_id} supersedes {target_id} of a different identity "
                f"{_lrd_identity(target)} != {_lrd_identity(doc)}",
            )
            continue
        edges[src_id] = target_id

    in_cycle: set[str] = set()
    for start in edges:
        walked: list[str] = []
        node = start
        while node in edges and node not in walked:
            walked.append(node)
            node = edges[node]
        if node in walked:
            in_cycle.update(walked[walked.index(node) :])
    for src in sorted(in_cycle):
        err(by_id[src], "LRD_SUPERSEDES", f"{src} is part of a supersedes cycle")

    superseded = {t for s, t in edges.items() if s not in in_cycle}
    groups: dict[tuple[Any, Any], list[Doc]] = {}
    for doc in lrds:
        groups.setdefault(_lrd_identity(doc), []).append(doc)
    for identity, group in groups.items():
        active = sorted(
            (d for d in group if d.data.get("decision_id") not in superseded),
            key=lambda d: str(d.data.get("decision_id")),
        )
        if len(active) > 1:
            ids = ", ".join(str(d.data.get("decision_id")) for d in active)
            err(
                active[0],
                "LRD_DUP",
                f"identity {identity} has {len(active)} active decisions "
                f"({ids}); expected at most 1",
            )
    return findings
```

В `run_bundle_checks` добавить строку перед `return`:

```python
    findings.extend(check_loop_resume_decisions(docs))
```

- [ ] **Step 4: Прогнать тесты**

Run: `uv run pytest tests/test_bundle_checks.py -v`
Expected: PASS все (включая старые). Затем pyrefly + ruff.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/checks.py tests/test_bundle_checks.py
git commit -m "feat: кросс-чеки LRD_* и девятая ссылочная схема loop-resume-decision://"
```

---

### Task 4: resume_loop — producer-протокол под lock, LRD как источник истины

**Files:**
- Modify: `src/impresario/loop.py:175-243` (`resume_loop` → протокол из спеки)
- Modify: `src/impresario/cli.py:282-300` (вывод `decision`)
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `validators["loop-resume-decision"]` (Task 1);
  `ws.single_writer_lock`, `ws.decisions_dir`, `ws.next_id`,
  `ws.write_atomic`, `ws.dump_yaml`, `ws.WorkspaceError` (существующие).
- Produces: `resume_loop(...) -> str` — возвращает
  `"loop-resume-decision://LRD-nnn"`; сигнатура аргументов НЕ меняется
  (`workspace, contracts_dir, *, max_iterations, actor, reason, now_iso`).
  Trace-событие `resumed` получает поле `decision_ref`. CLI-ответ resume:
  `{"ok": true, "resumed": "<ws>", "decision": "loop-resume-decision://LRD-nnn"}`.

- [ ] **Step 1: Failing-тесты**

В конец `tests/test_loop.py`:

```python
def test_resume_writes_and_consumes_lrd(loop_ws: Path) -> None:
    """Resume создаёт immutable LRD и потребляет его; бандл чист."""
    from impresario.loop import resume_loop

    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    ref = resume_loop(
        loop_ws,
        CONTRACTS_DIR,
        max_iterations=3,
        actor="andrei",
        reason="owner decision",
        now_iso=NOW,
    )
    assert ref == "loop-resume-decision://LRD-001"
    decision = load_doc(loop_ws / "decisions" / "lrd-001.yaml")
    assert decision.kind == "loop-resume-decision"
    assert decision.data["subject"] == {"loop_id": "LOOP-001", "iteration": 1}
    assert decision.data["new_max_iterations"] == 3
    assert decision.data["decided_at"] == NOW
    resumed = [e for e in _trace_events(loop_ws) if e["event"] == "resumed"]
    assert resumed[0]["decision_ref"] == ref
    report = validate_paths([loop_ws], CONTRACTS_DIR, bundle=True)
    assert report.ok, [f"{f.code}: {f.message}" for f in report.errors]


def test_resume_retry_mismatched_args_is_refused(
    loop_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ретрай с другими аргументами отклоняется; источник — записанный LRD."""
    import impresario.loop as loop_mod
    from impresario.loop import LoopError, resume_loop

    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    original = loop_mod._write_state
    calls = {"n": 0}

    def flaky(workspace, state, validator):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated crash before atomic replace")
        original(workspace, state, validator)

    monkeypatch.setattr(loop_mod, "_write_state", flaky)
    with pytest.raises(OSError):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=3,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )
    with pytest.raises(LoopError, match="does not match"):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=4,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )
    with pytest.raises(LoopError, match="does not match"):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=3,
            actor="andrei",
            reason="another reason",
            now_iso=NOW,
        )
    # совпадающий ретрай доводит переход из существующего LRD
    ref = resume_loop(
        loop_ws,
        CONTRACTS_DIR,
        max_iterations=3,
        actor="andrei",
        reason="r",
        now_iso="2026-08-12T19:00:00Z",
    )
    decision = load_doc(loop_ws / "decisions" / "lrd-001.yaml")
    assert decision.data["decided_at"] == NOW  # исходный timestamp сохранён
    assert ref == "loop-resume-decision://LRD-001"


def test_resume_fails_closed_on_invalid_lrd(loop_ws: Path) -> None:
    """Невалидное решение не потребляется; ожидание сохраняется."""
    from impresario.loop import LoopError, resume_loop

    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    decisions = loop_ws / "decisions"
    decisions.mkdir(exist_ok=True)
    (decisions / "lrd-001.yaml").write_text(
        "decision_id: LRD-001\n"
        "subject:\n  loop_id: LOOP-001\n  iteration: 1\n"
        "new_max_iterations: 3\n"
        "decided_by:\n  kind: agent\n  id: bot\n"  # не human — schema fail
        f"decided_at: '{NOW}'\n"
        "reason: r\n",
        encoding="utf-8",
    )
    with pytest.raises(LoopError, match="invalid"):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=3,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"]["verdict"] == "needs_human"


def test_resume_respects_single_writer_lock(loop_ws: Path) -> None:
    """Конкурентный writer (существующий .lock) — typed fail-fast."""
    from impresario.loop import LoopError, resume_loop

    result = _run(loop_ws, STUCK_SCRIPT)
    assert result.verdict == "needs_human"
    (loop_ws / ".lock").touch()
    with pytest.raises(LoopError, match="locked"):
        resume_loop(
            loop_ws,
            CONTRACTS_DIR,
            max_iterations=3,
            actor="andrei",
            reason="r",
            now_iso=NOW,
        )
    (loop_ws / ".lock").unlink()
```

Если `validate_paths` / `load_doc` ещё не импортированы в `test_loop.py` —
добавить в существующие импорты вверху файла.

- [ ] **Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_loop.py -k "lrd or lock or mismatched" -v`
Expected: FAIL (файл решения не создаётся, lock игнорируется и т.д.).

- [ ] **Step 3: Реализация**

Заменить `resume_loop` в `src/impresario/loop.py` (строки 175-243) на:

```python
def resume_loop(
    workspace: Path,
    contracts_dir: Path,
    *,
    max_iterations: int,
    actor: str,
    reason: str,
    now_iso: str,
) -> str:
    """Reopen a needs_human loop; returns the consumed decision's ref.

    Producer transition (spec 2026-08-15-loop-resume-decision, §protocol):
    the whole consume runs under the workspace single-writer lock; the
    recorded LoopResumeDecision — found active or created — is the source
    of the transition, never the call arguments. Mismatching retry
    arguments are refused. A failure between the steps keeps the waiting
    active; a matching retry finishes the transition from the same
    decision, preserving its decided_at/decided_by/reason.
    """
    try:
        with ws.single_writer_lock(workspace):
            return _resume_locked(
                workspace,
                contracts_dir,
                max_iterations=max_iterations,
                actor=actor,
                reason=reason,
                now_iso=now_iso,
            )
    except ws.WorkspaceError as exc:
        raise LoopError(str(exc)) from exc


def _load_active_resume_decision(
    workspace: Path,
    validator: Draft202012Validator,
    *,
    loop_id: str,
    iteration: int,
) -> dict[str, Any] | None:
    """The single active LRD for (loop_id, iteration), or None.

    Fail-closed: a schema-invalid decision file, a self/cyclic/foreign
    supersedes edge, or more than one active decision is a LoopError —
    the runner refuses to guess which authorization to trust.
    """
    directory = ws.decisions_dir(workspace)
    if not directory.is_dir():
        return None
    docs = [
        d
        for d in (load_doc(p) for p in sorted(directory.glob("*.yaml")))
        if d.kind == "loop-resume-decision"
    ]
    same_identity: list[Doc] = []
    for doc in docs:
        errors = sorted(validator.iter_errors(doc.data), key=lambda e: list(e.path))
        if errors:
            raise LoopError(
                f"{doc.path}: invalid loop-resume-decision: "
                + "; ".join(e.message for e in errors)
            )
        subject = doc.data["subject"]
        if subject["loop_id"] == loop_id and subject["iteration"] == iteration:
            same_identity.append(doc)
    by_id = {d.data["decision_id"]: d for d in same_identity}
    superseded: set[str] = set()
    for doc in same_identity:
        raw = doc.data.get("supersedes")
        if not isinstance(raw, str):
            continue
        target_id = raw.removeprefix("loop-resume-decision://")
        if target_id == doc.data["decision_id"] or target_id not in by_id:
            raise LoopError(
                f"{doc.path}: inadmissible supersedes {raw} "
                "(self, dangling or foreign identity)"
            )
        superseded.add(target_id)
    active = [d for d in same_identity if d.data["decision_id"] not in superseded]
    if len(active) > 1:
        ids = ", ".join(sorted(d.data["decision_id"] for d in active))
        raise LoopError(
            f"more than one active resume decision for ({loop_id}, {iteration}): {ids}"
        )
    return active[0].data if active else None


def _resume_locked(
    workspace: Path,
    contracts_dir: Path,
    *,
    max_iterations: int,
    actor: str,
    reason: str,
    now_iso: str,
) -> str:
    validators = load_validators(contracts_dir)
    state_validator = validators["loop-state"]
    lrd_validator = validators["loop-resume-decision"]

    state = _read_state(workspace)
    errors = _state_errors(state, state_validator)
    if errors:
        raise LoopError(
            f"{state_path(workspace)}: refusing to resume from invalid "
            "loop-state: " + "; ".join(errors)
        )
    stop = state.get("stop")
    if not stop or stop.get("verdict") != NEEDS_HUMAN:
        raise LoopError(
            "only a needs_human loop can be resumed; current stop: "
            f"{stop and stop.get('verdict')}"
        )
    if max_iterations <= int(state["max_iterations"]):
        raise LoopError(
            f"resume requires a larger iteration budget than {state['max_iterations']}"
        )
    loop_id = str(state["loop_id"])
    stop_iteration = int(stop["iteration"])

    decision = _load_active_resume_decision(
        workspace, lrd_validator, loop_id=loop_id, iteration=stop_iteration
    )
    if decision is None:
        existing = (
            {
                d.data["decision_id"]
                for p in sorted(ws.decisions_dir(workspace).glob("*.yaml"))
                if (d := load_doc(p)).kind == "loop-resume-decision"
            }
            if ws.decisions_dir(workspace).is_dir()
            else set()
        )
        decision = {
            "decision_id": ws.next_id("LRD", existing_ids=existing),
            "subject": {"loop_id": loop_id, "iteration": stop_iteration},
            "new_max_iterations": max_iterations,
            "decided_by": {"kind": "human", "id": actor},
            "decided_at": now_iso,
            "reason": reason,
        }
        record_errors = sorted(
            lrd_validator.iter_errors(decision), key=lambda e: list(e.path)
        )
        if record_errors:
            raise LoopError(
                "refusing to write invalid loop-resume-decision: "
                + "; ".join(e.message for e in record_errors)
            )
        path = ws.decisions_dir(workspace) / f"{decision['decision_id'].lower()}.yaml"
        ws.write_atomic(path, ws.dump_yaml(decision))
    else:
        mismatches = [
            name
            for name, got, want in (
                ("max_iterations", decision["new_max_iterations"], max_iterations),
                ("actor", decision["decided_by"]["id"], actor),
                ("reason", decision["reason"], reason),
            )
            if got != want
        ]
        if mismatches:
            raise LoopError(
                f"active decision {decision['decision_id']} does not match "
                f"the call arguments ({', '.join(mismatches)}); repeat the "
                "recorded arguments or supersede the decision"
            )

    # Re-read right before consumption: detects a change that happened
    # before the transition started; the race itself is excluded by the
    # single-writer lock held for the whole transition (spec §protocol 4).
    state = _read_state(workspace)
    stop = state.get("stop")
    if (
        not stop
        or stop.get("verdict") != NEEDS_HUMAN
        or int(stop["iteration"]) != stop_iteration
    ):
        raise LoopError("loop.state changed before consumption; refusing to resume")

    decision_ref = f"loop-resume-decision://{decision['decision_id']}"
    already_resumed = any(
        e.get("event") == "resumed" and e.get("iteration") == stop_iteration
        for e in _read_trace(workspace)
    )
    if not already_resumed:
        ctx = _Ctx(
            workspace=workspace,
            validators={},
            state=state,
            now=now_iso,
            report=Report(),
        )
        _trace(
            ctx,
            {
                "event": "resumed",
                "by": actor,
                "reason": reason,
                "from_verdict": NEEDS_HUMAN,
                "max_iterations": int(decision["new_max_iterations"]),
                "iteration": stop_iteration,
                "at": str(decision["decided_at"]),
                "decision_ref": decision_ref,
            },
        )
    state["max_iterations"] = int(decision["new_max_iterations"])
    state["stop"] = None
    _write_state(workspace, state, state_validator)
    return decision_ref
```

Нюанс совместимости с существующим
`test_resume_retry_after_partial_failure_is_idempotent`: он ретраит с
`now_iso=later`, но теми же remaining-аргументами — ретрай найдёт LRD,
аргументы совпадут, trace-dedup сохранит `at` = NOW (теперь `at` берётся из
`decision["decided_at"]`, что тоже NOW). Тест обязан остаться зелёным без
правок.

В `src/impresario/cli.py` (блок `if args.fc_command == "resume":`) заменить
вызов и вывод:

```python
        if args.fc_command == "resume":
            decision_ref = resume_loop(
                args.workspace,
                contracts,
                max_iterations=args.max_iterations,
                actor=args.actor,
                reason=args.reason,
                now_iso=_now_iso(),
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "resumed": str(args.workspace),
                        "decision": decision_ref,
                    },
                    ensure_ascii=False,
                )
            )
```

(Точную форму существующего вызова — включая имя аргумента `now_iso` и
функции текущего времени — свериться с `cli.py:287-299` и сохранить; меняется
только приём возвращаемого значения и добавление ключа `"decision"`.)

- [ ] **Step 4: Прогнать тесты**

Run: `uv run pytest tests/test_loop.py tests/test_cli.py -v`
Expected: PASS все, включая старые resume-тесты без правок. Затем pyrefly +
ruff.

- [ ] **Step 5: Commit**

```bash
git add src/impresario/loop.py src/impresario/cli.py tests/test_loop.py
git commit -m "feat: resume потребляет immutable LoopResumeDecision под single-writer lock"
```

---

### Task 5: Бэкфилл pp-101 и тест чистоты пилотного бандла

**Files:**
- Create: `pilot/forconcept/pp-101/decisions/lrd-001.yaml`
- Test: `tests/test_bundle_checks.py`

**Interfaces:**
- Consumes: схема и чеки из Task 1/3; `validate_paths` из `impresario.cli`.

- [ ] **Step 1: Baseline**

Run: `uv run impresario validate pilot/forconcept/pp-101`
Expected: exit 0. Если нет — СТОП, доложить: пилотный бандл грязен до
изменений, бэкфилл откладывается.

- [ ] **Step 2: Failing-тест**

В конец `tests/test_bundle_checks.py`:

```python
def test_pilot_pp101_bundle_is_clean_with_backfilled_lrd() -> None:
    """Живой пилот проходит валидатор; бэкфилл-LRD присутствует и активен."""
    from impresario.cli import validate_paths

    from .conftest import CONTRACTS_DIR, REPO_ROOT

    pilot_ws = REPO_ROOT / "pilot" / "forconcept" / "pp-101"
    lrd = load_doc(pilot_ws / "decisions" / "lrd-001.yaml")
    assert lrd.kind == "loop-resume-decision"
    assert lrd.data["subject"] == {"loop_id": "LOOP-101", "iteration": 1}
    assert lrd.data["decided_at"] == "2026-08-12T04:01:21Z"
    report = validate_paths([pilot_ws], CONTRACTS_DIR, bundle=True)
    assert report.ok, [f"{f.code}: {f.message}" for f in report.errors]
```

Run: `uv run pytest tests/test_bundle_checks.py::test_pilot_pp101_bundle_is_clean_with_backfilled_lrd -v`
Expected: FAIL — файла нет.

- [ ] **Step 3: Бэкфилл**

`pilot/forconcept/pp-101/decisions/lrd-001.yaml` — reason дословно из
`trace.jsonl` (строка с `"event": "resumed"`), `decided_at` — `at` записи
`research-pack://RP-503` в `exchange-log.yaml` (operational-шкала ExchangeLog,
НЕ `produced_at` самого RP-503; обоснование — спека, §Бэкфилл):

```yaml
# Бэкфилл 2026-08-15: авторизация исторического resume LOOP-101
# восстановлена из immutable evidence — trace.jsonl (событие resumed),
# decided_at = at записи research-pack://RP-503 в exchange-log.yaml.
decision_id: LRD-001
subject:
  loop_id: LOOP-101
  iteration: 1
new_max_iterations: 3
decided_by:
  kind: human
  id: andrei
decided_at: '2026-08-12T04:01:21Z'
reason: 'Решение владельца robin-runtime: exempt = prograph-vault; контракт
  семантики из 4 пунктов (включая постоянное раскрытие); канонический
  _PLAN_EXEMPT в коде вместо env'
```

Перед записью сверить reason c фактической строкой в
`pilot/forconcept/pp-101/trace.jsonl` и перенести дословно (перенос строк в
YAML-folded допустим, содержимое — байт в байт после парсинга).

- [ ] **Step 4: Прогнать тесты**

Run: `uv run pytest tests/test_bundle_checks.py -v` и
`uv run impresario validate pilot/forconcept/pp-101`
Expected: PASS / exit 0.

- [ ] **Step 5: Commit**

```bash
git add pilot/forconcept/pp-101/decisions/lrd-001.yaml tests/test_bundle_checks.py
git commit -m "feat: бэкфилл LRD-001 для pp-101 — resume LOOP-101 из immutable evidence

decided_at = 2026-08-12T04:01:21Z: at записи research-pack://RP-503 в
exchange-log.yaml (operational-шкала ExchangeLog), не produced_at RP-503."
```

---

### Task 6: Документация — semantics, README контрактов, README, TODO

**Files:**
- Modify: `docs/semantics.md` (раздел «Состояние цикла», абзац про resume)
- Modify: `contracts/README.md` (таблица контрактов, грамматика ID,
  ссылочные схемы)
- Modify: `README.md` (таблица кодов проверок; число тестов в «Разработка»)
- Modify: `TODO.md` (M3-прогресс)

**Interfaces:** только текст; термины и коды — строго как в Task 3/4.

- [ ] **Step 1: docs/semantics.md**

В разделе «Состояние цикла» заменить абзац «Resume — типизированный
человеческий акт…» на (сохранив соседние абзацы):

```markdown
Resume — типизированный человеческий акт с immutable авторизацией
([loop-resume-decision/v1](../contracts/loop-resume-decision/v1/schema.json)):
subject `(loop_id, iteration)`, `new_max_iterations`, `decided_by` (human),
`reason`, опциональная цепочка `supersedes` (решение активно, если на него
не ссылается семантически допустимое ребро `supersedes` другого
schema-valid решения; самоссылка/цикл/чужая identity — нарушение и не
деактивирует ничего). Роли различны: **producer** (reference CLI) находит
активное решение либо создаёт новое; **consumer** (внешний backend)
решения только принимает — отсутствие активного решения есть fail-closed
отказ.

Producer-переход целиком идёт под single-writer lock workspace:
CAS-предусловие (`stop.verdict = needs_human`), найти-или-создать активный
LoopResumeDecision (validate-then-atomic-write; ретрай с несовпадающими
аргументами отклоняется — источник перехода всегда записанное решение, не
аргументы вызова), перечитать состояние перед потреблением (обнаруживает
изменение до начала перехода; саму гонку исключает lock), immutable
trace-evidence `resumed` с `decision_ref` (dedup по identity), затем
atomic-replace: `stop: null`, `max_iterations = new_max_iterations`.
Файловый протокол корректен при single-writer; для внешнего backend/store
настоящий атомарный CAS — обязанность его хранилища. После успешного
replace повторный resume отклоняется CAS-предусловием. Окно «решение
записано, state ещё `needs_human`» — валидное состояние bundle.
```

В абзац про `LOOPSTATE_*`-чеки добавить предложение:

```markdown
Решения resume проверяются кросс-чеками `LRD_*`: `subject.loop_id`
резолвится ровно в один loop.state; `new_max_iterations ≥
subject.iteration + 2`; допустимость рёбер `supersedes`; не более одного
активного решения на identity.
```

- [ ] **Step 2: contracts/README.md**

Таблица контрактов — новая строка после gate-decision:

```markdown
| [loop-resume-decision/v1](./loop-resume-decision/v1/schema.json) | LoopResumeDecision (immutable авторизация resume одного ожидания needs_human; docs/semantics.md «Состояние цикла») |
```

Грамматика ID — строка после GateDecision:

```markdown
| LoopResumeDecision | `LRD-[0-9]{3,}` | `LRD-001` |
```

Абзац про ссылочные схемы: «разрешимых ссылочных схем восемь» → «девять», в
перечень добавить `loop-resume-decision://LRD-001`.

- [ ] **Step 3: README.md**

В таблицу «Коды проверок» после `LOOPSTATE_*`-строк (или в конец таблицы,
если LOOPSTATE-строк нет — тогда рядом с `XLOG_ORDER`):

```markdown
| `LRD_LOOP` | `subject.loop_id` решения resume не резолвится ровно в один loop.state бандла |
| `LRD_BUDGET` | `new_max_iterations` решения resume меньше `subject.iteration + 2` |
| `LRD_SUPERSEDES` | Недопустимое ребро `supersedes` (самоссылка, цикл, чужая identity) |
| `LRD_DUP` | Больше одного активного решения resume на одно ожидание |
```

В разделе «Разработка» обновить счётчик тестов на фактический (взять из
итогового `uv run pytest`).

- [ ] **Step 4: TODO.md**

В секцию `## M3 — Kapelle battle-test` добавить:

```markdown
- [x] **impresario#14 закрыт (сторона impresario)**: контракт
  `loop-resume-decision/v1` — immutable авторизация resume ожидания
  `(loop_id, iteration)`; producer/consumer-роли, single-writer lock на
  consume-переходе, кросс-чеки `LRD_*`, бэкфилл LRD-001 для pp-101.
  Спека: docs/superpowers/specs/2026-08-15-loop-resume-decision-design.md.
  После мержа: ответить в issue #14 пин-коммитом (вендоринг kapelle)
```

- [ ] **Step 5: Проверка и commit**

Run: `uv run pytest` (полный) — взять число тестов для README.
Expected: PASS.

```bash
git add docs/semantics.md contracts/README.md README.md TODO.md
git commit -m "docs: семантика loop-resume-decision, README контрактов, коды LRD_*, TODO M3"
```

---

### Task 7: Финальная верификация и PR

**Files:** нет новых; только проверки и push.

- [ ] **Step 1: Полная верификация**

```bash
uv run ruff format . && uv run ruff check .
uv run pyrefly check
uv run pytest
uv run impresario validate contracts/examples/pp-001
uv run impresario validate pilot/forconcept/pp-101
```

Expected: всё зелёное, оба validate — exit 0. Любой красный результат —
чинить до пуша, не рапортовать успех без вывода команд.

- [ ] **Step 2: Push и PR**

```bash
git push -u origin feat/loop-resume-decision
gh pr create --title "feat: контракт loop-resume-decision/v1 — авторизация resume (closes #14)" --body "Producer-owned immutable авторизация перехода needs_human → resumed: схема + fixtures, producer/consumer-роли, resume под single-writer lock с LRD как источником истины, кросс-чеки LRD_*, девятая ссылочная схема, бэкфилл LRD-001 для pp-101.

Спека: docs/superpowers/specs/2026-08-15-loop-resume-decision-design.md

Closes #14

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 3: Доложить**

Сообщить пользователю: ссылку на PR, что мерж — за человеком (правило репо),
и что после мержа нужен ответ в issue #14 с пин-коммитом для вендоринга
kapelle (см. TODO-запись из Task 6).
