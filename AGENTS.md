# SKM - Skill Manager

A CLI tool that manages AI agent skills by cloning GitHub repos, detecting skills via `SKILL.md`, and linking them to agent directories based on a central YAML config.

## Tech Stack

- Python 3.12+, uv, click, pyyaml, pydantic
- Git operations via subprocess (unified `run_cmd` helper raises `click.ClickException` on failure)
- Tests: pytest

## Project Structure

```
src/skm/
├── cli.py              # Click CLI entry point (group + subcommands)
├── types.py            # Pydantic data models + constants
├── config.py           # Load/save skills.yaml → SkmConfig
├── lock.py             # Read/write skills-lock.yaml
├── detect.py           # Walk cloned repos for SKILL.md files
├── git.py              # Clone, pull, fetch, commit SHA helpers (unified run_cmd error handling)
├── utils.py            # Utility functions (compact_path)
├── linker.py           # Link skills to agent dirs, resolve includes/excludes, link_mode_override
└── commands/
    ├── sync.py         # run_sync / run_sync_package: declarative sync (clone, link, remove stale, update)
    ├── list_cmd.py     # Print installed skills from lock file
    └── view.py         # Browse skills from a repo/local path without installing
tests/
├── test_types.py            # Pydantic model validation
├── test_config.py           # Config loading, error handling
├── test_lock.py             # Lock file I/O
├── test_detect.py           # Skill detection logic
├── test_git.py              # Git operations
├── test_linker.py           # Link creation, agent filtering, link_mode_override
├── test_install.py          # Core sync unit tests (calls run_sync directly)
├── test_install_from_source.py  # E2E tests for `skm add <source>`
├── test_local_path.py       # local_path package support
└── test_cli_e2e.py          # End-to-end CLI tests for all commands
```

## Key Paths

- **Config:** `~/.config/skm/skills.yaml` — YAML dict with `packages`, optional `agents.default`, optional `link_mode`
- **Lock:** `~/.config/skm/skills-lock.yaml` — tracks installed skills, commits, link paths
- **Store:** `~/.local/share/skm/skills/` — cloned repos cached here
- **Agent dirs:** Skills are linked into each agent's skill directory (e.g. `~/.claude/skills/`, `~/.codex/skills/`)

## Architecture

Config-driven: parse `skills.yaml` → clone repos to store → detect skills by walking for `SKILL.md` → link to agent dirs → write lock file.

`run_sync` / `run_sync_package` (in `commands/sync.py`) are the central operations. The CLI `sync` and `add` commands delegate to them after resolving paths and agents.

## Error Handling

All git subprocess calls go through `run_cmd()` in `git.py`, which captures stdout/stderr and raises `click.ClickException` on non-zero exit codes.

## Path Handling

Paths stored in `skills-lock.yaml` (e.g. `linked_to`) use `compact_path()` from `utils.py` to replace the home directory with `~`. When reading these paths back for filesystem operations, `Path.expanduser()` is used.

## CLI Commands

- `skm sync` — Reconcile agent dirs to match `skills.yaml`. Clones missing repos (no pull), creates/refreshes links, removes stale links tracked in the lock, updates `skills-lock.yaml`. Idempotent. Only touches links that are tracked in `skills-lock.yaml` — manually created files in agent dirs are never removed.
- `skm sync --update` / `skm sync -U` — Same as `sync`, but also pulls latest commits from all repo packages, shows changelogs (commit range + git log), and updates commit SHAs in `skills-lock.yaml`.
- `skm add <source> [skill]` — Interactive: discover skills from a repo URL or local path, let the user pick which skills and agents to target, update `skills.yaml`, then sync just that package. Alias: `skm i`.
- `skm list` — Show installed skills and their linked paths from lock file.
- `skm list --all` — Show all skills across all agent directories, marking which are managed by skm.
- `skm view <source>` — Browse and preview skills from a repo URL or local path without installing.
- `skm edit` — Open `skills.yaml` in `$EDITOR` (falls back to system default). Shows diff after editing.

**To remove a skill:** delete it (or its package) from `skills.yaml`, then run `skm sync`. Stale links are cleaned up automatically.

## Config Format (skills.yaml)

Top-level YAML dict:

```yaml
link_mode: symlink           # optional: 'hardlink' or 'symlink'
                             # when set, overrides per-agent AGENT_OPTIONS for all agents
                             # when absent, AGENT_OPTIONS defaults apply (standard/openclaw use hardlink)

agents:
  default:                   # optional: select which KNOWN_AGENTS are active (omit = all)
    - claude
    - standard

packages:
  - repo: https://github.com/vercel-labs/agent-skills
    skills:                  # optional: filter to specific skills (omit = all)
      - react-best-practices
    agents:                  # optional: further filter agents for this package
      excludes:
        - standard
  - repo: https://github.com/blader/humanizer   # installs all detected skills to default agents
  - local_path: ~/Code/my-custom-skills         # use a local directory as package source
```

