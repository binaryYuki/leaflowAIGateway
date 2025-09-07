import sys
from pathlib import Path
import pytest

# 确保项目根目录可被导入
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402


@pytest.fixture(autouse=True, scope="module")
async def _init_main_client():
    # 手动触发 startup / shutdown 事件来创建与关闭 httpx.AsyncClient
    await main._startup()  # type: ignore[attr-defined]
    yield
    await main._shutdown()  # type: ignore[attr-defined]
