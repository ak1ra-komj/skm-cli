from skm.linker import resolve_target_agents, link_skill, unlink_skill


def test_resolve_target_agents_all(tmp_path):
    """No includes/excludes → all agents."""
    agents = {'claude': str(tmp_path / 'claude'), 'codex': str(tmp_path / 'codex')}
    result = resolve_target_agents(None, agents)
    assert set(result.keys()) == {'claude', 'codex'}


def test_resolve_target_agents_excludes(tmp_path):
    agents = {
        'claude': str(tmp_path / 'claude'),
        'codex': str(tmp_path / 'codex'),
        'openclaw': str(tmp_path / 'openclaw'),
    }
    from skm.types import AgentsConfig

    cfg = AgentsConfig(excludes=['openclaw'])
    result = resolve_target_agents(cfg, agents)
    assert 'openclaw' not in result
    assert 'claude' in result


def test_resolve_target_agents_includes(tmp_path):
    agents = {
        'claude': str(tmp_path / 'claude'),
        'codex': str(tmp_path / 'codex'),
        'openclaw': str(tmp_path / 'openclaw'),
    }
    from skm.types import AgentsConfig

    cfg = AgentsConfig(includes=['claude'])
    result = resolve_target_agents(cfg, agents)
    assert set(result.keys()) == {'claude'}


def test_link_skill(tmp_path):
    """Link a skill dir to an agent skill dir."""
    skill_src = tmp_path / 'store' / 'my-skill'
    skill_src.mkdir(parents=True)
    (skill_src / 'SKILL.md').write_text('---\nname: my-skill\n---\n')

    agent_dir = tmp_path / 'agent' / 'skills'
    agent_dir.mkdir(parents=True)

    linked = link_skill(skill_src, 'my-skill', str(agent_dir))
    assert linked.is_symlink()
    assert linked.resolve() == skill_src.resolve()
    assert linked.name == 'my-skill'


def test_link_skill_already_linked(tmp_path):
    """Re-linking same source is idempotent."""
    skill_src = tmp_path / 'store' / 'my-skill'
    skill_src.mkdir(parents=True)
    agent_dir = tmp_path / 'agent' / 'skills'
    agent_dir.mkdir(parents=True)

    link_skill(skill_src, 'my-skill', str(agent_dir))
    linked = link_skill(skill_src, 'my-skill', str(agent_dir))
    assert linked.is_symlink()


def test_link_skill_existing_dir_raises(tmp_path):
    """Non-symlink dir at target raises FileExistsError."""
    skill_src = tmp_path / 'store' / 'my-skill'
    skill_src.mkdir(parents=True)
    agent_dir = tmp_path / 'agent' / 'skills'
    agent_dir.mkdir(parents=True)
    # Create a real directory at the target
    (agent_dir / 'my-skill').mkdir()
    (agent_dir / 'my-skill' / 'some-file.md').write_text('hello')

    import pytest

    with pytest.raises(FileExistsError):
        link_skill(skill_src, 'my-skill', str(agent_dir))


def test_link_skill_force_overrides_dir(tmp_path):
    """force=True removes existing dir and creates symlink."""
    skill_src = tmp_path / 'store' / 'my-skill'
    skill_src.mkdir(parents=True)
    agent_dir = tmp_path / 'agent' / 'skills'
    agent_dir.mkdir(parents=True)
    # Create a real directory at the target
    (agent_dir / 'my-skill').mkdir()
    (agent_dir / 'my-skill' / 'some-file.md').write_text('hello')

    linked = link_skill(skill_src, 'my-skill', str(agent_dir), force=True)
    assert linked.is_symlink()
    assert linked.resolve() == skill_src.resolve()


def test_link_skill_force_overrides_file(tmp_path):
    """force=True removes existing file and creates symlink."""
    skill_src = tmp_path / 'store' / 'my-skill'
    skill_src.mkdir(parents=True)
    agent_dir = tmp_path / 'agent' / 'skills'
    agent_dir.mkdir(parents=True)
    # Create a regular file at the target
    (agent_dir / 'my-skill').write_text('not a symlink')

    linked = link_skill(skill_src, 'my-skill', str(agent_dir), force=True)
    assert linked.is_symlink()
    assert linked.resolve() == skill_src.resolve()


def test_unlink_skill(tmp_path):
    """Unlink removes the symlink."""
    skill_src = tmp_path / 'store' / 'my-skill'
    skill_src.mkdir(parents=True)
    agent_dir = tmp_path / 'agent' / 'skills'
    agent_dir.mkdir(parents=True)

    link_skill(skill_src, 'my-skill', str(agent_dir))
    target = agent_dir / 'my-skill'
    assert target.is_symlink()

    unlink_skill('my-skill', str(agent_dir))
    assert not target.exists()
