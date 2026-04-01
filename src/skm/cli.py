from pathlib import Path

import click

from skm.config import load_config, save_config, upsert_package
from skm.tui import interactive_multi_select
from skm.types import (
    CONFIG_PATH,
    KNOWN_AGENTS,
    LOCK_PATH,
    STORE_DIR,
    AgentsConfig,
    SkillRepoConfig,
    SkmConfig,
)


class AliasGroup(click.Group):
    """A Click group that supports hidden command aliases."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aliases: dict[str, str] = {}

    def add_alias(self, alias: str, cmd_name: str):
        self._aliases[alias] = cmd_name

    def get_command(self, ctx, cmd_name):
        cmd_name = self._aliases.get(cmd_name, cmd_name)
        return super().get_command(ctx, cmd_name)


@click.group(cls=AliasGroup)
@click.option(
    "--config",
    "config_path",
    type=click.Path(),
    default=None,
    help="Path to skills.yaml config file.",
)
@click.option(
    "--store",
    "store_dir",
    type=click.Path(),
    default=None,
    help="Path to skill store directory.",
)
@click.option(
    "--lock",
    "lock_path",
    type=click.Path(),
    default=None,
    help="Path to skills-lock.yaml lock file.",
)
@click.option(
    "--agents-dir",
    "agents_dir",
    type=click.Path(),
    default=None,
    help="Base directory for agent skill symlinks (overrides all known agents).",
)
@click.pass_context
def cli(ctx, config_path, store_dir, lock_path, agents_dir):
    """SKM - Skill Manager for AI coding agents."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = Path(config_path) if config_path else CONFIG_PATH
    ctx.obj["lock_path"] = Path(lock_path) if lock_path else LOCK_PATH
    ctx.obj["store_dir"] = Path(store_dir) if store_dir else STORE_DIR
    ctx.obj["agents_dir"] = agents_dir


def _expand_agents(
    agents_dir: str | None = None, default_agents: list[str] | None = None
) -> dict[str, str]:
    agents = KNOWN_AGENTS
    if default_agents is not None:
        agents = {k: v for k, v in agents.items() if k in default_agents}
    if agents_dir:
        base = Path(agents_dir)
        return {name: str(base / name) for name in agents}
    return {name: str(Path(path).expanduser()) for name, path in agents.items()}


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--update",
    "-U",
    "do_update",
    is_flag=True,
    default=False,
    help="Pull latest from all repos, show changelogs, and update skills-lock.yaml.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Override existing non-managed skill directories without prompting.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Show detailed output for every operation.",
)
@click.pass_context
def sync(ctx, do_update, force, verbose):
    """Sync skills to match skills.yaml (add new, remove stale, optionally update repos).

    Reads skills.yaml as the source of truth: clones missing repos, creates or
    refreshes links for all configured skills, removes links for skills/packages
    that are no longer configured, and writes skills-lock.yaml.

    Only links tracked in skills-lock.yaml are ever removed — manually created
    files in agent directories are never touched.

    With --update / -U, also pulls the latest commits from every configured repo
    and updates the commit SHAs recorded in skills-lock.yaml.

    To remove a skill, delete it from skills.yaml and re-run skm sync.
    """
    from skm.commands.sync import run_sync

    config_path = ctx.obj["config_path"]
    try:
        config = load_config(config_path)
    except FileNotFoundError:
        raise click.ClickException(
            f"Config file not found: {config_path}\n"
            "Create one manually or use `skm add <source>` to add your first package."
        )

    default_agents = config.agents.default if config.agents else None
    agents = _expand_agents(ctx.obj["agents_dir"], default_agents)
    run_sync(
        config=config,
        lock_path=ctx.obj["lock_path"],
        store_dir=ctx.obj["store_dir"],
        known_agents=agents,
        force=force,
        verbose=verbose,
        update=do_update,
    )


