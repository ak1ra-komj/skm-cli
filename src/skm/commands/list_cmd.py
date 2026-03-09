from pathlib import Path

import click

from skm.lock import load_lock


def run_list(lock_path: Path) -> None:
    lock = load_lock(lock_path)

    if not lock.skills:
        click.echo("No skills installed.")
        return

    for skill in lock.skills:
        click.echo(f"{skill.name}  ({skill.repo})")
        click.echo(f"  commit: {skill.commit[:8]}")
        for link in skill.linked_to:
            click.echo(f"  -> {link}")
