# loop-state/v1 Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Промоутировать `loop.state` reference-раннера в версионированный контракт `loop-state/v1`, чтобы внешние наблюдатели (dispatcher#129 фаза 2) могли fail-closed читать сигнал `needs_human`.

**Architecture:** loop.state — текущий projection состояния цикла (JSON-файл в корне loop-workspace); история остаётся в immutable evidence (ExchangeLog, trace). Схема + fixtures в `contracts/loop-state/v1/`, write-path раннера становится validate-then-atomic-replace, resume получает identity-dedup evidence, бандл-валидатор — 5 identity-кросс-чеков. Спека: `docs/superpowers/specs/2026-08-12-loop-state-contract-design.md`.

**Tech Stack:** Python 3.12+, uv, jsonschema (Draft 2020-12), pytest, ruff, pyrefly.

## Global Constraints

- Только `uv` (`uv run pytest`, `uv run ruff ...`); НИКОГДА pip.
- Line length 88; после каждого изменения: `uv run ruff format . && uv run ruff check .` и `uv run pyrefly check` — исправить всё до коммита.
- Type hints обязательны; публичные API — с docstrings.
- Рабочая директория: `impresario/` (корень репо). Ветка: `feat/loop-state-contract` (уже создана, спека закоммичена).
- Схемы: `$id: urn:impresario:contract:loop-state:v1`, `additionalProperties: false`, timestamp-паттерн `…Z` как в exchange-log/v1.
- Раннер детерминирован: один `now_iso` на инвокацию; golden crash/resume тесты должны остаться зелёными.

---

### Task 1: Схема loop-state/v1, fixtures и поддержка в loader

**Files:**
- Create: `contracts/loop-state/v1/schema.json`
- Create: `contracts/loop-state/v1/fixtures/valid/{running,needs-human,ready,failed}.json`
- Create: `contracts/loop-state/v1/fixtures/invalid/{empty-reason,missing-at,unknown-verdict,extra-field,bad-hash}.json`
- Modify: `src/impresario/loader.py` (CONTRACT_KINDS, detect_kind, load_doc)
- Test: `tests/test_schema_fixtures.py` (глоб `.json` в дополнение к `.yaml`)

**Interfaces:**
- Consumes: существующие `load_doc`, `detect_kind`, `check_schema`, `load_validators` (грузит схему для каждого kind из `CONTRACT_KINDS`).
- Produces: kind `"loop-state"` в `CONTRACT_KINDS`; `detect_kind` возвращает `"loop-state"` при наличии ключа `loop_id` (проверка ДО `proposal_id` — loop-state тоже содержит `proposal_id`); `load_doc` классифицирует файл с именем ровно `loop.state` как JSON `loop-state` без эвристик. `collect_doc_paths` в этой задаче НЕ трогаем (иначе бандл-тесты покраснеют до Task 2).

- [ ] **Step 1: Создать схему**

