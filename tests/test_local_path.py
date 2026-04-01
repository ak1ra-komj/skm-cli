"""BDD tests for local_path package support."""

from pathlib import Path

import pytest

from skm.commands.sync import run_sync
from skm.config import load_config
from skm.lock import load_lock
from skm.types import SkillRepoConfig


def _make_local_skills_dir(tmp_path, skills: list[str]) -> Path:
    """Create a local directory with skill subdirectories (each with SKILL.md)."""
    local_dir = tmp_path / "local-skills"
    local_dir.mkdir()
    for name in skills:
        skill_dir = local_dir / name
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: test\n---\nContent\n"
        )
    return local_dir


# --- Config validation ---


def test_config_mutual_exclusion():
    """Both repo and local_path set should raise validation error."""
    with pytest.raises(ValueError, match="exactly one"):
        SkillRepoConfig(repo="https://github.com/foo/bar", local_path="~/Code/scripts")


def test_config_neither_set():
    """Neither repo nor local_path set should raise validation error."""
    with pytest.raises(ValueError, match="exactly one"):
        SkillRepoConfig()


def test_config_local_path_valid():
    """local_path alone is valid."""
    cfg = SkillRepoConfig(local_path="~/Code/scripts")
    assert cfg.local_path == "~/Code/scripts"
    assert cfg.repo is None
    assert cfg.is_local is True


def test_config_repo_valid():
    """repo alone is still valid."""
    cfg = SkillRepoConfig(repo="https://github.com/foo/bar")
    assert cfg.is_local is False


def test_config_source_key():
    """source_key returns the appropriate identifier."""
    cfg_repo = SkillRepoConfig(repo="https://github.com/foo/bar")
    assert cfg_repo.source_key == "https://github.com/foo/bar"

    cfg_local = SkillRepoConfig(local_path="~/Code/scripts")
    assert cfg_local.source_key == str(Path("~/Code/scripts").expanduser())


# --- Install from local_path ---


def test_install_local_path(tmp_path):
    """Install from local_path, verify symlinks point directly to local dir."""
    local_dir = _make_local_skills_dir(tmp_path, ["my-skill", "other-skill"])

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"packages:\n  - local_path: {local_dir}\n")

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"
    agents = {"claude": str(tmp_path / "agents" / "claude" / "skills")}

    config = load_config(config_path)
    run_sync(
        config=config, lock_path=lock_path, store_dir=store_dir, known_agents=agents
    )

    # Both skills should be symlinked
    link1 = tmp_path / "agents" / "claude" / "skills" / "my-skill"
    link2 = tmp_path / "agents" / "claude" / "skills" / "other-skill"
    assert link1.is_symlink()
    assert link2.is_symlink()
    # Symlinks should point into the local dir, not store_dir
    assert link1.resolve() == (local_dir / "my-skill").resolve()
    assert link2.resolve() == (local_dir / "other-skill").resolve()


def test_install_local_path_no_clone(tmp_path):
    """Verify no clone happens and no store_dir is used for local_path."""
    local_dir = _make_local_skills_dir(tmp_path, ["my-skill"])

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"packages:\n  - local_path: {local_dir}\n")

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"
    agents = {"claude": str(tmp_path / "agents" / "claude" / "skills")}

    config = load_config(config_path)
    run_sync(
        config=config, lock_path=lock_path, store_dir=store_dir, known_agents=agents
    )

    # store_dir should not be created (no cloning)
    assert not store_dir.exists()


def test_install_local_path_with_skill_filter(tmp_path):
    """Filter skills from local_path — only listed ones are installed."""
    local_dir = _make_local_skills_dir(tmp_path, ["alpha", "beta", "gamma"])

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        f"packages:\n  - local_path: {local_dir}\n    skills:\n      - alpha\n      - gamma\n"
    )

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"
    agents = {"claude": str(tmp_path / "agents" / "claude" / "skills")}

    config = load_config(config_path)
    run_sync(
        config=config, lock_path=lock_path, store_dir=store_dir, known_agents=agents
    )

    assert (tmp_path / "agents" / "claude" / "skills" / "alpha").is_symlink()
    assert not (tmp_path / "agents" / "claude" / "skills" / "beta").exists()
    assert (tmp_path / "agents" / "claude" / "skills" / "gamma").is_symlink()


# --- Lock file for local_path ---


def test_lock_local_path_fields(tmp_path):
    """Lock file stores local_path and no commit for local_path packages."""
    local_dir = _make_local_skills_dir(tmp_path, ["my-skill"])

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"packages:\n  - local_path: {local_dir}\n")

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"
    agents = {"claude": str(tmp_path / "agents" / "claude" / "skills")}

    config = load_config(config_path)
    run_sync(
        config=config, lock_path=lock_path, store_dir=store_dir, known_agents=agents
    )

    lock = load_lock(lock_path)
    assert len(lock.skills) == 1
    skill = lock.skills[0]
    assert skill.repo is None
    assert skill.local_path is not None
    assert skill.commit is None


# --- sync --update with local_path is a no-op (no git pull) ---


def test_sync_update_local_path_no_error(tmp_path):
    """run_sync(update=True) on a local_path package links skills without error."""
    local_dir = _make_local_skills_dir(tmp_path, ["my-skill"])

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"packages:\n  - local_path: {local_dir}\n")

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"
    agents = {"claude": str(tmp_path / "agents" / "claude" / "skills")}

    config = load_config(config_path)
    # update=True should not raise even though local_path has no git remote
    run_sync(
        config=config,
        lock_path=lock_path,
        store_dir=store_dir,
        known_agents=agents,
        update=True,
    )

    link = tmp_path / "agents" / "claude" / "skills" / "my-skill"
    assert link.is_symlink()

    lock = load_lock(lock_path)
    assert len(lock.skills) == 1
    assert lock.skills[0].local_path is not None
    assert lock.skills[0].commit is None
