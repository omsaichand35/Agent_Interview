from pathlib import Path
from typing import Union


def get_project_root() -> Path:
    """
    Locates the repository root (e.g. 'Interview') regardless of whether
    python was executed from 'Interview', 'Interview/backend', or any subdirectory.
    """
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        # If parent contains both backend and models, or backend/app
        if (parent / "backend" / "app").exists():
            return parent
        if (parent / "app").exists() and (parent.name == "backend"):
            return parent.parent
    return current.parents[2]


def get_backend_dir() -> Path:
    """
    Returns the absolute path to the backend directory.
    """
    root = get_project_root()
    if (root / "backend").exists():
        return root / "backend"
    return root


def resolve_path(target_path: Union[str, Path, None]) -> Path:
    """
    Resolves relative model, data, or configuration paths to an absolute path,
    checking project root, backend directory, and current working directory.
    Ensures identical file resolution whether running `python backend/app/main.py`
    or `cd backend && python app/main.py`.
    """
    if not target_path:
        return get_project_root()

    p = Path(target_path)
    if p.is_absolute() and p.exists():
        return p

    root = get_project_root()
    backend = get_backend_dir()
    cwd = Path.cwd().resolve()

    # Clean leading ../ or ./
    cleaned_str = str(p).replace("\\", "/")
    while cleaned_str.startswith("../") or cleaned_str.startswith("./"):
        if cleaned_str.startswith("../"):
            cleaned_str = cleaned_str[3:]
        elif cleaned_str.startswith("./"):
            cleaned_str = cleaned_str[2:]
    cleaned_path = Path(cleaned_str)

    # 1. Check direct relative against project root
    if (root / p).exists():
        return (root / p).resolve()

    # 2. Check cleaned relative against project root
    if (root / cleaned_path).exists():
        return (root / cleaned_path).resolve()

    # 3. Check direct relative against backend dir
    if (backend / p).exists():
        return (backend / p).resolve()

    # 4. Check cleaned relative against backend dir
    if (backend / cleaned_path).exists():
        return (backend / cleaned_path).resolve()

    # 5. Check against current working directory
    if (cwd / p).exists():
        return (cwd / p).resolve()

    # Fallback to root / cleaned_path or root / p
    return (root / cleaned_path).resolve()
