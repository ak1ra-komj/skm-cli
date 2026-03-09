import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_URL_RE = re.compile(r'^(https?://|git@|/)')
SHA_RE = re.compile(r'^[0-9a-f]{7,40}$')


def repo_url_to_dirname(repo_url: str) -> str:
    """Convert a repo URL to a filesystem-safe directory name."""
    parsed = urlparse(repo_url)
    # e.g. "github.com/vercel-labs/agent-skills" -> "github.com_vercel-labs_agent-skills"
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return f"{parsed.hostname}_{path.replace('/', '_')}"


def _validate_repo_url(repo_url: str) -> None:
    if not ALLOWED_URL_RE.match(repo_url):
        raise ValueError(f"Disallowed repo URL: {repo_url!r} (only https:// and git@ are supported)")


def _validate_sha(sha: str) -> None:
    if not SHA_RE.match(sha):
        raise ValueError(f"Invalid commit SHA: {sha!r}")


def clone_or_pull(repo_url: str, dest: Path) -> None:
    """Clone repo if not present, otherwise pull latest."""
    if dest.exists() and (dest / ".git").exists():
        subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=dest,
            capture_output=True,
            check=True,
        )
    else:
        _validate_repo_url(repo_url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", repo_url, str(dest)],
            capture_output=True,
            check=True,
        )


def get_head_commit(repo_path: Path) -> str:
    """Get the HEAD commit SHA of a repo."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def get_log_since(repo_path: Path, since_commit: str, max_count: int = 20) -> str:
    """Get git log from a commit to HEAD."""
    _validate_sha(since_commit)
    result = subprocess.run(
        ["git", "log", f"{since_commit}..HEAD", "--oneline", f"--max-count={max_count}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def fetch(repo_path: Path) -> None:
    """Fetch latest from remote without merging."""
    subprocess.run(
        ["git", "fetch"],
        cwd=repo_path,
        capture_output=True,
        check=True,
    )


def get_remote_head_commit(repo_path: Path) -> str:
    """Get the remote HEAD commit after fetch."""
    result = subprocess.run(
        ["git", "rev-parse", "origin/HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # fallback: try origin/main or origin/master
        for branch in ["origin/main", "origin/master"]:
            result = subprocess.run(
                ["git", "rev-parse", branch],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        raise RuntimeError(f"Cannot determine remote HEAD for {repo_path}")
    return result.stdout.strip()


def get_log_between(repo_path: Path, old_commit: str, new_commit: str, max_count: int = 20) -> str:
    """Get git log between two commits."""
    _validate_sha(old_commit)
    _validate_sha(new_commit)
    result = subprocess.run(
        ["git", "log", f"{old_commit}..{new_commit}", "--oneline", f"--max-count={max_count}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()
