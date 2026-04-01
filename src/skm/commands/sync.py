import shutil
import sys
from pathlib import Path

import click

from skm.detect import detect_skills
from skm.git import clone_or_pull, get_head_commit, get_log_between, repo_url_to_dirname
from skm.linker import link_skill, resolve_target_agents
from skm.lock import load_lock, save_lock
from skm.types import InstalledSkill, LockFile, SkillRepoConfig, SkmConfig
from skm.utils import compact_path

STATUS_COLORS = {
    "new": "green",
    "exists": None,  # dim
    "replaced": "magenta",
}


def _progress(msg: str) -> None:
    """Write a single refreshing progress line to stderr."""
    sys.stderr.write(f"\r\033[K{msg}")
    sys.stderr.flush()


def _clear_progress() -> None:
    """Clear the progress line."""
    sys.stderr.write("\r\033[K")
    sys.stderr.flush()


def _confirm_override(message: str) -> bool:
    """Prompt user with a y/n question, returns on single keypress."""
    _clear_progress()
    click.echo(f"{message} [y/N] ", nl=False)
    c = click.getchar()
    click.echo()  # newline after keypress
    return c in ("y", "Y")


def _format_link_status(status: str) -> str:
    """Format a status annotation for verbose mode."""
    color = STATUS_COLORS.get(status)
    text = f"({status})"
    if color:
        return click.style(text, fg=color)
    return click.style(text, dim=True)


def _dedup_skills(skills, source_label, verbose=False):
    """Deduplicate skills by name, warning about duplicates."""
    seen = {}
    result = []
    for skill in skills:
        if skill.name in seen:
            prev = seen[skill.name]
            msg = (
                f'  Warning: duplicate skill name "{skill.name}" '
                f"(from {skill.relative_path}, already seen from {prev.relative_path}), skipping"
            )
            if not verbose:
                _clear_progress()
            click.echo(click.style(msg, fg="red"))
            continue
        seen[skill.name] = skill
        result.append(skill)
    return result


def run_sync(
    config: SkmConfig,
    lock_path: Path,
    store_dir: Path,
    known_agents: dict[str, str],
    force: bool = False,
    verbose: bool = False,
    update: bool = False,
) -> None:
    """Sync skills to match skills.yaml.

    Clones missing repos, links all configured skills, removes stale links,
    and updates skills-lock.yaml.  When update=True, also pulls existing repos
    and shows changelogs before relinking.
    """
    link_mode = config.link_mode  # None → fall back to per-agent AGENT_OPTIONS
    lock = load_lock(lock_path)
    new_lock_skills: list[InstalledSkill] = []

    # Track which (skill_name, source_key) pairs are still configured
    configured_skill_keys: set[tuple[str, str]] = set()

    added_count = 0
    all_deferred_lines: list[str] = []

    for repo_config in config.packages:
        if repo_config.is_local:
            count, lines = _sync_local(
                repo_config,
                new_lock_skills,
                configured_skill_keys,
                known_agents,
                force,
                verbose,
                link_mode,
            )
        else:
            count, lines = _sync_repo(
                repo_config,
                store_dir,
                new_lock_skills,
                configured_skill_keys,
                known_agents,
                force,
                verbose,
                link_mode,
                pull_if_exists=update,
            )

        added_count += count
        all_deferred_lines.extend(lines)

        if verbose:
            click.echo()

    if not verbose:
        _clear_progress()
        for line in all_deferred_lines:
            click.echo(line)

    # Build set of all new linked paths for stale-link detection
    new_linked_paths: set[str] = set()
    for skill in new_lock_skills:
        for lp in skill.linked_to:
            new_linked_paths.add(lp)

    # Remove stale links: any old linked_to path not present in new state
    stale_header_printed = False
    removed_count = 0
    for old_skill in lock.skills:
        old_source = old_skill.repo or old_skill.local_path or ""
        skill_still_configured = (old_skill.name, old_source) in configured_skill_keys

        for link_path_str in old_skill.linked_to:
            if link_path_str not in new_linked_paths:
                p = Path(link_path_str).expanduser()
                reason = (
                    "agent config changed"
                    if skill_still_configured
                    else "no longer in config"
                )
                if p.is_symlink() or p.is_dir():
                    if not stale_header_printed:
                        click.echo()
                        click.echo(
                            click.style("Removing stale links", fg="red", bold=True)
                        )
                        stale_header_printed = True
                    if p.is_symlink():
                        p.unlink()
                    else:
                        shutil.rmtree(p)
                    click.echo(
                        click.style(
                            f"  {compact_path(link_path_str)} for {old_skill.name} ({reason})",
                            fg="red",
                        )
                    )
                    removed_count += 1

    # Summary line
    if not verbose:
        if added_count == 0 and removed_count == 0:
            click.echo("up to date")
        else:
            parts = []
            if added_count > 0:
                parts.append(
                    f"added {added_count} skill{'s' if added_count != 1 else ''}"
                )
            if removed_count > 0:
                parts.append(
                    f"removed {removed_count} skill{'s' if removed_count != 1 else ''}"
                )
            click.echo()
            click.echo(", ".join(parts))

    new_lock = LockFile(skills=new_lock_skills)
    save_lock(new_lock, lock_path)
    click.echo(f"Lock file updated: {lock_path}")


