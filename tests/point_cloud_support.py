"""三维节点测试用显式配置；数值不用于生产默认。"""

from backend.contracts.workflows.point_cloud import CloudFileOptions, CloudSpatial
from backend.service.application.workflows.point_cloud.policy import PointCloudIoPolicy


def spatial():
    """已确认的测试坐标系。"""
    return CloudSpatial.model_validate(
        {
            "length_unit": "mm",
            "unit_source": "configuration",
            "frame_id": "fixture",
            "axes": {
                "handedness": "right",
                "axis_labels": ["X", "Y", "Z"],
                "definition_source": "configuration",
            },
        }
    )


def options(profile="ply-ascii", dtype="float32", extra=()):
    """声明坐标与显式附加字段，不自动推断。"""
    return CloudFileOptions.model_validate(
        {
            "profile_id": profile,
            "profile_version": 1,
            "spatial": spatial(),
            "field_mapping": [
                {
                    "source_names": ["x", "y", "z"],
                    "target_name": "positions",
                    "semantic": "position",
                    "dtype": dtype,
                    "components": 3,
                    "unit": None,
                },
                *extra,
            ],
        }
    )


def policy(**overrides):
    """小夹具预算，强制跨块验证。"""
    return PointCloudIoPolicy(
        **{
            "max_header_bytes": 4096,
            "max_decoded_bytes": 4096,
            "max_working_bytes": 4096,
            "chunk_rows": 2,
            "chunk_bytes": 256,
            "max_live_array_bytes": 16384,
            **overrides,
        }
    )


def create_resource_service(tmp_path):
    """隔离计量资源服务，供点云资产与格式集成测试共用。"""
    from backend.service.application.workflows.documents.measurement_resources import (
        MeasurementResourceService,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )

    return MeasurementResourceService(
        LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "store")))
    )
