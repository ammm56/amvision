"""三维测量完整页面验收入口，复用正式发布测试系统和真实 API。"""

import argparse
from pathlib import Path

import uvicorn

from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_boundary_published import boundary_documents
from tests.integration.metrology3d.test_file_read import ply


def main():
    """隔离目录必须不存在；Ctrl+C 后关闭本轮服务与 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--point-cloud-policy", type=Path)
    parser.add_argument(
        "--recipe",
        choices=(
            "empty",
            "boundary-circle",
            "extents",
            "edge-pair",
            "hole",
            "dimensions",
            "datum-extension",
            "roi-union",
        ),
        default="boundary-circle",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or args.port in (5600, 5601):
        parser.error("验收必须使用独立的非业务端口")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    policy = None
    if args.point_cloud_policy:
        from backend.service.application.workflows.point_cloud.execution_policy import (
            PointCloudExecutionPolicy,
        )

        policy = PointCloudExecutionPolicy.model_validate_json(
            args.point_cloud_policy.read_text("utf-8")
        )
    with published_system(root, point_cloud_policy=policy) as system:
        kinds = (
            ("extents", "edge-pair", "hole")
            if args.recipe == "dimensions"
            else (args.recipe,)
        )
        for kind in () if args.recipe == "empty" else kinds:
            if kind == "datum-extension":
                from tests.integration.metrology3d.test_reference_extension_published import (
                    extension_documents,
                )

                version = system.publish(documents=extension_documents(file=True))
                print(
                    f"Published {version}; provide the complete original sample through the UI",
                    flush=True,
                )
                continue
            if kind == "roi-union":
                from tests.integration.metrology3d.test_roi_union_published import (
                    union_documents,
                )

                documents, _, points = union_documents(file=True)
            elif kind == "boundary-circle":
                documents, _, points = boundary_documents("circle", file=True)
            else:
                from tests.integration.metrology3d.test_dimension_nodes import (
                    dimension_documents,
                )

                documents, _, points = dimension_documents(kind, file=True)
            if args.recipe == "dimensions":
                template, app = documents
                template = template.model_copy(
                    update={"template_id": "dimension-" + kind, "display_name": kind}
                )
                app = app.model_copy(
                    update={
                        "application_id": "dimension-" + kind,
                        "display_name": kind,
                        "template_ref": app.template_ref.model_copy(
                            update={"template_id": template.template_id}
                        ),
                    }
                )
                documents = template, app
            path = root / (
                f"{kind}.ply" if args.recipe == "dimensions" else "circle.ply"
            )
            body = "".join(
                " ".join(format(float(v), ".9g") for v in row) + "\n" for row in points
            ).encode()
            path.write_bytes(ply(body, count=len(points)))
            version = system.publish(documents=documents)
            print(f"Published {version}; input={path}", flush=True)
        # 正式 lifespan 已由 published_system 进入一次，HTTP 服务器共享同一实例。
        uvicorn.run(system.client.app, host="127.0.0.1", port=args.port, lifespan="off")


if __name__ == "__main__":
    main()