def _sync_local(
    repo_config,
    new_lock_skills,
    configured_skill_keys,
    known_agents,
    force=False,
    verbose=False,
    link_mode=None,
):
    """Sync skills from a local path. Returns (added_count, deferred_lines)."""
    local_path = Path(repo_config.local_path).expanduser()
    source_label = compact_path(str(local_path))

    if verbose:
        click.echo(
            click.style(f"Using local path {source_label}", fg="blue", bold=True)
        )

    detected = detect_skills(local_path)
    if verbose:
        click.echo(
            click.style(
                f"  Found skills: {', '.join(s.name for s in detected) or '(none)'}",
                dim=True,
            )
        )

    target_agents = resolve_target_agents(repo_config.agents, known_agents)

    if repo_config.skills is not None:
        requested = set(repo_config.skills)
        skills_to_install = [s for s in detected if s.name in requested]
        missing = requested - {s.name for s in skills_to_install}
        if missing:
            click.echo(click.style(f"  Warning: skills not found: {missing}", fg="red"))
    else:
        skills_to_install = detected

    skills_to_install = _dedup_skills(skills_to_install, source_label, verbose)

    added_count = 0
    deferred_lines: list[str] = []

    for skill in skills_to_install:
        configured_skill_keys.add((skill.name, compact_path(str(local_path))))
        linked_paths = []
        skill_changed = False
        skill_lines: list[str] = []

        if not verbose:
            _progress(f"  {skill.name}")
        else:
            click.echo(click.style(f"  Install skill {skill.name}", fg="yellow"))

        for agent_name, agent_dir in target_agents.items():
            try:
                link, status = link_skill(
                    skill.path,
                    skill.name,
                    agent_dir,
                    agent_name=agent_name,
                    link_mode_override=link_mode,
                )
            except FileExistsError as e:
                if force or _confirm_override(f"  {e}. Override?"):
                    if verbose:
                        click.echo(
                            click.style(
                                f"  Overriding existing skill {skill.name}",
                                fg="magenta",
                            )
                        )
                    link, status = link_skill(
                        skill.path,
                        skill.name,
                        agent_dir,
                        force=True,
                        agent_name=agent_name,
                        link_mode_override=link_mode,
                    )
                else:
                    if verbose:
                        click.echo(
                            click.style(
                                f"  Skipped {skill.name} for [{agent_name}]", dim=True
                            )
                        )
                    continue

            linked_paths.append(compact_path(str(link)))
            link_line = f"    {skill.name} -> [{agent_name}] {compact_path(str(link))}"

            if verbose:
                click.echo(f"  {link_line} {_format_link_status(status)}")
            else:
                if status != "exists":
                    skill_changed = True
                    skill_lines.append(link_line)

        if not verbose and skill_changed:
            added_count += 1
            deferred_lines.append(
                click.style(f"  {skill.name}", fg="yellow") + f" from {source_label}"
            )
            deferred_lines.extend(skill_lines)

        new_lock_skills.append(
            InstalledSkill(
                name=skill.name,
                local_path=compact_path(str(local_path)),
                commit=None,
                skill_path=skill.relative_path,
                linked_to=linked_paths,
            )
        )

    return added_count, deferred_lines


