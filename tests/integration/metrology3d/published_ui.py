"""三维测量完整页面验收入口，复用正式发布测试系统和真实 API。"""

import argparse
from pathlib import Path

from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_boundary_published import boundary_documents
from tests.integration.metrology3d.test_file_read import ply


def main():
    """隔离目录必须不存在；Ctrl+C 后关闭本轮服务与 Runtime。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--point-cloud-policy", type=Path)
    parser.add_argument("--inspection", default="A_top_L")
    parser.add_argument("--datum-preview", action="store_true")
    parser.add_argument("--capture-debug", action="store_true")
    parser.add_argument(
        "--recipe",
        choices=(
            "empty",
            "boundary-circle",
            "extents",
            "edge-pair",
            "hole",
            "dimensions",
            "methods",
            "datum-extension",
            "roi-union",
            "visible-envelope",
            "workpiece-delivery",
            "calibrated-raster",
            "calibrated-raster-resaved",
            "calibrated-profiles",
            "height-map",
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
    elif args.recipe in {"visible-envelope", "workpiece-delivery", "height-map"}:
        from tests.integration.metrology3d.representative_workflow import (
            representative_policy,
        )

        policy = representative_policy()
    with published_system(root, point_cloud_policy=policy) as system:
        kinds = (
            (
                "three-planes",
                "statistic-mean",
                "statistic-median",
                "statistic-quantile",
                "denoise-statistical",
                "denoise-radius",
            )
            if args.recipe == "methods"
            else ("extents", "edge-pair", "hole")
            if args.recipe == "dimensions"
            else (args.recipe,)
        )
        for kind in () if args.recipe == "empty" else kinds:
            if kind == "height-map":
                from tests.test_metrology3d_height_map import parameters
                from tests.integration.metrology3d.test_height_map_published import (
                    documents,
                )

                settings = parameters().model_dump(mode="json")
                settings.update(width=256, height=512)
                settings["grid"].update(
                    origin=(-64, -192, 0), column_step=0.5, row_step=0.5
                )
                version = system.publish(
                    point_limit=500000, documents=documents(settings, file=True)
                )
                print(
                    f"Published {version}; provide complete original sample through UI",
                    flush=True,
                )
                continue
            if kind == "calibrated-profiles":
                import numpy as np
                from tests.test_metrology3d_profile_conversion import specification
                from tests.integration.metrology3d.test_profiles_published import (
                    profile_documents,
                )

                row, col = np.mgrid[:192, :256]
                heights = (0.015 * col + 0.025 * row + 2 * np.sin(col / 32)).astype(
                    "float32"
                )
                # 显式缺一采集行、留一空行，不把合成标定数据称为真实扫描。
                lengths = np.full(192, 256, dtype=np.uint64)
                lengths[80] = 0
                keep = row.ravel() != 80
                rows = np.arange(192, dtype=np.uint64)
                rows[100:] += 1
                offsets = np.concatenate(
                    (np.zeros(1, dtype=np.uint64), np.cumsum(lengths))
                )
                spec = specification(
                    point_count=int(offsets[-1]),
                    profile_count=192,
                    dtype="float32",
                    origin=[0, 0, 0],
                    x_direction=[1, 0, 0],
                    scan_direction=[0, 1, 0],
                    height_direction=[0, 0, 1],
                    displacement=dict(kind="fixed-step", origin_line_id=0, step=0.25),
                )
                path = root / "calibrated-profiles.npz"
                np.savez(
                    path,
                    profiles=np.column_stack(
                        (col.ravel()[keep] * np.float32(0.25), heights.ravel()[keep])
                    ).astype("float32"),
                    line_offsets=offsets,
                    line_ids=rows,
                )
                version = system.publish(
                    point_limit=500, documents=profile_documents(spec)
                )
                print(
                    f"Published {version}; analytic calibrated profiles input={path}",
                    flush=True,
                )
                continue
            if kind in {"calibrated-raster", "calibrated-raster-resaved"}:
                import numpy as np
                from tests.test_metrology3d_raster_conversion import specification
                from tests.integration.metrology3d.test_raster_published import (
                    raster_documents,
                )

                row, col = np.mgrid[:192, :256]
                heights = (0.015 * col + 0.025 * row + 2 * np.sin(col / 32)).astype(
                    "float32"
                )
                spec = specification(
                    width=256,
                    height=192,
                    projection=dict(
                        kind="orthographic-height",
                        origin=[0, 0, 0],
                        column_direction=[1, 0, 0],
                        row_direction=[0, 1, 0],
                        height_direction=[0, 0, 1],
                        column_step=0.25,
                        row_step=0.25,
                    ),
                )
                path = root / "calibrated-height.npy"
                np.save(path, heights, allow_pickle=False)
                if kind == "calibrated-raster-resaved":
                    from tests.integration.metrology3d.test_raster_published import (
                        publish_saved_raster_roundtrip,
                    )
                    from tests.test_metrology3d_raster_io import encode

                    body = publish_saved_raster_roundtrip(
                        system, spec, encode(heights, "npy")
                    )
                    print(
                        f"Published saved raster; pixels={body['source_point_count']}; calibration={body['raster_source']['calibration_id']}",
                        flush=True,
                    )
                    continue
                version = system.publish(
                    point_limit=1000, documents=raster_documents(spec=spec)
                )
                print(
                    f"Published {version}; analytic calibrated grid input={path}",
                    flush=True,
                )
                continue
            if args.recipe == "methods":
                from tests.integration.metrology3d.method_documents import (
                    method_documents,
                )

                documents, points = method_documents(kind)
                body = "".join(
                    " ".join(format(float(v), ".9g") for v in row) + "\n"
                    for row in points
                ).encode()
                path = root / f"{kind}.ply"
                path.write_bytes(ply(body, count=len(points)))
                version = system.publish(documents=documents)
                print(f"Published {version}; input={path}", flush=True)
                continue
            if kind == "workpiece-delivery":
                from scripts.metrology_workpiece import build_documents

                version = system.publish(
                    point_limit=500_000, documents=build_documents()
                )
                print(
                    f"Published {version}; complete public workpiece recipe", flush=True
                )
                continue
            if kind == "visible-envelope":
                from tests.integration.metrology3d.workpiece_workflow import (
                    workpiece_documents,
                )

                documents = workpiece_documents(
                    file=True,
                    visible=True,
                    inspection=args.inspection,
                    debug=("A_top_L", "S1", "S2") if args.capture_debug else (),
                )
                if args.datum_preview:
                    from backend.contracts.workflows.workflow_graph import (
                        WorkflowGraphTemplate,
                    )

                    graph = documents[0].model_dump(mode="json")
                    for source, port in (("D", "features"), ("frame", "pose")):
                        graph["edges"].append(
                            dict(
                                edge_id="ui-datum-" + source,
                                source_node_id=source,
                                source_port=port,
                                target_node_id="preview",
                                target_port=port,
                            )
                        )
                    documents = (
                        WorkflowGraphTemplate.model_validate(graph),
                        documents[1],
                    )
                version = system.publish(point_limit=500000, documents=documents)
                print(
                    f"Published {version}; provide the complete original sample through the UI",
                    flush=True,
                )
                continue
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
        from tests.integration.metrology3d.package_acceptance import serve

        serve(system, root, args.port)


if __name__ == "__main__":
    main()