`contracts/loop-state/v1/schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "urn:impresario:contract:loop-state:v1",
  "title": "LoopState",
  "description": "Текущий projection состояния цикла researcher ↔ creator (docs/semantics.md, «Состояние цикла»). Файл loop.state (JSON) в корне loop-workspace. stop: null — активного ожидания нет; stop.verdict = needs_human — активное ожидание человека. История остаётся в immutable evidence (ExchangeLog, trace).",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "loop_id",
    "idea_ref",
    "idea_input_hash",
    "proposal_id",
    "exchange_log_id",
    "max_iterations",
    "stop"
  ],
  "properties": {
    "loop_id": {
      "type": "string",
      "pattern": "^LOOP-[0-9]{3,}$"
    },
    "idea_ref": {
      "type": "string",
      "pattern": "^idea://IDEA-[0-9]{3,}$"
    },
    "idea_input_hash": {
      "type": "string",
      "pattern": "^sha256:[0-9a-f]{64}$"
    },
    "proposal_id": {
      "type": "string",
      "pattern": "^PP-[0-9]{3,}$"
    },
    "exchange_log_id": {
      "type": "string",
      "pattern": "^XL-[0-9]{3,}$"
    },
    "max_iterations": {
      "type": "integer",
      "minimum": 1
    },
    "stop": {
      "oneOf": [
        {
          "type": "null"
        },
        {
          "type": "object",
          "additionalProperties": false,
          "required": ["verdict", "reason", "iteration", "at"],
          "properties": {
            "verdict": {
              "enum": ["ready_for_business", "needs_human", "failed"]
            },
            "reason": {
              "type": "string",
              "minLength": 1
            },
            "iteration": {
              "type": "integer",
              "minimum": 0
            },
            "at": {
              "$ref": "#/$defs/timestamp"
            }
          }
        }
      ]
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

- [ ] **Step 2: Создать fixtures**

`contracts/loop-state/v1/fixtures/valid/running.json` (свежий init, `stop: null`):

```json
{
  "loop_id": "LOOP-001",
  "idea_ref": "idea://IDEA-001",
  "idea_input_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "proposal_id": "PP-001",
  "exchange_log_id": "XL-001",
  "max_iterations": 3,
  "stop": null
}
```

`contracts/loop-state/v1/fixtures/valid/needs-human.json`:

```json
{
  "loop_id": "LOOP-001",
  "idea_ref": "idea://IDEA-001",
  "idea_input_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "proposal_id": "PP-001",
  "exchange_log_id": "XL-001",
  "max_iterations": 2,
  "stop": {
    "verdict": "needs_human",
    "reason": "max_iterations reached with open critical items: gap: exempt semantics",
    "iteration": 1,
    "at": "2026-08-12T04:01:21Z"
  }
}
```

`contracts/loop-state/v1/fixtures/valid/ready.json` — как needs-human, но `"verdict": "ready_for_business"`, `"reason": "no open critical assumptions/gaps and no open requests"`, `"iteration": 1`.

`contracts/loop-state/v1/fixtures/valid/failed.json` — как needs-human, но `"verdict": "failed"`, `"reason": "researcher produced invalid artifact"`, `"iteration": 0`.

`fixtures/invalid/empty-reason.json` — копия needs-human с `"reason": ""`.
`fixtures/invalid/missing-at.json` — копия needs-human без ключа `"at"`.
`fixtures/invalid/unknown-verdict.json` — копия needs-human с `"verdict": "paused"`.
`fixtures/invalid/extra-field.json` — копия running с добавленным `"note": "x"`.
`fixtures/invalid/bad-hash.json` — копия running с `"idea_input_hash": "sha256:zzzz"`.

- [ ] **Step 3: Обновить фикстурные тесты на оба суффикса**

В `tests/test_schema_fixtures.py` заменить `_fixture_paths` и тело `test_fixture_coverage`:

```python
def _fixture_paths(polarity: str) -> list[Path]:
    return sorted(
        path
        for suffix in ("yaml", "json")
        for path in CONTRACTS_DIR.glob(f"*/v1/fixtures/{polarity}/*.{suffix}")
    )
```

```python
def test_fixture_coverage() -> None:
    """Every contract ships at least one valid and one invalid fixture."""
    for contract_dir in sorted(CONTRACTS_DIR.glob("*/v1")):
        name = contract_dir.parent.name
        for polarity in ("valid", "invalid"):
            found = [
                p
                for suffix in ("yaml", "json")
                for p in (contract_dir / "fixtures" / polarity).glob(f"*.{suffix}")
            ]
            assert found, f"{name}: no {polarity} fixtures"
```

- [ ] **Step 4: Прогнать тесты — убедиться, что падают правильно**

Run: `uv run pytest tests/test_schema_fixtures.py -v`
Expected: FAIL — фикстуры loop-state падают в `load_doc` (`cannot detect contract kind`) и/или `check_schema` (KeyError `loop-state` в validators).

- [ ] **Step 5: Поддержка в loader**

В `src/impresario/loader.py`:

1. В `CONTRACT_KINDS` добавить последним элементом `"loop-state"`.
2. В `detect_kind` добавить ПЕРВОЙ проверкой (до `assessment_id`/`proposal_id` — loop-state содержит `proposal_id`, иначе он ошибочно классифицируется как product-proposal):

```python
    if "loop_id" in data:
        return "loop-state"
```

3. В `load_doc` добавить классификацию по имени файла (до общей ветки; контракт обещает JSON, поэтому парсим строго `json.loads`, без YAML-послаблений):

```python
def load_doc(path: Path) -> Doc:
    """Load a single YAML/JSON artifact and detect its kind."""
    text = path.read_text(encoding="utf-8")
    if path.name == "loop.state":
        data = json.loads(text)
        if not isinstance(data, dict):
            raise UnknownContractError(f"{path}: document is not a mapping")
        return Doc(path=path, kind="loop-state", data=data)
    data = json.loads(text) if path.suffix == ".json" else parse_yaml_plain(text)
    if not isinstance(data, dict):
        raise UnknownContractError(f"{path}: document is not a mapping")
    return Doc(path=path, kind=detect_kind(data), data=data)