`agents.default` selects which agents from `KNOWN_AGENTS` are used as the base set. Per-package `agents.includes/excludes` then filters from that base set.

## link_mode

The optional `link_mode` field in `skills.yaml` controls how skills are linked into agent directories:

- `'symlink'` — create a symbolic link from `<agent_dir>/<skill_name>` → `<store>/<skill_name>`
- `'hardlink'` — materialize files as hardlinks (or reflinks/copies when devices differ)
- absent — use per-agent `AGENT_OPTIONS` from `types.py` (currently `standard` and `openclaw` use hardlink, others use symlink)

`link_mode_override` in `linker.link_skill()` propagates this setting at call time.

## Skill Detection

A skill is a directory containing a `SKILL.md` file with YAML frontmatter including a `name` field. Detection order:
1. Root `SKILL.md` → singleton skill (the repo itself is the skill)
2. `./skills/` subdirectory exists → walk its children
3. Otherwise → walk all subdirectories from repo root
4. Stop descending once `SKILL.md` is found (no nested skill-in-skill)

## Known Agents

Defined in `src/skm/types.py` as `KNOWN_AGENTS`:
- `standard` → `~/.agents/skills`
- `claude` → `~/.claude/skills`
- `codex` → `~/.codex/skills`
- `openclaw` → `~/.openclaw/skills`
- `pi` → `~/.pi/agent/skills`

## Testing

### Running Tests

```bash
uv sync
uv run pytest -v              # all tests
uv run pytest tests/test_cli_e2e.py -v   # e2e only
uv run pytest -k "sync" -v               # filter by name
```

### Test Isolation

All tests run entirely within pytest's `tmp_path` — no real agent directories, config files, or git repos are touched. This is achieved two ways:

- **Unit tests** (`test_install.py`, `test_linker.py`, etc.): call `run_sync` / `run_sync_package` directly with explicit `config`/`lock_path`/`store_dir`/`known_agents` parameters pointing to `tmp_path` subdirectories.
- **E2E tests** (`test_cli_e2e.py`): invoke the CLI through Click's `CliRunner` with `--config`, `--store`, `--lock`, and `--agents-dir` flags to redirect all I/O into `tmp_path`.

Git repos used in tests are local repos created via `git init` inside `tmp_path` — no network access required. Tests marked with `@pytest.mark.network` clone real GitHub repos and require internet access.

### CLI Path Overrides

The CLI group accepts four flags to override default paths, useful for both testing and safe manual experimentation:

```bash
skm --config /tmp/test.yaml \
    --store /tmp/store \
    --lock /tmp/lock.yaml \
    --agents-dir /tmp/agents \
    sync
```

- `--config` — path to `skills.yaml` (default: `~/.config/skm/skills.yaml`)
- `--lock` — path to `skills-lock.yaml` (default: `~/.config/skm/skills-lock.yaml`)
- `--store` — directory for cloned repos (default: `~/.local/share/skm/skills/`)
- `--agents-dir` — base directory for agent links; creates subdirs per agent name (overrides `KNOWN_AGENTS` paths)

### E2E Test Helpers

`test_cli_e2e.py` provides reusable helpers for writing new tests:

- `_make_skill_repo(base, repo_name, skills)` — creates a local git repo with specified skills. Each skill is `{"name": str, "subdir": bool}` where `subdir=True` (default) puts it under `skills/<name>/`, `False` makes it a singleton at repo root.
- `_cli_args(tmp_path)` — returns the common `--config/--store/--lock/--agents-dir` flags for full isolation.
- `_write_config(tmp_path, repos, agents=None)` — writes a `skills.yaml` with `{"packages": repos}` format, optionally including `agents` config.
- `_load_lock(tmp_path)` — loads the lock file as a plain dict for assertions.

### Writing New Tests

To add a new e2e test, follow this pattern:

```python
def test_my_scenario(self, tmp_path):
    repo = _make_skill_repo(tmp_path, "my-repo", [{"name": "my-skill"}])
    _write_config(tmp_path, [{"repo": str(repo)}])

    runner = CliRunner()
    result = runner.invoke(cli, [*_cli_args(tmp_path), "sync"])

    assert result.exit_code == 0, result.output
    # assert on links, lock contents, output text, etc.
```

## Development

```bash
uv sync
uv run pytest -v      # run tests
uv run skm --help     # run CLI
```

Do not run formatters or style linters on the code.