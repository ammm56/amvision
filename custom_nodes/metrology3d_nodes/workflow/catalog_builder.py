"""用实际参数和输出模型生成 Catalog，不另建节点注册框架。"""

from backend.contracts.nodes.node_pack_manifest import (
    CUSTOM_NODE_CATALOG_FORMAT,
    CustomNodeCatalogDocument,
)
from backend.contracts.workflows.schema_helpers import inline_model_schema
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    NormalizeCloudUnits,
    FilterCloudValid,
)
from backend.contracts.workflows.point_cloud_preview import CloudPreviewOptions
from backend.contracts.workflows.metrology import ResourceReference
from backend.contracts.workflows.workflow_graph import (
    WorkflowPayloadContract,
    validate_node_definition_catalog,
)
from backend.nodes.core_catalog import get_core_workflow_payload_contracts
from custom_nodes.metrology3d_nodes import PACK_VERSION
from backend.contracts.workflows.dimension3d_parameters import (
    ExtentsNodeParameters,
    EdgePairNodeParameters,
    HoleNodeParameters,
)
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.geometry3d_methods import RigidTransform3d
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_parameters import (
    HeightNodeParameters,
    StepNodeParameters,
)
from custom_nodes.metrology3d_nodes.shared.geometry_parameters import (
    CropNodeParameters,
    PlaneNodeParameters,
    FrameNodeParameters,
    TransformNodeParameters,
    RoiPayload,
)
from custom_nodes.metrology3d_nodes.shared.parameters import (
    ReadCloudParameters,
    SaveCloudParameters,
    ExportCloudParameters,
)
from backend.contracts.workflows.boundary3d import (
    ExtractBoundaryNodeParameters,
    FitLineNodeParameters,
    FitCircleNodeParameters,
)