# ---------------------------------------------------------------------------
# add  (interactive: discover skills from a source, update config, then sync)
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("source")
@click.argument("skill_name", required=False, default=None)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Override existing non-symlink skill directories without prompting.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Show detailed output for every operation.",
)
@click.option(
    "--agents-includes",
    default=None,
    help="Comma-separated agents to include (skips interactive).",
)
@click.option(
    "--agents-excludes",
    default=None,
    help="Comma-separated agents to exclude (skips interactive).",
)
@click.pass_context
def add(ctx, source, skill_name, force, verbose, agents_includes, agents_excludes):
    """Add skills from a source to skills.yaml, then install them.

    SOURCE can be a repo URL or local path.
    SKILL_NAME optionally specifies a single skill to add from the source.

    Detects available skills in SOURCE, lets you choose interactively (unless
    SKILL_NAME is given), updates skills.yaml, and installs the new skills.
    """
    from skm.commands.sync import run_sync_package
    from skm.detect import detect_skills
    from skm.git import clone_or_pull, repo_url_to_dirname
    from skm.lock import load_lock

    if agents_includes and agents_excludes:
        raise click.ClickException(
            "Cannot specify both --agents-includes and --agents-excludes"
        )

    # Resolve source
    source_path = Path(source).expanduser()
    if source_path.is_dir():
        repo_path = source_path
        is_local = True
    else:
        dest = ctx.obj["store_dir"] / repo_url_to_dirname(source)
        clone_or_pull(source, dest)
        repo_path = dest
        is_local = False

    # Load or create config
    config_path = ctx.obj["config_path"]
    if config_path.exists():
        config = load_config(config_path)
    else:
        config = SkmConfig(packages=[])

    # If a skill_name was given and the source is already configured with skills: None,
    # check whether the skill is already linked (no-op) or needs a re-sync.
    if skill_name:
        source_key = str(source_path) if is_local else source
        existing_pkg = _find_package_by_source(config, source_key, is_local)
        if existing_pkg and existing_pkg.skills is None:
            lock = load_lock(ctx.obj["lock_path"])
            skill_installed = any(
                s.name == skill_name
                and (s.local_path or s.repo)
                and _source_matches(s, source_key, is_local)
                for s in lock.skills
            )
            if skill_installed:
                click.echo(
                    f'Skill "{skill_name}" is already installed from this source (all skills configured).'
                )
                return
            else:
                # Re-sync just this package to pick up newly added skills
                default_agents = config.agents.default if config.agents else None
                agents = _expand_agents(ctx.obj["agents_dir"], default_agents)
                run_sync_package(
                    repo_config=existing_pkg,
                    lock_path=ctx.obj["lock_path"],
                    store_dir=ctx.obj["store_dir"],
                    known_agents=agents,
                    force=force,
                    verbose=verbose,
                    link_mode=config.link_mode,
                )
                return

    # Detect skills in the source
    detected = detect_skills(repo_path)
    if not detected:
        click.echo("No skills found in source.")
        return

    # Select which skills to add
    if skill_name:
        matched = [s for s in detected if s.name == skill_name]
        if not matched:
            raise click.ClickException(
                f'Skill "{skill_name}" not found in source. Available: {", ".join(s.name for s in detected)}'
            )
        selected_skills = matched
    else:
        labels = [f"{s.name}  ({s.relative_path})" for s in detected]
        indices = interactive_multi_select(labels, header="Select skills to add:")
        if indices is None:
            click.echo("Cancelled.")
            return
        selected_skills = [detected[i] for i in indices]

    if not selected_skills:
        click.echo("No skills selected.")
        return

    # Determine agents config
    existing_pkg = _find_package_by_source(
        config,
        SkillRepoConfig(
            repo=source if not is_local else None,
            local_path=str(source_path) if is_local else None,
        ).source_key,
        is_local,
    )
    if agents_includes:
        agents_config = AgentsConfig(
            includes=[a.strip() for a in agents_includes.split(",")]
        )
    elif agents_excludes:
        agents_config = AgentsConfig(
            excludes=[a.strip() for a in agents_excludes.split(",")]
        )
    elif existing_pkg is not None:
        agents_config = existing_pkg.agents
    else:
        agent_names = list(KNOWN_AGENTS.keys())
        default_agents_list = config.agents.default if config.agents else None
        if default_agents_list:
            preselected = {
                i for i, name in enumerate(agent_names) if name in default_agents_list
            }
        else:
            preselected = None  # all selected

        agent_indices = interactive_multi_select(
            agent_names, header="Select agents:", preselected=preselected
        )
        if agent_indices is None:
            click.echo("Cancelled.")
            return

        selected_agent_names = [agent_names[i] for i in agent_indices]
        if set(selected_agent_names) == set(agent_names):
            agents_config = None  # all agents — no filter needed
        else:
            agents_config = AgentsConfig(includes=selected_agent_names)

    # Build SkillRepoConfig
    skill_names = [s.name for s in selected_skills]
    config_skills = None if len(selected_skills) == len(detected) else skill_names

    if is_local:
        new_pkg = SkillRepoConfig(
            local_path=str(source_path), skills=config_skills, agents=agents_config
        )
    else:
        new_pkg = SkillRepoConfig(
            repo=source, skills=config_skills, agents=agents_config
        )

    upsert_package(config, new_pkg)
    save_config(config, config_path)
    click.echo(f"Config saved: {config_path}")

    pkg_to_install = (
        _find_package_by_source(config, new_pkg.source_key, is_local) or new_pkg
    )

    default_agents = config.agents.default if config.agents else None
    agents = _expand_agents(ctx.obj["agents_dir"], default_agents)
    run_sync_package(
        repo_config=pkg_to_install,
        lock_path=ctx.obj["lock_path"],
        store_dir=ctx.obj["store_dir"],
        known_agents=agents,
        force=force,
        verbose=verbose,
        link_mode=config.link_mode,
    )


