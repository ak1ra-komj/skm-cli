---
created: 2026-04-01
tags:
  - skm-sync
  - refactor
  - cli
  - lint
  - justfile
---

# Sync Refactor and Lint Fix

## Session 1 — Declarative `skm sync` Refactor

### Summary

Replaced the old overlapping subcommands (`install`, `remove`, `update`, `check-updates`) with a single declarative `skm sync` command and a separate interactive `skm add` command. `skills.yaml` is now the single source of truth; `sync` reconciles agent directories to match it.

### Motivation

The previous command set was redundant and imperative — users had to call multiple commands to keep state consistent. The new design is declarative: edit `skills.yaml`, run `skm sync`, done.

### New CLI Commands

| Command | Description |
|---|---|
| `skm sync` | Clone missing repos, create/refresh links, remove stale links, update lock. Idempotent. |
| `skm sync --update` / `-U` | Same as sync, but also pulls latest commits, shows changelogs (commit range + git log), and updates SHAs in lock. |
| `skm add <source> [skill]` | Interactive: discover skills from repo URL or local path, pick skills and agents, append to `skills.yaml`, then sync that package. Alias: `skm i`. |

Old commands removed: `install`, `remove`, `update`, `check-updates`.

### New Config Option: `link_mode`

Added optional top-level `link_mode` field to `skills.yaml`:

```yaml
link_mode: symlink   # or 'hardlink'
```

- When set, overrides per-agent `AGENT_OPTIONS` for all agents globally.
- When absent, per-agent defaults still apply (`standard` and `openclaw` use hardlink, others use symlink).
- Propagated to `linker.link_skill()` via `link_mode_override` parameter.

### Files Changed

#### Added
- `src/skm/commands/sync.py` — implements `run_sync` and `run_sync_package`; central logic for clone, detect, link, stale-removal, lock update, changelog display.

#### Deleted
- `src/skm/commands/install.py`
- `src/skm/commands/remove.py`
- `src/skm/commands/update.py`
- `src/skm/commands/check_updates.py`

#### Modified
- `src/skm/cli.py` — replaced old subcommands with `sync` and `add`; added `AliasGroup` for `i` → `add` alias.
- `src/skm/types.py` — added `link_mode: Literal['symlink', 'hardlink'] | None` field to `SkmConfig`.
- `src/skm/linker.py` — `link_skill()` accepts `link_mode_override`; when provided, skips `AGENT_OPTIONS` lookup.
- `src/skm/git.py` — all git subprocess calls now set `GIT_TERMINAL_PROMPT=0` and `GIT_ASKPASS=echo` to prevent interactive credential prompts from blocking test runs.
- `pyproject.toml` — added `addopts = ["-m", "not network"]` so network tests are deselected by default.
- `tests/test_cli_e2e.py`, `tests/test_install.py`, `tests/test_install_from_source.py`, `tests/test_local_path.py` — updated for new `sync` / `add` commands.
- `tests/test_clonefile.py` — fixed reflink test to skip on filesystems that don't support `FICLONE` ioctl (e.g. tmpfs), rather than failing.
- `README.md`, `AGENTS.md` — updated to document new commands and `link_mode`.

### Test Results

```
101 passed, 1 skipped (reflink unsupported on tmpfs), 4 deselected (network tests)
```

---

## Session 2 — Add `justfile` and Fix `ruff` Lint Errors

### Summary

Added a `justfile` with common development recipes and fixed all errors reported by `ruff check`.

### `justfile` Recipes

| Recipe | Description |
|---|---|
| `just sync` | `uv sync --group dev` |
| `just lint` | `ruff check --fix` + `ruff format` on `src/` and `tests/` |
| `just typecheck` | `ty check src/` (Astral ty) |
| `just test [ARGS]` | `pytest -v tests/` with optional extra args |
| `just coverage` | `pytest --cov=skm-cli --cov-report=term-missing tests/` |
| `just build` | `uv build -v` |
| `just clean` | Remove `dist/`, `__pycache__`, `.pytest_cache`, etc. |

### Lint Errors Fixed

**E402 — Module level import not at top of file (3 occurrences)**

- `src/skm/cli.py`: the `from skm.*` import block was placed *after* the `AliasGroup` class definition. Moved it above the class, right after the `import click` line.
- `tests/test_cli_e2e.py`: `from skm.cli import cli` appeared after `_yaml.default_flow_style = False` (a non-import statement). Moved it above the `_yaml` setup lines.

**E741 — Ambiguous variable name `l` (4 occurrences)**

- `tests/test_cli_e2e.py` lines 394–401: four list comprehensions used `l` as the loop variable. Renamed to `line` throughout.

### Test Results

No regressions:

```
101 passed, 1 skipped, 4 deselected
```
