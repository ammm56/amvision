"""只有一个叶进程的文件所有权夹具，无服务或孙进程。"""

from pathlib import Path
import sys
import time

from pypcd4 import PointCloud
from trimesh.exchange import ply


def main():
    """在 decoder 已接管文件时等待父测试终止。"""
    path, kind = Path(sys.argv[1]), sys.argv[2]

    def checkpoint():
        path.with_suffix(".ready").write_text("ready", encoding="ascii")
        while True:
            time.sleep(1)

    with path.open("rb") as stream:
        limits = dict(
            max_decoded_bytes=4096, chunk_rows=2, chunk_bytes=128, cancel=checkpoint
        )
        if kind == "ply":
            header = ply.read_ply_header(stream, max_header_bytes=4096)
            ply.read_ply_data(stream, header, **limits)
        else:
            PointCloud.from_fileobj(
                stream, max_header_bytes=4096, max_working_bytes=4096, **limits
            )


if __name__ == "__main__":
    main()
