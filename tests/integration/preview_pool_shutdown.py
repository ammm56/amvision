"""隔离复现实际 Uvicorn 信号退出与真实 Preview 池的资源收尾。"""

from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys

from fastapi import FastAPI
import uvicorn

from tests.test_workflow_preview_pool_cleanup import _pool, semaphore_paths


def main():
    """仅为测试探针；不替代产品服务、启动器或生命周期实现。"""
    root = Path(sys.argv[1])
    pool = _pool()
    names = semaphore_paths(pool)

    @asynccontextmanager
    async def lifespan(_app):
        (root / "ready.json").write_text(json.dumps([str(path) for path in names]))
        try:
            yield
        finally:
            pool.close()
            (root / "closed.json").write_text(json.dumps({
                "remaining": [str(path) for path in names if path.exists()],
                "slot_count": len(pool._slots),
            }))

    uvicorn.run(FastAPI(lifespan=lifespan), host="127.0.0.1", port=0, log_level="info")


if __name__ == "__main__":
    main()
