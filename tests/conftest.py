import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FC_PYTEST_TIMEOUT_S", "60")

import pytest

@pytest.fixture
def datadir(tmp_path):
    return tmp_path / "fc"

TASK = str(ROOT / "sample_task")
REPO_TASK = str(ROOT / "repo_tasks" / "textkit")

import tempfile
os.environ.setdefault("FC_DATA_DIR", tempfile.mkdtemp(prefix="fc_web_"))