```

`collect_doc_paths` НЕ менять в этой задаче.

- [ ] **Step 6: Прогнать тесты**

Run: `uv run pytest tests/test_schema_fixtures.py -v && uv run pytest`
Expected: PASS (все; существующие бандл-тесты не затронуты — `loop.state` пока не попадает в обход директорий).

- [ ] **Step 7: Линт/типы и коммит**

Run: `uv run ruff format . && uv run ruff check . && uv run pyrefly check`

```bash
git add contracts/loop-state src/impresario/loader.py tests/test_schema_fixtures.py
git commit -m "feat: контракт loop-state/v1 — схема, fixtures, kind в loader" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Раннер — stop с iteration/at, validate-then-atomic-replace, явный contracts_dir

**Files:**
- Modify: `src/impresario/loop.py` (`_write_state`, `init_loop`, `resume_loop`, `run_loop`, запись stop в `fail()`/READY/NEEDS_HUMAN)
- Modify: `src/impresario/cli.py` (`--contracts` у `fc_init`/`fc_resume`, единый резолв в `_run_forconcept`)
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `load_validators(contracts_dir)` из Task 1 (ключ `"loop-state"`), `ws.write_atomic`, `CONTRACTS_DIR` из `tests/conftest.py`.
- Produces: новые сигнатуры — `init_loop(workspace, idea_file, contracts_dir, *, loop_id, proposal_id, exchange_log_id, max_iterations, now_iso)`; `resume_loop(workspace, contracts_dir, *, max_iterations, actor, reason, now_iso)`; `_write_state(workspace, state, validator)` с `validator: Draft202012Validator`. Формат stop-записи: `{"verdict", "reason", "iteration", "at"}`. Task 3 и 4 полагаются на эти сигнатуры и формат.

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_loop.py` добавить (импорты `json` и `pytest` уже есть):

```python
def test_stop_record_is_contract_valid(loop_ws: Path) -> None:
    from impresario.schemas import load_validators

    _run(loop_ws, STUCK_SCRIPT)
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"]["iteration"] == 1
    assert state["stop"]["at"] == NOW
    validator = load_validators(CONTRACTS_DIR)["loop-state"]
    assert list(validator.iter_errors(state)) == []


def test_write_state_rejects_invalid_state(loop_ws: Path) -> None:
    import impresario.loop as loop_mod
    from impresario.schemas import load_validators

    validator = load_validators(CONTRACTS_DIR)["loop-state"]
    before = (loop_ws / "loop.state").read_text(encoding="utf-8")
    with pytest.raises(loop_mod.LoopError, match="invalid loop-state"):
        loop_mod._write_state(loop_ws, {"loop_id": "nope"}, validator)
    assert (loop_ws / "loop.state").read_text(encoding="utf-8") == before
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

Run: `uv run pytest tests/test_loop.py::test_stop_record_is_contract_valid tests/test_loop.py::test_write_state_rejects_invalid_state -v`
Expected: FAIL (`KeyError: 'iteration'` / `TypeError: _write_state() takes 2 positional arguments`).

- [ ] **Step 3: Реализация в loop.py**

1. Импорты: добавить `from jsonschema import Draft202012Validator` и `from .schemas import check_schema, load_validators` (заменить существующий импорт `check_schema, load_validators` — `load_validators` уже импортирован, добавить только jsonschema).

2. `_write_state` — validate-then-atomic-replace:

```python
def _write_state(
    workspace: Path, state: dict[str, Any], validator: Draft202012Validator
) -> None:
    """Refuse to persist a state that violates loop-state/v1 (fail-closed)."""
    errors = sorted(validator.iter_errors(state), key=lambda e: list(e.path))
    if errors:
        raise LoopError(
            f"{state_path(workspace)}: refusing to write invalid loop-state: "
            + "; ".join(e.message for e in errors)
        )
    ws.write_atomic(
        state_path(workspace), json.dumps(state, ensure_ascii=False, indent=2)
    )
```

3. `init_loop`: сигнатура `def init_loop(workspace: Path, idea_file: Path, contracts_dir: Path, *, loop_id: str, ...)`. Перед `_write_state` получить валидатор и передать его:

```python
    validator = load_validators(contracts_dir)["loop-state"]
    _write_state(workspace, {...как сейчас...}, validator)
```

Дополнить docstring: `contracts_dir` разрешается вызывающей стороной один раз (CLI: `--contracts` или `find_contracts_dir(cwd)`).

