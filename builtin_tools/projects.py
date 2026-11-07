"""The ONLY way built-in tools may touch files: inside DreadOS Build projects.

data/build-projects/<name>/ — names are lowercase letters, digits and hyphens (same rule as Build).
No absolute paths, no '..', no symlinks/junctions, never overwrite an existing project.
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / 'data' / 'build-projects'
NAME_RE = re.compile(r'[a-z0-9][a-z0-9-]{0,49}')
SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', '.vite', '__pycache__', '.next', '.cache'}


class ProjectError(ValueError):
    pass


def _linked(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def slug(text):
    """Turn a site title into a valid project name: 'Jazz Guitar Site!' -> 'jazz-guitar-site'."""
    value = re.sub(r'[^a-z0-9]+', '-', str(text).lower()).strip('-')[:50].strip('-')
    return value or 'my-site'


def project_dir(name, must_exist=True):
    """Validated path of a Build project. must_exist=False: it must NOT exist yet (for creation)."""
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise ProjectError('Project names use lowercase letters, numbers and hyphens (e.g. "jazz-portfolio").')
    path = PROJECTS / name
    if path.resolve().parent != PROJECTS.resolve() or _linked(path):
        raise ProjectError('Invalid project path.')
    if must_exist and not path.is_dir():
        known = ', '.join(list_projects()[:20]) or 'none yet'
        raise ProjectError(f'No Build project called "{name}". Existing projects: {known}.')
    if not must_exist and path.exists():
        raise ProjectError(f'A project called "{name}" already exists. Pick another name; existing projects are never overwritten.')
    return path


def list_projects():
    if not PROJECTS.is_dir():
        return []
    return sorted(p.name for p in PROJECTS.iterdir() if p.is_dir() and not _linked(p) and NAME_RE.fullmatch(p.name))


def write_files(name, files):
    """Create a NEW project with {relative_path: text or bytes}. Atomic-ish: refuses any unsafe path first."""
    root = project_dir(name, must_exist=False)
    clean = {}
    for rel, content in files.items():
        parts = Path(rel).parts
        # On Windows '/x' isn't "absolute" (no drive) but still points at the drive root: reject any anchor.
        if (not isinstance(rel, str) or Path(rel).anchor or ':' in rel or rel.startswith(('/', '\\')) or not parts
                or any(p in ('..', '') or (p.startswith('.') and p != '.gitignore') for p in parts)):
            raise ProjectError(f'Unsafe file path in template: {rel}')
        target = (root / rel).resolve()
        if root.resolve() not in target.parents:
            raise ProjectError(f'Unsafe file path in template: {rel}')
        clean[rel] = content
    if len(clean) > 200 or sum(len(c) for c in clean.values()) > 5_000_000:
        raise ProjectError('Template too large.')
    PROJECTS.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    for rel, content in clean.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding='utf-8', newline='\n')
    return root


def iter_files(name, max_files=2000):
    """(relative posix path, absolute Path) for files in a project, skipping build/vendor folders and links."""
    root = project_dir(name)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.') and not _linked(Path(dirpath) / d)]
        for fn in filenames:
            path = Path(dirpath) / fn
            if _linked(path):
                continue
            yield path.relative_to(root).as_posix(), path
            count += 1
            if count >= max_files:
                return


def read_text(name, rel, limit=2_000_000):
    """Read a text file inside a project (read-only), refusing paths that escape it."""
    root = project_dir(name)
    path = (root / rel).resolve()
    if root.resolve() not in path.parents or not path.is_file() or _linked(path):
        raise ProjectError(f'File not found in project: {rel}')
    data = path.read_bytes()[:limit]
    return data.decode('utf-8', errors='replace')
