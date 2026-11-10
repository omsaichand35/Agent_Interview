import os
import shutil
import tempfile
from pathlib import Path

# Keep the suite database outside pytest's basetemp: tmp_path may clean that
# directory lazily after the database engine has already opened its file.
_TEST_DATABASE_DIR = Path(__file__).resolve().parents[1] / ".test-runtime" / f"run-{os.getpid()}"
_TEST_DATABASE_DIR.mkdir(parents=True, exist_ok=True)
_TEST_DATABASE_FILE = _TEST_DATABASE_DIR / "test-suite.db"
_TEST_OUTPUT_DIR = _TEST_DATABASE_DIR / "outputs"
_TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DATABASE_FILE.as_posix()}"
os.environ["TEST_OUTPUT_ROOT"] = str(_TEST_OUTPUT_DIR)

# Ensure .venv/Scripts and latest Windows environment PATH are in os.environ["PATH"]
if not shutil.which("ffmpeg"):
    venv_scripts = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", ".venv", "Scripts")
    )
    if os.path.exists(os.path.join(venv_scripts, "ffmpeg.exe")):
        os.environ["PATH"] = venv_scripts + os.pathsep + os.environ.get("PATH", "")
    elif os.name == "nt":
        import winreg

        paths = []
        for hive, subkey in [
            (winreg.HKEY_CURRENT_USER, r"Environment"),
            (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        ]:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    val, _ = winreg.QueryValueEx(key, "Path")
                    paths.extend(val.split(";"))
            except OSError:
                pass

        for p in paths:
            if p and os.path.exists(p) and p not in os.environ["PATH"]:
                os.environ["PATH"] = p + os.pathsep + os.environ["PATH"]

import pytest


@pytest.fixture(scope="session", autouse=True)
def initialize_isolated_test_database():
    """Create the isolated schema before fixtures seed rows outside HTTP lifespans."""
    import app.database.models  # noqa: F401
    from app.database.base import Base
    from app.database.connection import engine

    Base.metadata.create_all(bind=engine)
    yield
    engine.dispose()
    shutil.rmtree(_TEST_DATABASE_DIR, ignore_errors=True)
    shutil.rmtree(_TEST_OUTPUT_DIR, ignore_errors=True)


@pytest.fixture(autouse=True)
def reset_rate_limiter(initialize_isolated_test_database):
    try:
        from app.security.rate_limiter import rate_limiter_instance
        rate_limiter_instance.reset()
    except Exception:
        pass
    yield
    try:
        from app.security.rate_limiter import rate_limiter_instance
        rate_limiter_instance.reset()
    except Exception:
        pass

