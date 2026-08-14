"""tests 公共夹具：每次测试会话自动生成样本与 replay（幂等）。"""

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_sessionstart(session):
    for script in ("generate.py", "make_replay.py"):
        subprocess.run([sys.executable, str(FIXTURES / script)], check=True)
