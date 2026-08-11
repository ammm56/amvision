"""YOLO 数据集配置和类别信息解析。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import yaml

from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.pose_topology import normalize_pose_flip_indices


class YoloManifestMixin:
    """读取 YOLO data.yaml、导出 manifest 和类别映射。"""

    def _load_yolo_dataset_descriptor(
        self,
        dataset_root: Path,
    ) -> tuple[str | None, dict[str, object], Path, str | None, dict[str, object] | None]:
        """读取 YOLO 数据集配置文件和可选导出 manifest。"""

        config_file: str | None = None
        config_payload: dict[str, object] = {}
        dataset_base_root = dataset_root
        for yaml_path in self._collect_yolo_yaml_paths(dataset_root):
            try:
                raw_payload = yaml.safe_load(
                    self._read_import_text(yaml_path, file_kind="metadata")
                )
            except yaml.YAMLError as error:
                raise InvalidRequestError(
                    "YOLO data.yaml 解析失败",
                    details={
                        "config_file": self._relative_path(dataset_root, yaml_path),
                        "reason": str(error),
                    },
                ) from error
            if not isinstance(raw_payload, dict):
                continue
            normalized_payload = dict(raw_payload)
            if not self._looks_like_yolo_config_payload(normalized_payload):
                continue
            config_file = self._relative_path(dataset_root, yaml_path)
            config_payload = normalized_payload
            configured_root = normalized_payload.get("path")
            if isinstance(configured_root, str) and configured_root.strip():
                resolved_configured_root = self._resolve_yolo_path(
                    yaml_path.parent,
                    configured_root,
                )
                dataset_base_root = self._resolve_yolo_dataset_base_root(
                    dataset_root=dataset_root,
                    yaml_path=yaml_path,
                    configured_root=configured_root,
                    resolved_configured_root=resolved_configured_root,
                )
            else:
                dataset_base_root = yaml_path.parent
            break

        export_manifest_file: str | None = None
        export_manifest_payload: dict[str, object] | None = None
        manifest_path = dataset_root / "manifest.json"
        if manifest_path.is_file():
            try:
                raw_manifest_payload = json.loads(
                    self._read_import_text(manifest_path, file_kind="metadata")
                )
            except json.JSONDecodeError as error:
                raise InvalidRequestError(
                    "YOLO manifest.json 解析失败",
                    details={"line": error.lineno, "column": error.colno},
                ) from error
            if isinstance(raw_manifest_payload, dict):
                format_id = str(raw_manifest_payload.get("format_id") or "").strip()
                if format_id.startswith("yolo-"):
                    export_manifest_file = self._relative_path(dataset_root, manifest_path)
                    export_manifest_payload = raw_manifest_payload

        return (
            config_file,
            config_payload,
            dataset_base_root,
            export_manifest_file,
            export_manifest_payload,
        )

    def _resolve_yolo_dataset_base_root(
        self,
        *,
        dataset_root: Path,
        yaml_path: Path,
        configured_root: str,
        resolved_configured_root: Path,
    ) -> Path:
        """解析 YOLO data.yaml 中的 dataset root。"""

        archive_root = dataset_root.resolve()
        if not resolved_configured_root.resolve(strict=False).is_relative_to(archive_root):
            raise InvalidRequestError(
                "YOLO data.yaml 的 path 不得指向 zip 外部",
                details={"path": configured_root},
            )
        if resolved_configured_root.exists():
            return resolved_configured_root

        normalized_root_name = Path(configured_root.strip().replace("\\", "/")).name
        yaml_parent = yaml_path.parent
        # 常见 zip 会把数据集目录本身打包进去，同时 data.yaml 仍保留
        # `path: <dataset-name>`。解压后 YAML 所在目录已是数据集根目录，
        # 此时不能再拼一层同名目录。
        if normalized_root_name and yaml_parent.name == normalized_root_name:
            return yaml_parent
        if (yaml_parent / "images").is_dir() or (yaml_parent / "labels").is_dir():
            return yaml_parent
        return resolved_configured_root

    def _collect_yolo_yaml_paths(
        self,
        dataset_root: Path,
    ) -> tuple[Path, ...]:
        """收集并排序 YOLO 数据集常见配置文件。"""

        preferred_names = ("data.yaml", "data.yml", "dataset.yaml", "dataset.yml")
        preferred_paths = [
            dataset_root / file_name
            for file_name in preferred_names
            if (dataset_root / file_name).is_file()
        ]
        other_paths = sorted(
            candidate
            for pattern in ("*.yaml", "*.yml")
            for candidate in dataset_root.glob(pattern)
            if candidate.is_file() and candidate not in preferred_paths
        )
        return tuple(preferred_paths + other_paths)

    def _looks_like_yolo_config_payload(
        self,
        payload: dict[str, object],
    ) -> bool:
        """判断某个 YAML 载荷是否像 YOLO 数据集配置。"""

        has_split_spec = any(
            isinstance(payload.get(key), (str, list))
            for key in ("train", "val", "test")
        )
        has_names = isinstance(payload.get("names"), (list, dict))
        return has_split_spec and has_names

    def _resolve_yolo_path(
        self,
        base_root: Path,
        raw_path: str,
    ) -> Path:
        """解析 YOLO 配置中的路径。"""

        normalized_path = Path(raw_path.strip().replace("\\", "/")).expanduser()
        if normalized_path.is_absolute():
            raise InvalidRequestError(
                "YOLO data.yaml 不允许使用绝对路径",
                details={"path": raw_path},
            )
        return (base_root / normalized_path).resolve(strict=False)

    def _resolve_yolo_category_name_map(
        self,
        *,
        config_payload: dict[str, object],
        export_manifest_payload: dict[str, object] | None,
        requested_class_map: dict[str, str],
        observed_class_ids: set[int],
    ) -> dict[int, str]:
        """解析 YOLO 数据集的类别名称映射。"""

        source_name_map = self._read_yolo_source_category_names(
            config_payload=config_payload,
            export_manifest_payload=export_manifest_payload,
        )
        if source_name_map:
            missing_category_ids = sorted(
                class_id
                for class_id in observed_class_ids
                if class_id not in source_name_map
            )
            if missing_category_ids:
                raise InvalidRequestError(
                    "YOLO 标注引用了未定义的类别 id",
                    details={"category_ids": missing_category_ids},
                )
            ordered_source_ids = sorted(source_name_map)
        else:
            ordered_source_ids = sorted(observed_class_ids)

        if not ordered_source_ids:
            raise InvalidRequestError("YOLO 数据集缺少可用的类别定义")

        resolved_name_map: dict[int, str] = {}
        for source_category_id in ordered_source_ids:
            source_name = source_name_map.get(
                source_category_id,
                f"class-{source_category_id}",
            )
            mapped_name = requested_class_map.get(
                str(source_category_id),
                requested_class_map.get(source_name, source_name),
            )
            resolved_name_map[source_category_id] = mapped_name
        normalized_names = tuple(resolved_name_map.values())
        if any(not name or name != name.strip() for name in normalized_names):
            raise InvalidRequestError("YOLO 类别名称不能为空或包含首尾空白")
        if len(set(normalized_names)) != len(normalized_names):
            raise InvalidRequestError(
                "YOLO 类别映射后名称必须唯一",
                details={"category_names": list(normalized_names)},
            )
        return resolved_name_map

    def _read_yolo_source_category_names(
        self,
        *,
        config_payload: dict[str, object],
        export_manifest_payload: dict[str, object] | None,
    ) -> dict[int, str]:
        """读取 YOLO 配置或导出 manifest 中的类别名。"""

        names_payload = config_payload.get("names")
        if isinstance(names_payload, list):
            source_names = self._validate_yolo_category_names(names_payload)
            self._validate_yolo_nc(config_payload, len(source_names))
            return dict(enumerate(source_names))
        if isinstance(names_payload, dict):
            normalized_name_map: dict[int, str] = {}
            for raw_key, raw_value in names_payload.items():
                if isinstance(raw_key, bool):
                    raise InvalidRequestError("YOLO names 类别 id 必须是非负整数")
                try:
                    category_id = int(str(raw_key))
                except ValueError as error:
                    raise InvalidRequestError(
                        "YOLO names 类别 id 必须是非负整数",
                        details={"category_id": raw_key},
                    ) from error
                if category_id < 0 or str(category_id) != str(raw_key).strip():
                    raise InvalidRequestError(
                        "YOLO names 类别 id 必须是规范的非负整数",
                        details={"category_id": raw_key},
                    )
                if category_id in normalized_name_map:
                    raise InvalidRequestError("YOLO names 存在重复类别 id")
                normalized_name_map[category_id] = self._normalize_yolo_category_name(
                    raw_value
                )
            if sorted(normalized_name_map) != list(range(len(normalized_name_map))):
                raise InvalidRequestError("YOLO names 类别 id 必须从 0 开始连续")
            self._require_unique_yolo_category_names(normalized_name_map.values())
            self._validate_yolo_nc(config_payload, len(normalized_name_map))
            return normalized_name_map

        if export_manifest_payload is None:
            return {}
        manifest_category_names = export_manifest_payload.get("category_names")
        if isinstance(manifest_category_names, list):
            source_names = self._validate_yolo_category_names(manifest_category_names)
            return dict(enumerate(source_names))
        return {}

    def _validate_yolo_category_names(self, raw_names: list[object]) -> tuple[str, ...]:
        """校验 YOLO names 列表。"""

        if not raw_names:
            raise InvalidRequestError("YOLO names 不能为空")
        names = tuple(self._normalize_yolo_category_name(value) for value in raw_names)
        self._require_unique_yolo_category_names(names)
        return names

    def _normalize_yolo_category_name(self, raw_value: object) -> str:
        """读取一个非空且无首尾空白的 YOLO 类别名称。"""

        if not isinstance(raw_value, str) or not raw_value or raw_value != raw_value.strip():
            raise InvalidRequestError(
                "YOLO 类别名称必须是非空字符串且不能包含首尾空白",
                details={"category_name": raw_value},
            )
        return raw_value

    def _require_unique_yolo_category_names(self, names: Iterable[str]) -> None:
        """要求 YOLO 类别名称唯一。"""

        normalized_names = tuple(str(name) for name in names)
        if len(set(normalized_names)) != len(normalized_names):
            raise InvalidRequestError(
                "YOLO 类别名称必须唯一",
                details={"category_names": list(normalized_names)},
            )

    def _validate_yolo_nc(self, config_payload: dict[str, object], name_count: int) -> None:
        """当 data.yaml 提供 nc 时要求它与 names 完全一致。"""

        if "nc" not in config_payload:
            return
        raw_nc = config_payload.get("nc")
        if isinstance(raw_nc, bool) or not isinstance(raw_nc, int) or raw_nc != name_count:
            raise InvalidRequestError(
                "YOLO data.yaml 的 nc 必须等于 names 类别数",
                details={"nc": raw_nc, "name_count": name_count},
            )

    def _read_yolo_pose_shape(
        self,
        config_payload: dict[str, object],
    ) -> tuple[int, int] | None:
        """读取 YOLO pose 配置中的 kpt_shape。"""

        raw_pose_shape = config_payload.get("kpt_shape")
        if raw_pose_shape is None:
            return None
        if not isinstance(raw_pose_shape, list) or len(raw_pose_shape) != 2:
            raise InvalidRequestError("YOLO pose kpt_shape 必须是两个整数")
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in raw_pose_shape
        ):
            raise InvalidRequestError("YOLO pose kpt_shape 必须是两个整数")
        keypoint_count = raw_pose_shape[0]
        point_dimensions = raw_pose_shape[1]
        if keypoint_count <= 0 or point_dimensions not in {2, 3}:
            raise InvalidRequestError(
                "YOLO pose kpt_shape 必须是 [正整数, 2|3]",
                details={"kpt_shape": raw_pose_shape},
            )
        return (keypoint_count, point_dimensions)

    def _read_yolo_pose_flip_indices(
        self,
        config_payload: dict[str, object],
        *,
        pose_shape: tuple[int, int] | None,
    ) -> tuple[int, ...] | None:
        """读取并严格校验 YOLO pose 配置中的 flip_idx。"""

        raw_indices = config_payload.get("flip_idx")
        if raw_indices is None:
            return None
        if pose_shape is None:
            raise InvalidRequestError(
                "YOLO pose 声明 flip_idx 时必须同时声明 kpt_shape"
            )
        try:
            return normalize_pose_flip_indices(
                raw_indices,
                keypoint_count=pose_shape[0],
            )
        except ValueError as error:
            raise InvalidRequestError(
                "YOLO pose flip_idx 无效",
                details={"reason": str(error)},
            ) from error
