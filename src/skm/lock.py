import os
import tempfile
from io import StringIO
from pathlib import Path

from ruamel.yaml import YAML

from skm.types import LockFile, InstalledSkill

_yaml = YAML()
_yaml.default_flow_style = False
_yaml.indent(mapping=2, sequence=4, offset=2)


def load_lock(lock_path: Path) -> LockFile:
    if not lock_path.exists():
        return LockFile()

    data = _yaml.load(lock_path)
    if not data or "skills" not in data:
        return LockFile()

    return LockFile(skills=[InstalledSkill(**s) for s in data["skills"]])


def save_lock(lock: LockFile, lock_path: Path) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"skills": [s.model_dump(mode="json") for s in lock.skills]}
    buf = StringIO()
    _yaml.dump(data, buf)
    text = buf.getvalue()
    fd, tmp = tempfile.mkstemp(dir=lock_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, lock_path)
    except BaseException:
        os.unlink(tmp)
        raise
