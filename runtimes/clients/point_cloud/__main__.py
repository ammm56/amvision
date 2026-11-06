"""使用服务同一运行时和显式配置调用已启用的点云 Trigger。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.point_cloud import CloudBufferDescriptor
from backend.contracts.workflows.raster3d import RasterBufferDescriptor
from backend.contracts.workflows.profile3d import ProfileBufferDescriptor
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
    parser.add_argument(
        "--input-kind", choices=("cloud", "raster", "profiles"), default="cloud"
    )
    parser.add_argument("--payload-key")
    args = parser.parse_args()
    settings = get_backend_service_settings()
    client = PointCloudClient(
        buffers_root=settings.local_memory.root_dir,
        broker_settings=settings.local_buffer_broker,
    )
    model, invoke = {
        "cloud": (CloudBufferDescriptor, client.invoke),
        "raster": (RasterBufferDescriptor, client.invoke_raster),
        "profiles": (ProfileBufferDescriptor, client.invoke_profiles),
    }[args.input_kind]
    descriptor = model.model_validate_json(args.descriptor.read_text("utf-8"))
    result = invoke(
        source_id=args.source,
        generation=args.generation,
        **{args.input_kind: descriptor},
        payload_key=args.payload_key or args.input_kind,
        content=args.array,
        timeout_ms=args.timeout_ms,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
