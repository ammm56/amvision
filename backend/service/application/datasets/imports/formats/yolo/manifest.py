"""YOLO 数据集配置和类别信息解析。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from backend.service.application.errors import InvalidRequestError


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
                raw_payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
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
                    manifest_path.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                raw_manifest_payload = None
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
        yaml_path: Path,
        configured_root: str,
        resolved_configured_root: Path,
    ) -> Path:
        """解析 YOLO data.yaml 中的 dataset root。"""

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
            return normalized_path.resolve(strict=False)
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
            return {
                category_id: str(category_name)
                for category_id, category_name in enumerate(names_payload)
            }
        if isinstance(names_payload, dict):
            normalized_name_map: dict[int, str] = {}
            for raw_key, raw_value in names_payload.items():
                try:
                    category_id = int(str(raw_key))
                except ValueError:
                    continue
                normalized_name_map[category_id] = str(raw_value)
            return normalized_name_map

        if export_manifest_payload is None:
            return {}
        manifest_category_names = export_manifest_payload.get("category_names")
        if isinstance(manifest_category_names, list):
            return {
                category_id: str(category_name)
                for category_id, category_name in enumerate(manifest_category_names)
            }
        return {}

    def _read_yolo_pose_shape(
        self,
        config_payload: dict[str, object],
    ) -> tuple[int, int] | None:
        """读取 YOLO pose 配置中的 kpt_shape。"""

        raw_pose_shape = config_payload.get("kpt_shape")
        if not isinstance(raw_pose_shape, list) or len(raw_pose_shape) < 2:
            return None
        try:
            keypoint_count = int(raw_pose_shape[0])
            point_dimensions = int(raw_pose_shape[1])
        except (TypeError, ValueError):
            return None
        if keypoint_count <= 0 or point_dimensions not in {2, 3}:
            return None
        return (keypoint_count, point_dimensions)
