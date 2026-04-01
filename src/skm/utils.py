from pathlib import Path


def compact_path(p: str) -> str:
    """Replace the user's home directory prefix with ~."""
    home = str(Path.home())
    if p.startswith(home):
        return "~" + p[len(home) :]
    return p