4. `resume_loop`: сигнатура `def resume_loop(workspace: Path, contracts_dir: Path, *, max_iterations: int, actor: str, reason: str, now_iso: str)`; в конце `validator = load_validators(contracts_dir)["loop-state"]` и `_write_state(workspace, state, validator)`. (Протокол resume целиком — Task 3; здесь только сигнатура и валидация записи.)

5. `run_loop`: валидаторы уже загружены — во всех трёх местах записи stop передавать `validators["loop-state"]` и дополнить записи:

```python
        state["stop"] = {
            "verdict": FAILED,
            "reason": reason,
            "iteration": iteration,
            "at": ctx.now,
        }
        _write_state(workspace, state, validators["loop-state"])
```

Аналогично для READY и NEEDS_HUMAN (verdict соответствующий, `iteration` — текущая переменная цикла, `at: ctx.now`). Внутри `fail()` замыкания `validators` доступен.

- [ ] **Step 4: Прокинуть contracts_dir через CLI и тесты**

1. `src/impresario/cli.py`: добавить `fc_init.add_argument("--contracts", type=Path, default=None)` и `fc_resume.add_argument("--contracts", type=Path, default=None)`. В `_run_forconcept` первой строкой try-блока: `contracts_dir = args.contracts or find_contracts_dir(Path.cwd())`, передать в `resume_loop(args.workspace, contracts_dir, ...)`, `init_loop(args.workspace, args.idea_file, contracts_dir, ...)`; строку резолва перед `run_loop` удалить (использовать общий).
2. `tests/test_loop.py`: во всех вызовах `init_loop(...)` (fixture `loop_ws`, control-прогон в `test_crash_resume_at_every_boundary`, `test_init_rejects_zero_iterations`) добавить третий позиционный аргумент `CONTRACTS_DIR`; во всех вызовах `resume_loop(loop_ws, ...)` — второй позиционный `CONTRACTS_DIR`.
3. Проверить другие вызовы: `grep -rn "init_loop\|resume_loop" tests/ src/` — обновить все найденные (ожидаются только `tests/test_loop.py` и `src/impresario/cli.py`).

- [ ] **Step 5: Прогнать все тесты**

Run: `uv run pytest`
Expected: PASS, включая golden crash/resume (`now_iso` фиксирован — записи детерминированы).

- [ ] **Step 6: Линт/типы и коммит**

Run: `uv run ruff format . && uv run ruff check . && uv run pyrefly check`

