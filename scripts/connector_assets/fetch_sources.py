"""下载明确列出的连接器公开参考资料并记录 SHA256，不访问业务数据或修改数据库。"""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


def main() -> None:
    """只新增缺失文件；已存在文件核对固定摘要，不静默覆盖。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/development/connector-inspection/sources"))
    args = parser.parse_args()
    source_list = json.loads(Path(__file__).with_name("sources.json").read_text(encoding="utf-8"))
    root = args.output.resolve()
    for item in source_list["files"]:
        destination = (root / item["path"]).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("Source path outside output")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            content = destination.read_bytes()
        else:
            request = urllib.request.Request(item["url"], headers={"User-Agent": "AMVision-Development-Assets/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                content = response.read(10 * 1024 * 1024 + 1)
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("Unexpected oversized source")
        digest = hashlib.sha256(content).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"Source changed; review required: {item['path']}")
        if not destination.exists():
            with destination.open("xb") as stream:
                stream.write(content)
        print(item["path"], len(content), digest)
    (root / "sources.json").write_text(json.dumps(source_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
