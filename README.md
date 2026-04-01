# SKM - Skill Manager

A CLI tool that manages **global** AI agent skills from GitHub repos or local directories. Clone repos or link local paths, detect skills via `SKILL.md`, and symlink them into agent directories — all driven by a single YAML config.

> **Note:** skm manages skills at the user level (e.g. `~/.claude/skills/`), not at the project level. It is not intended for installing skills into project-scoped directories.

![skm install](images/skm-install.png)

## Install

```bash
uv tool install skm-cli
```

Or install from source:

```bash
uv tool install git+https://github.com/reorx/skm
```

## Quick Start

1. Create `~/.config/skm/skills.yaml`:

```yaml
packages:
  - repo: https://github.com/vercel-labs/agent-skills
    skills:
      - vercel-react-best-practices
      - vercel-react-native-skills
  - repo: https://github.com/blader/humanizer
  - local_path: ~/Code/my-custom-skills       # use a local directory instead of a git repo
```

2. Run sync (`skm sync` syncs everything to match your config):

```bash
skm sync
```

Skills are cloned (or linked from local paths) into your agent directories (`~/.claude/skills/`, `~/.codex/skills/`, etc.).

### Add skills from a source directly

You can also add skills directly from a repo URL or local path — no need to edit `skills.yaml` first:

```bash
# Add from a GitHub repo (interactive skill & agent selection)
skm add https://github.com/vercel-labs/agent-skills

# Add a specific skill by name
skm add https://github.com/vercel-labs/agent-skills vercel-react-best-practices

# Add from a local directory
skm add ~/Code/my-custom-skills

# Skip interactive prompts with --agents-includes / --agents-excludes
skm add https://github.com/blader/humanizer --agents-includes claude,codex
```

This detects available skills, lets you pick which ones to add (unless a specific skill name is given), and automatically updates your `skills.yaml` config, then installs the new skills.

## Commands

| Command | Description |
|---|---|
| `skm sync` | Reconcile agent dirs to match `skills.yaml`. Clones missing repos, creates/refreshes links, removes stale links, writes lock file. Idempotent — only touches links tracked in `skills-lock.yaml`. |
| `skm sync --update` (or `skm sync -U`) | Same as `sync`, but also pulls latest commits from all repo packages, shows changelogs, and updates commit SHAs in the lock file. |
| `skm add <source> [skill]` (or `skm i`) | Add skills from a repo URL or local path. Interactively select skills and agents, update `skills.yaml`, then sync that package. |
| `skm list` | Show installed skills and their linked paths. |
| `skm list --all` | Show all skills across all agent directories, marking which are managed by skm. |
| `skm view <source>` | Browse and preview skills from a repo URL or local path without installing. |
| `skm edit` | Open `skills.yaml` in `$EDITOR` (falls back to system default). Shows diff after editing. |

**To remove a skill:** delete it (or its entire package) from `skills.yaml`, then run `skm sync`. Stale links are cleaned up automatically.

## Config Format

`~/.config/skm/skills.yaml`:

```yaml
link_mode: symlink           # optional: 'hardlink' or 'symlink' — see Link Mode below

agents:
  default:                   # optional: select which agents are active (omit = all)
    - claude
    - standard

packages:
  - repo: https://github.com/vercel-labs/agent-skills
    skills:                  # optional: install only these skills (omit = all)
      - vercel-react-best-practices
    agents:                  # optional: further filter agents for this package
      excludes:
        - standard

  - repo: https://github.com/blader/humanizer   # installs all detected skills to default agents

  - local_path: ~/Code/my-custom-skills         # use a local directory as package source
    skills:
      - my-skill
```

Each package must specify exactly one of `repo` or `local_path`. Local path packages use the directory directly (no cloning) and are not updated by `skm sync --update`.

## Sync Behavior

`skm sync` treats `skills.yaml` as a declarative state file. Each run reconciles agent directories to match the config:

