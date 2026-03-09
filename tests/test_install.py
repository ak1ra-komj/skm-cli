import subprocess
from pathlib import Path
from skm.commands.install import run_install
from skm.types import KNOWN_AGENTS


def _make_skill_repo(tmp_path, name, skills_subdir=True):
    """Create a minimal local git repo with a skill."""
    repo = tmp_path / f"repo-{name}"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)

    if skills_subdir:
        skill_dir = repo / "skills" / name
    else:
        skill_dir = repo

    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\ndescription: test\n---\nContent\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True)
    return repo


def test_install_basic(tmp_path):
    """Install a skill from a local repo, verify symlinks and lock file."""
    repo = _make_skill_repo(tmp_path, "test-skill")

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"- repo: {repo}\n  skills:\n    - test-skill\n")

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"

    # Use tmp dirs as agent targets
    agents = {
        "claude": str(tmp_path / "agents" / "claude" / "skills"),
        "codex": str(tmp_path / "agents" / "codex" / "skills"),
    }

    run_install(
        config_path=config_path,
        lock_path=lock_path,
        store_dir=store_dir,
        known_agents=agents,
    )

    # Check symlinks exist
    assert (tmp_path / "agents" / "claude" / "skills" / "test-skill").is_symlink()
    assert (tmp_path / "agents" / "codex" / "skills" / "test-skill").is_symlink()

    # Check lock file
    assert lock_path.exists()


def test_install_singleton_skill(tmp_path):
    """Install a singleton skill (SKILL.md at repo root)."""
    repo = _make_skill_repo(tmp_path, "singleton", skills_subdir=False)

    config_path = tmp_path / "config" / "skills.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(f"- repo: {repo}\n")

    lock_path = tmp_path / "config" / "skills-lock.yaml"
    store_dir = tmp_path / "store"
    agents = {"claude": str(tmp_path / "agents" / "claude" / "skills")}

    run_install(
        config_path=config_path,
        lock_path=lock_path,
        store_dir=store_dir,
        known_agents=agents,
    )

    assert (tmp_path / "agents" / "claude" / "skills" / "singleton").is_symlink()