def _sync_repo(
    repo_config,
    store_dir,
    new_lock_skills,
    configured_skill_keys,
    known_agents,
    force=False,
    verbose=False,
    link_mode=None,
    pull_if_exists=False,
):
    """Sync skills from a git repo. Returns (added_count, deferred_lines).

    When pull_if_exists=True the repo is pulled even if already cloned, and
    a changelog is printed when the commit advances.
    """
    repo_dir_name = repo_url_to_dirname(repo_config.repo)
    repo_path = store_dir / repo_dir_name

    was_existing = repo_path.exists() and (repo_path / ".git").exists()
    old_commit_for_update: str | None = None

    if pull_if_exists and was_existing:
        old_commit_for_update = get_head_commit(repo_path)
        if not verbose:
            _progress(f"  Pulling {repo_config.repo}...")
        else:
            click.echo(
                click.style(f"Pulling {repo_config.repo}...", fg="blue", bold=True)
            )
        clone_or_pull(repo_config.repo, repo_path)
    elif was_existing:
        if verbose:
            click.echo(
                click.style(f"Using existing {repo_config.repo}", fg="blue", bold=True)
            )
    else:
        if not verbose:
            _progress(f"  Cloning {repo_config.repo}...")
        else:
            click.echo(
                click.style(f"Cloning {repo_config.repo}...", fg="blue", bold=True)
            )
        clone_or_pull(repo_config.repo, repo_path)

    commit = get_head_commit(repo_path)

    # Show changelog when --update pulled an existing repo
    if old_commit_for_update is not None:
        if not verbose:
            _clear_progress()
        if old_commit_for_update != commit:
            log = get_log_between(repo_path, old_commit_for_update, commit)
            click.echo(click.style(f"  {repo_config.repo}", fg="cyan"))
            click.echo(
                f"  {click.style(old_commit_for_update[:8], fg='red')}"
                f" → {click.style(commit[:8], fg='green')}"
            )
            if log:
                for line in log.splitlines():
                    click.echo(click.style(f"    {line}", dim=True))
        else:
            click.echo(
                click.style(
                    f"  ✔ {repo_config.repo} already up to date ({commit[:8]})",
                    fg="green",
                )
            )

    detected = detect_skills(repo_path)
    if verbose:
        click.echo(
            click.style(
                f"  Found skills: {', '.join(s.name for s in detected) or '(none)'}",
                dim=True,
            )
        )

    target_agents = resolve_target_agents(repo_config.agents, known_agents)

    if repo_config.skills is not None:
        requested = set(repo_config.skills)
        skills_to_install = [s for s in detected if s.name in requested]
        missing = requested - {s.name for s in skills_to_install}
        if missing and was_existing and not pull_if_exists:
            # Repo was already cloned but requested skills are missing — pull and retry
            if not verbose:
                _progress(
                    f"  Pulling {repo_config.repo}"
                    f" (missing skills: {', '.join(sorted(missing))})..."
                )
            else:
                click.echo(
                    click.style(
                        f"  Pulling {repo_config.repo} (missing skills: {', '.join(sorted(missing))})...",
                        fg="blue",
                    )
                )
            clone_or_pull(repo_config.repo, repo_path)
            commit = get_head_commit(repo_path)
            detected = detect_skills(repo_path)
            if verbose:
                click.echo(
                    click.style(
                        f"  Found skills after pull: {', '.join(s.name for s in detected) or '(none)'}",
                        dim=True,
                    )
                )
            skills_to_install = [s for s in detected if s.name in requested]
            still_missing = requested - {s.name for s in skills_to_install}
            if still_missing:
                click.echo(
                    click.style(
                        f"  Warning: skills not found in repo: {still_missing}",
                        fg="red",
                    )
                )
        elif missing:
            click.echo(
                click.style(f"  Warning: skills not found in repo: {missing}", fg="red")
            )
    else:
        skills_to_install = detected

    skills_to_install = _dedup_skills(skills_to_install, repo_config.repo, verbose)

    added_count = 0
    deferred_lines: list[str] = []

    for skill in skills_to_install:
        configured_skill_keys.add((skill.name, repo_config.repo))
        linked_paths = []
        skill_changed = False
        skill_lines: list[str] = []

        if not verbose:
            _progress(f"  {skill.name}")
        else:
            click.echo(click.style(f"  Install skill {skill.name}", fg="yellow"))

        for agent_name, agent_dir in target_agents.items():
            try:
                link, status = link_skill(
                    skill.path,
                    skill.name,
                    agent_dir,
                    agent_name=agent_name,
                    link_mode_override=link_mode,
                )
            except FileExistsError as e:
                if force or _confirm_override(f"  {e}. Override?"):
                    if verbose:
                        click.echo(
                            click.style(
                                f"  Overriding existing skill {skill.name}",
                                fg="magenta",
                            )
                        )
                    link, status = link_skill(
                        skill.path,
                        skill.name,
                        agent_dir,
                        force=True,
                        agent_name=agent_name,
                        link_mode_override=link_mode,
                    )
                else:
                    if verbose:
                        click.echo(
                            click.style(
                                f"  Skipped {skill.name} for [{agent_name}]", dim=True
                            )
                        )
                    continue

            linked_paths.append(compact_path(str(link)))
            link_line = f"    {skill.name} -> [{agent_name}] {compact_path(str(link))}"

            if verbose:
                click.echo(f"  {link_line} {_format_link_status(status)}")
            else:
                if status != "exists":
                    skill_changed = True
                    skill_lines.append(link_line)

        if not verbose and skill_changed:
            added_count += 1
            deferred_lines.append(
                click.style(f"  {skill.name}", fg="yellow")
                + f" from {repo_config.repo}"
            )
            deferred_lines.extend(skill_lines)

        new_lock_skills.append(
            InstalledSkill(
                name=skill.name,
                repo=repo_config.repo,
                commit=commit,
                skill_path=skill.relative_path,
                linked_to=linked_paths,
            )
        )

    return added_count, deferred_lines