```bash
git add src/impresario/loop.py src/impresario/cli.py tests/test_loop.py
git commit -m "feat: stop с iteration/at, validate-then-atomic-replace loop.state, явный contracts_dir" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Протокол resume — evidence с identity-dedup и at

**Files:**
- Modify: `src/impresario/loop.py` (`resume_loop`, новый хелпер `_read_trace`)
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: сигнатуру `resume_loop(workspace, contracts_dir, *, ...)` и `_write_state(..., validator)` из Task 2.
- Produces: trace-событие `resumed` с полями `by, reason, from_verdict, max_iterations, iteration, at`; dedup события по identity `(loop_id, iteration)` (loop_id — имплицитно, trace на workspace один), а не по байтам JSON.

- [ ] **Step 1: Написать падающий тест**

```python
def test_resume_retry_after_partial_failure_is_idempotent(
    loop_ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry после сбоя между evidence и replace не дублирует resumed.

    Первая попытка пишет resumed и падает на записи state; ожидание
    остаётся активным. Retry с ДРУГИМ now_iso обязан не создать второй
    resumed (identity-dedup по iteration), сохранить at первой попытки
    и довести replace до stop: null.
    """
    import impresario.loop as loop_mod
    from impresario.loop import resume_loop

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
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"]["verdict"] == "needs_human"  # ожидание активно

    later = "2026-08-12T19:00:00Z"
    resume_loop(
        loop_ws,
        CONTRACTS_DIR,
        max_iterations=3,
        actor="andrei",
        reason="r",
        now_iso=later,
    )
    resumed = [e for e in _trace_events(loop_ws) if e["event"] == "resumed"]
    assert len(resumed) == 1
    assert resumed[0]["at"] == NOW  # at первой попытки сохранён
    assert resumed[0]["iteration"] == 1
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    assert state["stop"] is None
```

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `uv run pytest tests/test_loop.py::test_resume_retry_after_partial_failure_is_idempotent -v`
Expected: FAIL — `resumed[0]` не содержит `at` (KeyError) либо `len(resumed) == 2` (байтовый dedup не совпал из-за нового `now_iso`).

- [ ] **Step 3: Реализация**

В `src/impresario/loop.py` добавить хелпер и переписать `resume_loop`:

```python
def _read_trace(workspace: Path) -> list[dict[str, Any]]:
    path = workspace / TRACE_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
```

```python
def resume_loop(
    workspace: Path,
    contracts_dir: Path,
    *,
    max_iterations: int,
    actor: str,
    reason: str,
    now_iso: str,
) -> None:
    """Reopen a needs_human loop after a human addressed the blocker.

    Protocol (docs/semantics.md, «Состояние цикла»): CAS precondition on
    stop.verdict == needs_human; immutable resumed evidence first,
    identity-deduped on (loop_id, iteration) so a retry after a partial
    failure never duplicates it and keeps the first attempt's `at`; then
    validate-then-atomic-replace of loop.state with stop: null and a
    widened budget. A failure between the steps keeps the waiting active;
    after a successful replace a repeated resume is rejected by the CAS
    precondition (stop is null).
    """
    state = _read_state(workspace)
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
    validator = load_validators(contracts_dir)["loop-state"]
    stop_iteration = int(stop["iteration"])
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
                "max_iterations": max_iterations,
                "iteration": stop_iteration,
                "at": now_iso,
            },
        )
    state["max_iterations"] = max_iterations
    state["stop"] = None
    _write_state(workspace, state, validator)
```

Повтор той же identity после успешного replace невозможен по построению: после расширения бюджета следующий `needs_human` наступает на строго большей итерации.

- [ ] **Step 4: Прогнать все тесты**

Run: `uv run pytest`
Expected: PASS (в т.ч. `test_needs_human_resume_path` — событие `resumed` там проверяется по `event`, новые поля не мешают).

- [ ] **Step 5: Линт/типы и коммит**

Run: `uv run ruff format . && uv run ruff check . && uv run pyrefly check`

```bash
git add src/impresario/loop.py tests/test_loop.py
git commit -m "feat: протокол resume — resumed evidence с iteration/at и identity-dedup" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: loop.state в бандл-валидации + identity-кросс-чеки

**Files:**
- Modify: `src/impresario/loader.py` (`collect_doc_paths`)
- Modify: `src/impresario/checks.py` (`_KIND_TO_SCHEME`, `_ID_FIELDS`, новый `check_loop_states`, регистрация в `run_bundle_checks`)
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: kind `"loop-state"` (Task 1), контрактно-валидные состояния раннера (Task 2), `canonical_doc_hash` из `impresario.hashing`, `validate_paths` из `impresario.cli`.
- Produces: коды `LOOPSTATE_PROPOSAL`, `LOOPSTATE_IDEA_REF`, `LOOPSTATE_IDEA_HASH`, `LOOPSTATE_XLOG`, `LOOPSTATE_ITERATION`; `loop.state` попадает в обход бандла.

- [ ] **Step 1: Написать падающие тесты**

В `tests/test_loop.py` добавить хелперы и тесты:

```python
def _mutate_state(workspace: Path, **changes: Any) -> None:
    path = workspace / "loop.state"
    state = json.loads(path.read_text(encoding="utf-8"))
    state.update(changes)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _bundle_codes(workspace: Path) -> set[str]:
    report = validate_paths([workspace], CONTRACTS_DIR, bundle=True)
    return {f.code for f in report.errors}


def test_loop_state_included_in_bundle_validation(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    _mutate_state(loop_ws, loop_id="broken")  # schema violation
    assert "SCHEMA" in _bundle_codes(loop_ws)


def test_loop_state_foreign_proposal(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    _mutate_state(loop_ws, proposal_id="PP-999")
    assert "LOOPSTATE_PROPOSAL" in _bundle_codes(loop_ws)


def test_loop_state_idea_ref_mismatch(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    _mutate_state(loop_ws, idea_ref="idea://IDEA-999")
    assert "LOOPSTATE_IDEA_REF" in _bundle_codes(loop_ws)


def test_loop_state_stale_idea_hash(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    _mutate_state(loop_ws, idea_input_hash="sha256:" + "0" * 64)
    assert "LOOPSTATE_IDEA_HASH" in _bundle_codes(loop_ws)


def test_loop_state_dangling_exchange_log(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    _mutate_state(loop_ws, exchange_log_id="XL-999")
    assert "LOOPSTATE_XLOG" in _bundle_codes(loop_ws)


def test_loop_state_foreign_exchange_log(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    log_path = loop_ws / "exchange-log.yaml"
    log = yaml.safe_load(log_path.read_text(encoding="utf-8"))
    log["proposal_ref"] = "proposal://PP-999"
    log_path.write_text(
        yaml.safe_dump(log, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    assert "LOOPSTATE_XLOG" in _bundle_codes(loop_ws)


def test_loop_state_iteration_over_budget(loop_ws: Path) -> None:
    _run(loop_ws, STUCK_SCRIPT)
    state = json.loads((loop_ws / "loop.state").read_text(encoding="utf-8"))
    state["stop"]["iteration"] = 5
    (loop_ws / "loop.state").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert "LOOPSTATE_ITERATION" in _bundle_codes(loop_ws)
```

- [ ] **Step 2: Прогнать — убедиться, что падают**

Run: `uv run pytest tests/test_loop.py -k loop_state -v`
Expected: FAIL — коды отсутствуют (`loop.state` не попадает в обход, чеков нет).

- [ ] **Step 3: Включить loop.state в обход и зарегистрировать kind в checks**

1. `src/impresario/loader.py`, `collect_doc_paths`:

```python
                if child.is_file()
                and (child.suffix in _DOC_SUFFIXES or child.name == "loop.state")
```

2. `src/impresario/checks.py` — БЕЗ этого `_doc_ref` падает KeyError на новом kind:

```python
_KIND_TO_SCHEME = {
    ...,
    "run-record": "run",
    # loop:// is not a resolvable ref scheme; needed only for the known-set.
    "loop-state": "loop",
}
```

`_ID_FIELDS`: `loop_id` первым — loop-state содержит и `proposal_id`:

```python
_ID_FIELDS = ("loop_id", "id", "assessment_id", "proposal_id", "decision_id")
```

- [ ] **Step 4: Реализовать check_loop_states**

В `src/impresario/checks.py` (импортировать `from .hashing import canonical_doc_hash`):

```python
def check_loop_states(docs: list[Doc]) -> list[Finding]:
    """LoopState identity: the projection must belong to its bundle.

    Schema guards the shape; these checks guard identity (spec:
    docs/superpowers/specs/2026-08-12-loop-state-contract-design.md).
    """
    findings: list[Finding] = []
    for doc in docs:
        if doc.kind != "loop-state":
            continue
        path, data = str(doc.path), doc.data

        def err(code: str, message: str) -> None:
            findings.append(Finding(code=code, path=path, message=message))

        proposal_id = data.get("proposal_id")
        proposals = [
            d
            for d in docs
            if d.kind == "product-proposal" and d.data.get("proposal_id") == proposal_id
        ]
        if len(proposals) != 1:
            err(
                "LOOPSTATE_PROPOSAL",
                f"proposal_id {proposal_id} matches {len(proposals)} "
                "proposal(s) in bundle (expected exactly 1)",
            )
        elif data.get("idea_ref") != proposals[0].data.get("idea_ref"):
            err(
                "LOOPSTATE_IDEA_REF",
                f"idea_ref {data.get('idea_ref')} != proposal idea_ref "
                f"{proposals[0].data.get('idea_ref')}",
            )

        idea = _resolve(docs, data.get("idea_ref"))
        if idea is not None and canonical_doc_hash(idea.data) != data.get(
            "idea_input_hash"
        ):
            err(
                "LOOPSTATE_IDEA_HASH",
                f"idea_input_hash does not match {data.get('idea_ref')} "
                "in bundle (stale or foreign pinned idea)",
            )

        stop = data.get("stop")
        xlog_id = data.get("exchange_log_id")
        xlogs = [
            d for d in docs if d.kind == "exchange-log" and d.data.get("id") == xlog_id
        ]
        expected_ref = f"proposal://{proposal_id}"
        if xlogs:
            findings.extend(
                Finding(
                    code="LOOPSTATE_XLOG",
                    path=path,
                    message=(
                        f"exchange-log {xlog_id} belongs to "
                        f"{x.data.get('proposal_ref')}, not {expected_ref}"
                    ),
                )
                for x in xlogs
                if x.data.get("proposal_ref") != expected_ref
            )
        elif stop and stop.get("verdict") in ("needs_human", "ready_for_business"):
            # failed/running may legitimately predate the first exchange
            # entry; a loop that reached a verdict past iteration 0 cannot.
            err(
                "LOOPSTATE_XLOG",
                f"exchange_log_id {xlog_id} not found in bundle",
            )

        if stop and stop.get("iteration", 0) >= data.get("max_iterations", 1):
            err(
                "LOOPSTATE_ITERATION",
                f"stop.iteration {stop.get('iteration')} >= max_iterations "
                f"{data.get('max_iterations')} (iterations are 0-based)",
            )
    return findings
```

Зарегистрировать в `run_bundle_checks` после `check_exchange_logs`:

```python
    findings.extend(check_loop_states(docs))
```

- [ ] **Step 5: Прогнать все тесты**

Run: `uv run pytest`
Expected: PASS. Особое внимание: `test_happy_path_reaches_ready`, `test_stuck_loop_needs_human`, `test_needs_human_resume_path` — их `validate_paths(bundle=True)` теперь проверяет и `loop.state` (позитивный интеграционный сигнал); `test_invalid_artifact_fails_closed` бандл не валидирует и не пострадает от отсутствия exchange-log при `failed`.

- [ ] **Step 6: Линт/типы и коммит**

Run: `uv run ruff format . && uv run ruff check . && uv run pyrefly check`

```bash
git add src/impresario/loader.py src/impresario/checks.py tests/test_loop.py
git commit -m "feat: loop.state в бандл-валидации + LOOPSTATE_* identity-кросс-чеки" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Бэкфилл pp-101 из immutable evidence

**Files:**
- Modify: `pilot/forconcept/pp-101/loop.state`

**Interfaces:**
- Consumes: схему и кросс-чеки из Task 1–4.
- Produces: контрактно-валидный исторический loop.state (нужен Task 6 для зелёного validate всего пилота).

- [ ] **Step 1: Убедиться, что бандл сейчас красный**

Run: `uv run impresario validate pilot/forconcept/pp-101`
Expected: exit 1, SCHEMA-ошибки по `loop.state` (в stop нет `iteration`/`at`).

- [ ] **Step 2: Бэкфилл**

В `pilot/forconcept/pp-101/loop.state` дополнить объект `stop` (значения из immutable evidence, зафиксированы в спеке: iteration 2 — trace-вердикт `ready_for_business` на итерации 2; at — `at` ExchangeLog-записей итерации 2, тот же `now_iso` инвокации):

```json
  "stop": {
    "verdict": "ready_for_business",
    "reason": "no open critical assumptions/gaps and no open requests",
    "iteration": 2,
    "at": "2026-08-12T04:01:21Z"
  }
```

Порядок ключей: `verdict`, `reason`, `iteration`, `at`. Остальные поля файла не трогать; trace.jsonl и exchange-log.yaml НЕ менять (immutable history).

- [ ] **Step 3: Проверить зелёный validate**

Run: `uv run impresario validate pilot/forconcept/pp-101 && uv run pytest`
Expected: validate exit 0 (schema + все LOOPSTATE_* чеки на живом бандле), pytest PASS.

- [ ] **Step 4: Коммит**

```bash
git add pilot/forconcept/pp-101/loop.state
git commit -m "chore: бэкфилл stop.iteration/at в pp-101 loop.state из immutable evidence" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Документация — semantics.md, contracts/README.md, TODO.md

**Files:**
- Modify: `docs/semantics.md` (новая секция после «Цикл researcher ↔ creator»)
- Modify: `contracts/README.md` (таблица контрактов, грамматика ID, вводный абзац)
- Modify: `TODO.md` (закрыть пункт M4)

**Interfaces:**
- Consumes: термины и коды из Task 1–5 (`loop-state/v1`, `LOOPSTATE_*`, протокол resume).
- Produces: публичный SSOT семантики сигнала (его вендорит dispatcher фаза 2).

- [ ] **Step 1: Секция в docs/semantics.md**

Вставить после секции «Цикл researcher ↔ creator» (перед «Классы enforcement»):

```markdown
## Состояние цикла: loop-state (сигнал `needs_human`)

Файл `loop.state` (JSON, корень loop-workspace) — законтрактованный
**текущий projection** состояния цикла
([loop-state/v1](../contracts/loop-state/v1/schema.json)): конфигурация
запуска (`loop_id`, `idea_ref` + `idea_input_hash`, `proposal_id`,
`exchange_log_id`, `max_iterations`) и текущая остановка `stop`. Это не
журнал: история (`needs_human` → resume) остаётся в immutable evidence
(ExchangeLog, trace).

Семантика для внешних наблюдателей (dispatcher и др.):

- `stop: null` — активного ожидания нет (цикл не завершён: до первого
  терминального вердикта или после resume).
- `stop.verdict = "needs_human"` — **активное ожидание человека**;
  `reason` обязателен и непуст. Identity ожидания —
  `(loop_id, stop.iteration)`; freshness — `stop.at`.
- Terminal projection сохраняет stop: `ready_for_business` / `failed`
  не откатываются в `null`; единственный переход `stop → null` — resume
  из `needs_human` (`failed` не resumable, fail-closed).
- Наблюдатель строго read-only и вендорит пинованную копию схемы;
  неизвестная версия / невалидный / нечитаемый файл = **unknown, а не
  «ожиданий нет»** (fail-closed).

Запись файла — validate-then-atomic-replace (tool-enforced): невалидное
состояние не пишется, файл остаётся в последнем консистентном виде.
Resume — типизированный человеческий акт: CAS-предусловие
(`stop.verdict = needs_human`), затем immutable evidence возобновления
(`resumed`: by, reason, iteration, at) с dedup по identity
`(loop_id, iteration)` — retry после частичного сбоя между evidence и
replace не дублирует запись и сохраняет `at` первой попытки, — затем
atomic-replace со `stop: null` и расширенным бюджетом. После успешного
replace повторный resume отклоняется CAS-предусловием.

Принадлежность бандлу — tool-enforced кросс-чеками (`LOOPSTATE_*`):
`proposal_id` совпадает ровно с одним proposal; `idea_ref` и
`idea_input_hash` — с идеей, от которой построен proposal;
`exchange_log_id` резолвится в ExchangeLog того же proposal;
`stop.iteration < max_iterations`.
```

- [ ] **Step 2: contracts/README.md**

1. Вводный абзац: заменить «Восемь версионированных контрактов product-governance (стадии отбора идеи и форконцепта), fixtures и детерминированный валидатор» на «Версионированные контракты product-governance (стадии отбора идеи и форконцепта), fixtures и детерминированный валидатор» (числительное уже разошлось с таблицей).
2. В таблицу контрактов добавить строку после run-record:

```markdown
| [loop-state/v1](./loop-state/v1/schema.json) | LoopState (текущий projection состояния цикла researcher ↔ creator; JSON-файл `loop.state`, сигнал `needs_human` — docs/semantics.md) |
```

3. В таблицу «Грамматика ID» добавить строку:

```markdown
| Loop | `LOOP-[0-9]{3,}` | `LOOP-101` |
```

4. Рядом с оговоркой про `run://` дописать: `loop://` также не является ссылочной схемой — `loop_id` встречается только в `loop.state`.

- [ ] **Step 3: TODO.md**

Заменить пункт (строки 74–77):

```markdown
- [ ] Законтрактовать сигнал `needs_human` для внешних наблюдателей: сегодня
  он живёт в `loop.state` — внутреннем состоянии reference-раннера, а не в
  контракте; вариантов два — контракт `loop-state/v1` или типизированное
  emitted-событие; без этого фаза 2 dispatcher#129 невозможна
```

на:

```markdown
- [x] **Сигнал `needs_human` законтрактован (loop-state/v1)**: `loop.state`
  промоутирован в контракт (projection, не журнал; identity
  `(loop_id, stop.iteration)`, freshness `stop.at`, terminal сохраняет
  stop), write-path validate-then-atomic-replace, resume — CAS +
  identity-dedup evidence, 5 кросс-чеков `LOOPSTATE_*`, бэкфилл pp-101 из
  immutable evidence; семантика — docs/semantics.md «Состояние цикла».
  Спека: docs/superpowers/specs/2026-08-12-loop-state-contract-design.md.
  Follow-up: handoff dispatcher#129 фаза 2 (вендорить схему @ merge-commit)
```

- [ ] **Step 4: Финальная верификация**

Run: `uv run pytest && uv run ruff format . && uv run ruff check . && uv run pyrefly check && uv run impresario validate pilot/forconcept/pp-101`
Expected: всё зелёное.

- [ ] **Step 5: Коммит**

```bash
git add docs/semantics.md contracts/README.md TODO.md
git commit -m "docs: семантика loop-state/v1 (needs_human), README контрактов, TODO M4" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## После выполнения

PR в `andrei-shtanakov/impresario` (мерж — человек, по умбрелла-политике; отслеживать ревью Copilot). После мержа — follow-up вне этого плана: handoff в dispatcher (комментарий в #129 или новый inbox-issue): «фаза 2 разблокирована, вендорите `loop-state/v1` @ <merge-commit>, семантика — docs/semantics.md "Состояние цикла"».