- **New skills** (added to config) are linked to agent directories.
- **Removed skills** (dropped from `skills:` list, or entire package removed) have their links deleted.
- **Agent config changes** (e.g. adding `excludes: [openclaw]`) remove links from excluded agents while keeping links in others.
- **`--update` / `-U`** additionally pulls every repo package, shows a commit changelog, and updates the lock file with new commit SHAs.

Only links tracked in `skills-lock.yaml` are affected. Manually created files or skills installed by other tools in agent directories are never touched.

## Skill Detection

A skill is a directory containing a `SKILL.md` file with YAML frontmatter (`name` field required). Detection order:

1. Root `SKILL.md` — the repo itself is a singleton skill
2. `./skills/` subdirectory exists — scan its children
3. Otherwise — walk all subdirectories from repo root
4. Stop descending once `SKILL.md` is found (no nested skills)

## Known Agents

Skills are symlinked into these directories by default:

| Agent | Path |
|---|---|
| `standard` | `~/.agents/skills/` |
| `claude` | `~/.claude/skills/` |
| `codex` | `~/.codex/skills/` |
| `openclaw` | `~/.openclaw/skills/` |

## Copy Strategy

When skm links a skill into an agent directory, it picks a strategy based on the agent config and filesystem:

### 0. Configured via `link_mode`

Set `link_mode: symlink` or `link_mode: hardlink` at the top of `skills.yaml` to override the default for all agents globally. When unset, per-agent `AGENT_OPTIONS` apply (see below).

### 1. Symlink (default for most agents)

A symbolic link from `<agent_dir>/skills/<skill_name>` → `<store>/<skill_name>`. This is the default for `claude`, `codex`, and `pi`. Changes in the store are immediately visible.

### 2. Hardlink (default for `standard` and `openclaw`)

When `use_hardlink: true` is set for an agent in `AGENT_OPTIONS`, skm creates hardlinks instead. Each file in the skill directory gets its own hardlink pointing to the same inode as the source. This only works when source and target are on the **same filesystem/device**.

### 3. Reflink (copy-on-write)

When hardlinks can't be used (source and target on **different devices**), skm attempts a reflink/COW clone. This creates an independent copy that shares physical disk blocks with the source until either side is modified — fast and space-efficient.

The reflink backend is platform-specific:

| Platform | Mechanism | Supported filesystems |
|---|---|---|
| **Linux** | `FICLONE` ioctl (`fcntl.ioctl`) | Btrfs, XFS, OCFS2, and others with reflink support |
| **macOS** | `clonefile(2)` syscall (via `ctypes`) | APFS (default since macOS 10.13) |

### 4. Plain copy (fallback)

If reflink is not available (unsupported filesystem, non-Unix platform, etc.), skm falls back to a plain `shutil.copy2` — a full byte copy with metadata preserved.

### Selection flow

```
link_mode set in skills.yaml?
├── symlink → symlink (all agents)
├── hardlink → hardlink / reflink / copy (all agents, same flow as below)
└── not set → per-agent AGENT_OPTIONS
    └── use_hardlink enabled?
        ├── No  → symlink
        └── Yes → same device?
            ├── Yes → hardlink
            └── No  → reflink supported?
                ├── Yes → reflink (COW clone)
                └── No  → plain copy
```

The reflink implementation is isolated in `src/skm/clonefile.py` with dedicated tests in `tests/test_clonefile.py`.

## CLI Path Overrides

Override default paths for testing or custom setups:

```bash
skm --config /tmp/test.yaml \
    --store /tmp/store \
    --lock /tmp/lock.yaml \
    --agents-dir /tmp/agents \
    sync
```

## Key Paths

- **Config:** `~/.config/skm/skills.yaml`
- **Lock:** `~/.config/skm/skills-lock.yaml`
- **Store:** `~/.local/share/skm/skills/`

## Development

```bash
uv sync
uv run pytest -v      # run tests
uv run skm --help     # run CLI
```
