"""用实际参数和输出模型生成 Catalog，不另建节点注册框架。"""

from pydantic import RootModel

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
from backend.contracts.workflows.cloud_preprocess import (
    DenoiseCloudParameters,
    ResampleCloudParameters,
)
from backend.contracts.workflows.cloud_normals import EstimateNormalsNodeParameters
from backend.contracts.workflows.registration3d import (
    RegistrationParameters,
    RegistrationTransform,
)
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
    ArcNodeParameters,
)
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from backend.contracts.workflows.geometry3d_methods import RigidTransform3d
from backend.contracts.workflows.pose3d_operations import (
    PoseOperationParameters,
    PoseChainTransform,
)
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.relation3d_parameters import RelationNodeParameters
from backend.contracts.workflows.deviation3d_evidence import DeviationNodeParameters
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
    FitLineNodeParameters,
    FitCircleNodeParameters,
)


from backend.contracts.workflows.raster3d import RasterToCloudParameters
from backend.contracts.workflows.raster_trigger import WorkflowTriggerRasterInputV1
from backend.contracts.workflows.profile3d import ProfilesToCloudParameters
from backend.contracts.workflows.profile_trigger import WorkflowTriggerProfileInputV1
from backend.contracts.workflows.height_map_reference import (
    HeightMapReference,
    HeightMapNodeParameters,
)
from backend.contracts.workflows.edge_reference import EdgeDiagnosticReference
from backend.contracts.workflows.edge_extraction import BoundaryExtractionNodeParameters