def run_sync_package(
    repo_config: SkillRepoConfig,
    lock_path: Path,
    store_dir: Path,
    known_agents: dict[str, str],
    force: bool = False,
    verbose: bool = False,
    update: bool = False,
    link_mode: str | None = None,
) -> None:
    """Sync a single package and merge results into the existing lock file.

    Used by `skm add` after interactively updating skills.yaml for one package.
    """
    lock = load_lock(lock_path)
    new_lock_skills: list[InstalledSkill] = []
    configured_skill_keys: set[tuple[str, str]] = set()

    if repo_config.is_local:
        added_count, deferred_lines = _sync_local(
            repo_config,
            new_lock_skills,
            configured_skill_keys,
            known_agents,
            force,
            verbose,
            link_mode,
        )
    else:
        added_count, deferred_lines = _sync_repo(
            repo_config,
            store_dir,
            new_lock_skills,
            configured_skill_keys,
            known_agents,
            force,
            verbose,
            link_mode,
            pull_if_exists=update,
        )

    if not verbose:
        _clear_progress()
        for line in deferred_lines:
            click.echo(line)

    if verbose:
        click.echo()
    else:
        if added_count == 0:
            click.echo("up to date")
        else:
            click.echo()
            click.echo(f"added {added_count} skill{'s' if added_count != 1 else ''}")

    # Merge: keep existing lock entries from other sources, replace entries from this source
    source_key = repo_config.source_key
    merged_skills = []
    for existing in lock.skills:
        existing_source = existing.repo or existing.local_path or ""
        # Keep entries not from this source
        if existing_source != source_key:
            if not (
                repo_config.is_local
                and existing.local_path
                and str(Path(existing.local_path).expanduser())
                == str(Path(source_key).expanduser())
            ):
                merged_skills.append(existing)
    merged_skills.extend(new_lock_skills)

    new_lock = LockFile(skills=merged_skills)
    save_lock(new_lock, lock_path)
    click.echo(f"Lock file updated: {lock_path}")