def build_custom_node_catalog_document():
    """生成正式 Catalog；字段定义直接来自公开参数与结果契约。"""
    payloads = tuple(
        WorkflowPayloadContract(
            payload_type_id=key,
            display_name=title,
            transport_kind="inline-json",
            json_schema=inline_model_schema(model),
        )
        for key, title, model in (
            ("point-cloud-ref.v1", "Point Cloud", CloudReference),
            ("measurement-resource-ref.v1", "Measurement Resource", ResourceReference),
            ("roi3d.v1", "3D ROI", RoiPayload),
            ("features3d.v1", "3D Features", Features3d),
            ("pose3d.v1", "3D Pose", Pose3d),
            ("transform3d.v1", "3D Transform", RigidTransform3d),
            (
                "measurement-evidence3d.v1",
                "3D Measurement Evidence",
                MeasurementEvidence3d,
            ),
        )
    )

    def port(name, kind, required=True, multiple=False):
        return dict(
            name=name,
            display_name=name.title(),
            payload_type_id=kind,
            required=required,
            multiple=multiple,
        )

    cloud = port("cloud", "point-cloud-ref.v1")
    definitions = []
    for key, title, category, model, inputs, outputs in (
        (
            "measure-extents",
            "Measure Extents",
            "metrology3d.measurement",
            ExtentsNodeParameters,
            [
                port("cloud", "point-cloud-ref.v1", False),
                port("features", "features3d.v1", False, True),
            ],
            [
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "measure-edge-pair",
            "Measure Edge Pair",
            "metrology3d.measurement",
            EdgePairNodeParameters,
            [port("features", "features3d.v1", multiple=True)],
            [
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "measure-hole",
            "Measure Hole",
            "metrology3d.measurement",
            HoleNodeParameters,
            [port("features", "features3d.v1", multiple=True)],
            [
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "extract-boundary",
            "Extract Boundary",
            "metrology3d.geometry",
            ExtractBoundaryNodeParameters,
            [
                cloud,
                port("features", "features3d.v1", False, True),
                port("pose", "pose3d.v1", False),
                port("evidence", "measurement-evidence3d.v1", False, True),
            ],
            [cloud, port("features", "features3d.v1")],
        ),
        (
            "fit-line",
            "Fit Line",
            "metrology3d.geometry",
            FitLineNodeParameters,
            [port("features", "features3d.v1")],
            [port("features", "features3d.v1")],
        ),
        (
            "fit-circle",
            "Fit Circle",
            "metrology3d.geometry",
            FitCircleNodeParameters,
            [port("features", "features3d.v1")],
            [port("features", "features3d.v1")],
        ),
        (
            "height-query",
            "Height Query",
            "metrology3d.measurement",
            HeightNodeParameters,
            [
                cloud,
                port("features", "features3d.v1", multiple=True),
                port("pose", "pose3d.v1", False),
            ],
            [
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
                port("features", "features3d.v1"),
            ],
        ),
        (
            "measure-step",
            "Measure Step",
            "metrology3d.measurement",
            StepNodeParameters,
            [
                port("features", "features3d.v1", False, True),
                port("reference", "point-cloud-ref.v1", False),
                port("target", "point-cloud-ref.v1", False),
                port("pose", "pose3d.v1", False),
            ],
            [
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "crop-roi",
            "Crop ROI",
            "metrology3d.data.preprocess",
            CropNodeParameters,
            [cloud, port("roi", "roi3d.v1", False)],
            [cloud, port("summary", "value.v1")],
        ),
        (
            "fit-plane",
            "Fit Plane",
            "metrology3d.geometry",
            PlaneNodeParameters,
            [cloud],
            [port("features", "features3d.v1")],
        ),
        (
            "build-frame",
            "Build Frame",
            "metrology3d.geometry",
            FrameNodeParameters,
            [port("features", "features3d.v1", multiple=True)],
            [port("pose", "pose3d.v1"), port("found", "boolean.v1")],
        ),
        (
            "transform-cloud",
            "Transform Cloud",
            "metrology3d.data.preprocess",
            TransformNodeParameters,
            [cloud, port("pose", "pose3d.v1")],
            [cloud],
        ),
        (
            "read-cloud",
            "Read Cloud",
            "metrology3d.data.io",
            ReadCloudParameters,
            [port("file", "file-ref.v1", False)],
            [cloud, port("features", "features3d.v1", False)],
        ),
        (
            "normalize-units",
            "Normalize Units",
            "metrology3d.data.preprocess",
            NormalizeCloudUnits,
            [cloud],
            [cloud],
        ),
        (
            "filter-valid",
            "Filter Valid",
            "metrology3d.data.preprocess",
            FilterCloudValid,
            [cloud],
            [cloud, port("summary", "value.v1")],
        ),
        (
            "cloud-preview",
            "Cloud Preview",
            "metrology3d.ui.preview",
            CloudPreviewOptions,
            [
                cloud,
                port("features", "features3d.v1", False, True),
                port("pose", "pose3d.v1", False),
                port("evidence", "measurement-evidence3d.v1", False, True),
            ],
            [port("body", "response-body.v1")],
        ),
        (
            "save-cloud",
            "Save Cloud",
            "metrology3d.data.io",
            SaveCloudParameters,
            [cloud, port("features", "features3d.v1", False)],
            [port("resource", "measurement-resource-ref.v1")],
        ),
        (
            "export-cloud",
            "Export Cloud",
            "metrology3d.data.io",
            ExportCloudParameters,
            [port("cloud", "point-cloud-ref.v1", False)],
            [port("file", "file-ref.v1"), port("summary", "value.v1")],
        ),
    ):
        definitions.append(
            dict(
                node_type_id="custom.metrology3d." + key,
                version="0.1.12"
                if key
                in {
                    "extract-boundary",
                    "fit-line",
                    "fit-circle",
                    "measure-extents",
                    "measure-edge-pair",
                    "measure-hole",
                    "read-cloud",
                    "save-cloud",
                    "export-cloud",
                    "cloud-preview",
                }
                else "0.1.11"
                if key in {"height-query", "measure-step", "cloud-preview"}
                else "0.1.10"
                if key
                in {
                    "crop-roi",
                    "extract-boundary",
                    "cloud-preview",
                    "read-cloud",
                    "save-cloud",
                    "export-cloud",
                }
                else "0.1.9"
                if key
                in {
                    "height-query",
                    "measure-step",
                    "cloud-preview",
                    "measure-extents",
                    "measure-edge-pair",
                    "measure-hole",
                }
                else "0.1.8",
                display_name=title,
                category=category,
                description=title,
                implementation_kind="custom-node",
                runtime_kind="python-callable",
                node_pack_id="metrology3d.nodes",
                node_pack_version=PACK_VERSION,
                input_ports=inputs,
                output_ports=outputs,
                parameter_schema=inline_model_schema(model),
                capability_tags=["vision.metrology3d"]
                + (["ui.preview"] if key == "cloud-preview" else []),
            )
        )
    document = CustomNodeCatalogDocument(
        format_id=CUSTOM_NODE_CATALOG_FORMAT,
        payload_contracts=payloads,
        node_definitions=definitions,
    )
    validate_node_definition_catalog(
        node_definitions=document.node_definitions,
        payload_contracts=(*get_core_workflow_payload_contracts(), *payloads),
    )
    return document