def build_custom_node_catalog_document():
    """生成正式 Catalog；字段定义直接来自公开参数与结果契约。"""
    payloads = tuple(
        WorkflowPayloadContract(
            payload_type_id=key,
            display_name=title,
            transport_kind="inline-json",
            # Payload 不由参数表单编辑，保留标准本地 $defs，避免来源证据重复展开。
            json_schema=model.model_json_schema(),
        )
        for key, title, model in (
            ("point-cloud-ref.v1", "Point Cloud", CloudReference),
            ("height-map-ref.v1", "Height Map", HeightMapReference),
            ("edge-diagnostic-ref.v1", "Edge Diagnostics", EdgeDiagnosticReference),
            ("calibrated-raster.v1", "Calibrated Raster", WorkflowTriggerRasterInputV1),
            (
                "calibrated-profiles.v1",
                "Calibrated Profiles",
                WorkflowTriggerProfileInputV1,
            ),
            ("measurement-resource-ref.v1", "Measurement Resource", ResourceReference),
            ("roi3d.v1", "3D ROI", RoiPayload),
            ("features3d.v1", "3D Features", Features3d),
            ("pose3d.v1", "3D Pose", Pose3d),
            (
                "transform3d.v1",
                "3D Transform",
                RootModel[
                    RigidTransform3d | RegistrationTransform | PoseChainTransform
                ],
            ),
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
            display_name="Height Map" if name == "height_map" else name.title(),
            payload_type_id=kind,
            required=required,
            multiple=multiple,
        )

    cloud = port("cloud", "point-cloud-ref.v1")
    definitions = []
    for key, title, category, model, inputs, outputs in (
        (
            "measure-deviation",
            "Measure Datum Deviation",
            "metrology3d.measurement",
            DeviationNodeParameters,
            [cloud, port("features", "features3d.v1", multiple=True)],
            [
                cloud,
                port("features", "features3d.v1"),
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "cloud-to-height-map",
            "Cloud to Height Map",
            "metrology3d.data.preprocess",
            HeightMapNodeParameters,
            [cloud, port("pose", "pose3d.v1", False)],
            [
                cloud,
                port("height_map", "height-map-ref.v1"),
                port("summary", "value.v1"),
            ],
        ),
        (
            "profiles-to-cloud",
            "Profiles to Cloud",
            "metrology3d.data.io",
            ProfilesToCloudParameters,
            [
                port("file", "file-ref.v1", False),
                port("profiles", "calibrated-profiles.v1", False),
            ],
            [cloud, port("summary", "value.v1")],
        ),
        (
            "raster-to-cloud",
            "Raster to Cloud",
            "metrology3d.data.io",
            RasterToCloudParameters,
            [
                port("file", "file-ref.v1", False),
                port("raster", "calibrated-raster.v1", False),
            ],
            [cloud, port("summary", "value.v1")],
        ),
        (
            "register-cloud",
            "Register Cloud",
            "metrology3d.geometry",
            RegistrationParameters,
            [
                port("source", "point-cloud-ref.v1"),
                port("reference", "point-cloud-ref.v1"),
                port("source_datum", "pose3d.v1", required=False),
                port("reference_datum", "pose3d.v1", required=False),
            ],
            [port("pose", "pose3d.v1"), port("found", "boolean.v1")],
        ),
        (
            "invert-pose",
            "Invert Pose",
            "metrology3d.geometry",
            PoseOperationParameters,
            [port("pose", "pose3d.v1")],
            [port("pose", "pose3d.v1"), port("found", "boolean.v1")],
        ),
        (
            "compose-pose",
            "Compose Poses",
            "metrology3d.geometry",
            PoseOperationParameters,
            [port("first", "pose3d.v1"), port("second", "pose3d.v1")],
            [port("pose", "pose3d.v1"), port("found", "boolean.v1")],
        ),
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
            "measure-arc",
            "Measure Arc",
            "metrology3d.measurement",
            ArcNodeParameters,
            [port("features", "features3d.v1", multiple=True)],
            [
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "measure-relation",
            "Measure Relation",
            "metrology3d.measurement",
            RelationNodeParameters,
            [cloud, port("features", "features3d.v1", False, True)],
            [
                cloud,
                port("features", "features3d.v1"),
                port("measurements", "numeric-table.v1"),
                port("evidence", "measurement-evidence3d.v1"),
            ],
        ),
        (
            "extract-boundary",
            "Extract Boundary",
            "metrology3d.geometry",
            BoundaryExtractionNodeParameters,
            [
                cloud,
                port("features", "features3d.v1", False, True),
                port("pose", "pose3d.v1", False),
                port("evidence", "measurement-evidence3d.v1", False, True),
                port("height_map", "height-map-ref.v1", False),
            ],
            [
                cloud,
                port("source_cloud", "point-cloud-ref.v1", False),
                port("features", "features3d.v1", False),
                port("diagnostics", "edge-diagnostic-ref.v1", False),
            ],
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
            [port("features", "features3d.v1"), cloud],
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
            [
                cloud,
                port("features", "features3d.v1", False),
                port("height_map", "height-map-ref.v1", False),
                port("diagnostics", "edge-diagnostic-ref.v1", False),
                port("evidence", "measurement-evidence3d.v1", False),
            ],
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
            "denoise-cloud",
            "Denoise Cloud",
            "metrology3d.data.preprocess",
            DenoiseCloudParameters,
            [cloud],
            [cloud, port("removed", "point-cloud-ref.v1"), port("summary", "value.v1")],
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
            "resample-cloud",
            "Resample Cloud",
            "metrology3d.data.preprocess",
            ResampleCloudParameters,
            [cloud],
            [cloud, port("summary", "value.v1")],
        ),
        (
            "estimate-normals",
            "Estimate Normals",
            "metrology3d.data.preprocess",
            EstimateNormalsNodeParameters,
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
                port("height_map", "height-map-ref.v1", False),
                port("diagnostics", "edge-diagnostic-ref.v1", False),
            ],
            [port("body", "response-body.v1")],
        ),
        (
            "save-cloud",
            "Save Cloud",
            "metrology3d.data.io",
            SaveCloudParameters,
            [
                cloud,
                port("features", "features3d.v1", False),
                port("height_map", "height-map-ref.v1", False),
                port("diagnostics", "edge-diagnostic-ref.v1", False),
                port("evidence", "measurement-evidence3d.v1", False),
            ],
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
                version="0.1.34"
                if key
                in {"measure-deviation", "read-cloud", "save-cloud", "cloud-preview"}
                else "0.1.33"
                if key
                in {"measure-relation", "read-cloud", "save-cloud", "cloud-preview"}
                else "0.1.32"
                if key
                in {
                    "measure-arc",
                    "fit-circle",
                    "read-cloud",
                    "save-cloud",
                    "cloud-preview",
                }
                else "0.1.31"
                if key
                in {"cloud-to-height-map", "read-cloud", "save-cloud", "cloud-preview"}
                else "0.1.30"
                if key
                in {"profiles-to-cloud", "read-cloud", "save-cloud", "cloud-preview"}
                else "0.1.29"
                if key == "raster-to-cloud"
                else "0.1.28"
                if key
                in {
                    "register-cloud",
                    "read-cloud",
                    "save-cloud",
                    "invert-pose",
                    "compose-pose",
                    "build-frame",
                    "transform-cloud",
                    "cloud-preview",
                    "height-query",
                    "measure-step",
                    "extract-boundary",
                }
                else "0.1.24"
                if key == "estimate-normals"
                else "0.1.23"
                if key
                in {
                    "resample-cloud",
                    "read-cloud",
                    "save-cloud",
                    "cloud-preview",
                    "normalize-units",
                    "transform-cloud",
                    "export-cloud",
                }
                else "0.1.21"
                if key == "denoise-cloud"
                else "0.1.14"
                if key in {"extract-boundary", "cloud-preview"}
                else "0.1.13"
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
