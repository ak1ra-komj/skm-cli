from pathlib import Path

import click

from skm.types import CONFIG_PATH, LOCK_PATH, STORE_DIR, KNOWN_AGENTS


@click.group()
def cli():
    """SKM - Skill Manager for AI coding agents."""
    pass


def _expand_agents() -> dict[str, str]:
    return {name: str(Path(path).expanduser()) for name, path in KNOWN_AGENTS.items()}


@cli.command()
def install():
    """Install/remove skills based on config."""
    from skm.commands.install import run_install
    agents = _expand_agents()
    run_install(
        config_path=CONFIG_PATH,
        lock_path=LOCK_PATH,
        store_dir=STORE_DIR,
        known_agents=agents,
    )


@cli.command(name="check-updates")
def check_updates():
    """Check for skill updates."""
    from skm.commands.check_updates import run_check_updates
    run_check_updates(LOCK_PATH, STORE_DIR)


@cli.command()
@click.argument("skill_name")
def update(skill_name: str):
    """Update a specific skill."""
    from skm.commands.update import run_update
    agents = _expand_agents()
    run_update(
        skill_name=skill_name,
        config_path=CONFIG_PATH,
        lock_path=LOCK_PATH,
        store_dir=STORE_DIR,
        known_agents=agents,
    )


@cli.command(name="list")
def list_skills():
    """List installed skills and their linked paths."""
    from skm.commands.list_cmd import run_list
    run_list(LOCK_PATH)
