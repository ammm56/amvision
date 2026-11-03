"""使用服务同一运行时和显式配置调用已启用的点云 Trigger。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.service.settings import get_backend_service_settings
from runtimes.clients.point_cloud import PointCloudClient


def main() -> None:
    """descriptor 与数组分离；不读取 PLY、不替服务启动 Runtime 或猜 generation。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--array", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--generation", type=int, required=True)
    parser.add_argument("--timeout-ms", type=int, required=True)
    args = parser.parse_args()
    settings = get_backend_service_settings()
    result = PointCloudClient(
        buffers_root=settings.local_memory.root_dir,
        broker_settings=settings.local_buffer_broker,
    ).invoke(
        source_id=args.source, generation=args.generation,
        cloud=CloudBufferDescriptor.model_validate_json(args.descriptor.read_text("utf-8")),
        content=args.array, timeout_ms=args.timeout_ms,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