cli.add_alias("i", "add")


def _find_package_by_source(
    config: SkmConfig, source_key: str, is_local: bool
) -> SkillRepoConfig | None:
    """Find existing package in config matching the source."""
    for pkg in config.packages:
        if is_local and pkg.local_path:
            if str(Path(pkg.local_path).expanduser()) == str(
                Path(source_key).expanduser()
            ):
                return pkg
        elif not is_local and pkg.repo:
            if pkg.repo == source_key:
                return pkg
    return None


def _source_matches(installed_skill, source_key: str, is_local: bool) -> bool:
    """Check if an InstalledSkill matches the given source."""
    if is_local:
        return installed_skill.local_path is not None and str(
            Path(installed_skill.local_path).expanduser()
        ) == str(Path(source_key).expanduser())
    return installed_skill.repo == source_key


# ---------------------------------------------------------------------------
# view
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("source")
@click.pass_context
def view(ctx, source: str):
    """Browse and read skills from a repo or local path."""
    from skm.commands.view import run_view

    run_view(source=source, store_dir=ctx.obj["store_dir"])


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


@cli.command()
@click.pass_context
def edit(ctx):
    """Open skills.yaml in your editor."""
    import os
    import platform
    import subprocess

    config_path = ctx.obj["config_path"]
    if not config_path.exists():
        raise click.ClickException(f"Config file not found: {config_path}")

    editor = os.environ.get("EDITOR")
    if editor:
        import shutil
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".yaml", delete=False)
        tmp.close()
        shutil.copy2(config_path, tmp.name)
        try:
            subprocess.call([editor, str(config_path)])
            if shutil.which("diff"):
                result = subprocess.run(
                    ["diff", "--color=always", tmp.name, str(config_path)],
                    capture_output=True,
                    text=True,
                )
                if result.stdout:
                    click.echo(result.stdout)
                else:
                    click.echo("No changes.")
        finally:
            os.unlink(tmp.name)
    elif platform.system() == "Darwin":
        subprocess.call(["open", str(config_path)])
    elif platform.system() == "Windows":
        os.startfile(str(config_path))
    else:
        subprocess.call(["xdg-open", str(config_path)])


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@cli.command(name="list")
@click.argument("skill_name", required=False, default=None)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="Show all skills in each agent directory, including unmanaged ones.",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Show skill paths and symlink targets.",
)
@click.pass_context
def list_skills(ctx, skill_name: str | None, show_all: bool, verbose: bool):
    """List installed skills and their linked paths."""
    from skm.commands.list_cmd import run_list, run_list_all

    if show_all:
        config = load_config(ctx.obj["config_path"])
        default_agents = config.agents.default if config.agents else None
        agents = _expand_agents(ctx.obj["agents_dir"], default_agents)
        run_list_all(ctx.obj["lock_path"], agents)
    else:
        run_list(ctx.obj["lock_path"], verbose=verbose, skill_name=skill_name)
