"""Conversion attempt 硬时限、staging 与原子发布边界。"""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path, PurePosixPath
import pickle
import shutil
import sys
from typing import Any
from uuid import uuid4

from backend.service.application.backends import (
    ConversionBackendRunRequest,
    ConversionBackendRunResult,
)
from backend.service.application.errors import (
    OperationTimeoutError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.device_leases import (
    DeviceLeaseMode,
    DeviceLeaseProvider,
    DeviceLeaseProviderConfig,
)
from backend.service.application.conversions.publication import (
    serialize_conversion_run_result,
    write_conversion_publication_state,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.workers.conversion.model_conversion_common import (
    resolve_conversion_project_root,
)
from backend.workers.shared.process_tree_supervisor import ProcessTreeSupervisor


class SupervisedConversionRunner:
    """在独立受监督进程树中执行完整 conversion runner。"""

    def __init__(
        self,
        *,
        runner_kind: str,
        dataset_storage: LocalDatasetStorage,
        workspace_dir: Path,
        timeout_seconds: float,
        helper_timeout_seconds: float = 7200.0,
        termination_grace_seconds: float = 5.0,
        device_lease_config: DeviceLeaseProviderConfig | None = None,
        device_lease_provider: DeviceLeaseProvider | None = None,
    ) -> None:
        """初始化 attempt 监督与存储边界。"""

        self.runner_kind = runner_kind
        self.dataset_storage = dataset_storage
        self.workspace_dir = workspace_dir.resolve()
        self.timeout_seconds = float(timeout_seconds)
        self.helper_timeout_seconds = float(helper_timeout_seconds)
        self.termination_grace_seconds = float(termination_grace_seconds)
        self.device_lease_config = device_lease_config or DeviceLeaseProviderConfig()
        self.device_lease_provider = device_lease_provider or (
            DeviceLeaseProvider.from_config(self.device_lease_config)
        )

    def run_conversion(
        self,
        request: ConversionBackendRunRequest,
    ) -> ConversionBackendRunResult:
        """通过 staging 执行、校验并原子发布一次转换。"""

        requested_cuda_device = self._resolve_requested_cuda_device(request)
        if requested_cuda_device is None:
            return self._run_conversion_attempt(request, device_lease_metadata=None)
        with self.device_lease_provider.acquire_cuda(
            requested_cuda_device,
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="conversion",
            owner_id=request.conversion_task_id,
            timeout_seconds=(
                self.device_lease_config.exclusive_acquire_timeout_seconds
            ),
        ) as device_lease:
            return self._run_conversion_attempt(
                self._pin_request_to_leased_visible_device(request),
                device_lease_metadata=device_lease.info.to_dict(),
            )

    def _resolve_requested_cuda_device(
        self,
        request: ConversionBackendRunRequest,
    ) -> str | None:
        """返回该 attempt 实际会使用的 CUDA 设备；纯 CPU attempt 返回空。"""

        if "tensorrt-engine" in request.target_formats:
            return self.device_lease_config.conversion_cuda_device
        source_device = getattr(request.source_runtime_target, "device_name", None)
        if not isinstance(source_device, str):
            return None
        normalized = source_device.strip().lower()
        if normalized in {"cuda", "gpu"} or normalized.startswith("cuda:"):
            return source_device
        return None

    @staticmethod
    def _pin_request_to_leased_visible_device(
        request: ConversionBackendRunRequest,
    ) -> ConversionBackendRunRequest:
        """CVD 已缩减为单个 UUID 后，把子进程来源 runtime 固定到 cuda:0。"""

        source_target = request.source_runtime_target
        source_device = getattr(source_target, "device_name", None)
        if not isinstance(source_device, str):
            return request
        normalized = source_device.strip().lower()
        if normalized not in {"cuda", "gpu"} and not normalized.startswith("cuda:"):
            return request
        return replace(
            request,
            source_runtime_target=replace(source_target, device_name="cuda:0"),
        )

    def _run_conversion_attempt(
        self,
        request: ConversionBackendRunRequest,
        *,
        device_lease_metadata: dict[str, object] | None,
    ) -> ConversionBackendRunResult:
        """在需要时已持有独占 GPU lease 的前提下执行 attempt。"""

        attempt_id = f"conversion-attempt-{uuid4().hex}"
        attempt_object_prefix = (
            f"{request.output_object_prefix}/attempts/{attempt_id}"
        )
        staging_prefix = f"{attempt_object_prefix}/staging"
        staged_request = replace(request, output_object_prefix=staging_prefix)
        control_dir = self.workspace_dir / "conversion-attempts" / attempt_id
        control_dir.mkdir(parents=True, exist_ok=False)
        request_path = control_dir / "request.pkl"
        result_path = control_dir / "result.pkl"
        with request_path.open("wb") as stream:
            pickle.dump(staged_request, stream, protocol=pickle.HIGHEST_PROTOCOL)

        stdout_object_key = f"{attempt_object_prefix}/logs/stdout.log"
        stderr_object_key = f"{attempt_object_prefix}/logs/stderr.log"
        publication_object_key = f"{attempt_object_prefix}/publication.json"
        stdout_log_path = self.dataset_storage.resolve(stdout_object_key)
        stderr_log_path = self.dataset_storage.resolve(stderr_object_key)
        project_root = resolve_conversion_project_root()
        process_env = dict(os.environ)
        process_env["AMVISION_WORKER_CONVERSION__HELPER_TIMEOUT_SECONDS"] = str(
            self.helper_timeout_seconds
        )
        if device_lease_metadata is not None:
            resource_key = device_lease_metadata.get("resource_key")
            if isinstance(resource_key, str) and resource_key:
                # 子进程只看见已租用的 GPU/MIG；其内部继续稳定使用 cuda:0。
                process_env["CUDA_VISIBLE_DEVICES"] = resource_key
        process_env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (
                str(project_root),
                process_env.get("PYTHONPATH", ""),
            )
            if part
        )
        try:
            process_result = ProcessTreeSupervisor(
                timeout_seconds=self.timeout_seconds,
                termination_grace_seconds=self.termination_grace_seconds,
            ).run(
                [
                    sys.executable,
                    "-m",
                    "backend.workers.conversion.attempt_entrypoint",
                    "--runner-kind",
                    self.runner_kind,
                    "--dataset-root",
                    str(self.dataset_storage.root_dir),
                    "--request-path",
                    str(request_path),
                    "--result-path",
                    str(result_path),
                ],
                cwd=project_root,
                env=process_env,
                stdout_log_path=stdout_log_path,
                stderr_log_path=stderr_log_path,
            )
            payload = self._read_attempt_payload(
                result_path=result_path,
                process_returncode=process_result.returncode,
                stdout_tail=process_result.stdout,
                stderr_tail=process_result.stderr,
            )
            run_result = payload.get("result")
            if not isinstance(run_result, ConversionBackendRunResult):
                raise ServiceConfigurationError(
                    "conversion attempt 返回结果类型无效",
                    details={"attempt_id": attempt_id},
                )
            self._validate_staged_outputs(
                request=staged_request,
                run_result=run_result,
            )
            final_builds_object_key = (
                f"{request.output_object_prefix}/artifacts/builds"
            )
            expected_published_result = self._build_published_result(
                request=request,
                staging_prefix=staging_prefix,
                run_result=run_result,
            )
            expected_published_result = replace(
                expected_published_result,
                metadata={
                    **expected_published_result.metadata,
                    "conversion_attempt_id": attempt_id,
                    "stdout_log_object_key": stdout_object_key,
                    "stderr_log_object_key": stderr_object_key,
                    "attempt_timeout_seconds": self.timeout_seconds,
                    "publication_record_object_key": publication_object_key,
                    "device_lease": device_lease_metadata,
                },
            )
            write_conversion_publication_state(
                dataset_storage=self.dataset_storage,
                publication_object_key=publication_object_key,
                state="publishing",
                payload={
                    "conversion_task_id": request.conversion_task_id,
                    "conversion_attempt_id": attempt_id,
                    "final_builds_object_key": final_builds_object_key,
                    "target_formats": [
                        output.target_format for output in run_result.outputs
                    ],
                    "run_result": serialize_conversion_run_result(
                        expected_published_result
                    ),
                },
            )
            published_result = self._publish_staged_outputs(
                request=request,
                staging_prefix=staging_prefix,
                run_result=run_result,
            )
            write_conversion_publication_state(
                dataset_storage=self.dataset_storage,
                publication_object_key=publication_object_key,
                state="published_pending_registration",
                payload={
                    "published_object_uris": [
                        output.object_uri for output in published_result.outputs
                    ],
                },
            )
            return expected_published_result
        finally:
            shutil.rmtree(control_dir, ignore_errors=True)

    @staticmethod
    def _read_attempt_payload(
        *,
        result_path: Path,
        process_returncode: int,
        stdout_tail: str,
        stderr_tail: str,
    ) -> dict[str, Any]:
        """读取子进程结构化结果并保留日志诊断。"""

        if not result_path.is_file():
            raise ServiceConfigurationError(
                "conversion attempt 未生成结果文件",
                details={
                    "process_returncode": process_returncode,
                    "stdout_tail": stdout_tail,
                    "stderr_tail": stderr_tail,
                },
            )
        with result_path.open("rb") as stream:
            payload = pickle.load(stream)  # noqa: S301 - 仅消费本地 attempt 子进程结果
        if not isinstance(payload, dict):
            raise ServiceConfigurationError("conversion attempt 结果文件格式无效")
        if payload.get("ok") is not True:
            raw_error = payload.get("error")
            error_payload = dict(raw_error) if isinstance(raw_error, dict) else {}
            error_message = str(
                error_payload.get("error_message")
                or "conversion attempt 执行失败"
            )
            diagnostic_details = {
                "child_error": error_payload,
                "child_traceback": payload.get("traceback"),
                "process_returncode": process_returncode,
                "stdout_tail": stdout_tail,
                "stderr_tail": stderr_tail,
            }
            if error_payload.get("error_type") == "OperationTimeoutError":
                raise OperationTimeoutError(
                    error_message,
                    details=diagnostic_details,
                )
            raise ServiceConfigurationError(
                error_message,
                details=diagnostic_details,
            )
        if process_returncode != 0:
            raise ServiceConfigurationError(
                "conversion attempt 结果与进程退出状态不一致",
                details={"process_returncode": process_returncode},
            )
        return payload

    def _validate_staged_outputs(
        self,
        *,
        request: ConversionBackendRunRequest,
        run_result: ConversionBackendRunResult,
    ) -> None:
        """在发布前检查文件完整性和已有数值门禁摘要。"""

        if not run_result.outputs:
            raise ServiceConfigurationError("conversion attempt 没有生成任何输出")
        produced_formats = {output.target_format for output in run_result.outputs}
        missing_formats = sorted(set(request.target_formats) - produced_formats)
        if missing_formats:
            raise ServiceConfigurationError(
                "conversion attempt 缺少请求的目标格式",
                details={"missing_target_formats": missing_formats},
            )
        for output in run_result.outputs:
            output_path = self.dataset_storage.resolve(output.object_uri)
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise ServiceConfigurationError(
                    "conversion staging 产物不完整",
                    details={"object_uri": output.object_uri},
                )
            if output.target_format == "openvino-ir":
                weights_uri = output.metadata.get("weights_object_uri")
                if not isinstance(weights_uri, str):
                    weights_uri = PurePosixPath(output.object_uri).with_suffix(".bin").as_posix()
                weights_path = self.dataset_storage.resolve(weights_uri)
                if not weights_path.is_file() or weights_path.stat().st_size <= 0:
                    raise ServiceConfigurationError(
                        "conversion staging OpenVINO 权重不完整",
                        details={"weights_object_uri": weights_uri},
                    )
            self._validate_output_gate(output)

    @staticmethod
    def _validate_output_gate(output: Any) -> None:
        """验证单个目标产物携带的数值一致性与 runtime smoke 摘要。"""

        validation_summary = output.metadata.get("validation_summary")
        if not isinstance(validation_summary, dict):
            raise ServiceConfigurationError(
                "conversion 产物缺少源模型数值一致性摘要",
                details={
                    "target_format": output.target_format,
                    "object_uri": output.object_uri,
                },
            )
        if validation_summary.get("finite") is False:
            raise ServiceConfigurationError(
                "conversion 数值校验发现 NaN 或 Inf",
                details=dict(validation_summary),
            )
        accepted = validation_summary.get("accepted")
        if accepted is False:
            raise ServiceConfigurationError(
                "conversion 源模型数值一致性校验未达到任务容差",
                details=dict(validation_summary),
            )
        if accepted is not True and validation_summary.get("allclose") is not True:
            raise ServiceConfigurationError(
                "conversion 源模型数值一致性校验失败",
                details=dict(validation_summary),
            )
        if output.target_format not in {"openvino-ir", "tensorrt-engine"}:
            return
        runtime_smoke = output.metadata.get("runtime_smoke")
        if not isinstance(runtime_smoke, dict) or runtime_smoke.get("passed") is not True:
            raise ServiceConfigurationError(
                "conversion 运行时 smoke 未通过",
                details={
                    "target_format": output.target_format,
                    "object_uri": output.object_uri,
                    "runtime_smoke": runtime_smoke,
                },
            )

    def _publish_staged_outputs(
        self,
        *,
        request: ConversionBackendRunRequest,
        staging_prefix: str,
        run_result: ConversionBackendRunResult,
    ) -> ConversionBackendRunResult:
        """把完整 staging builds 目录一次原子 rename 为最终不可变目录。"""

        staged_builds_key = f"{staging_prefix}/artifacts/builds"
        final_builds_key = f"{request.output_object_prefix}/artifacts/builds"
        staged_builds_path = self.dataset_storage.resolve(staged_builds_key)
        final_builds_path = self.dataset_storage.resolve(final_builds_key)
        if not staged_builds_path.is_dir():
            raise ServiceConfigurationError(
                "conversion staging builds 目录不存在",
                details={"staged_builds_key": staged_builds_key},
            )
        if final_builds_path.exists():
            raise ServiceConfigurationError(
                "conversion 最终 builds 已存在，拒绝覆盖不可变产物",
                details={"final_builds_key": final_builds_key},
            )
        final_builds_path.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staged_builds_path, final_builds_path)
        return self._build_published_result(
            request=request,
            staging_prefix=staging_prefix,
            run_result=run_result,
        )

    @staticmethod
    def _build_published_result(
        *,
        request: ConversionBackendRunRequest,
        staging_prefix: str,
        run_result: ConversionBackendRunResult,
    ) -> ConversionBackendRunResult:
        """在 rename 前确定 publication 中最终且不可变的路径描述。"""

        remapped_outputs = tuple(
            replace(
                output,
                object_uri=_remap_prefix(
                    output.object_uri,
                    source_prefix=staging_prefix,
                    target_prefix=request.output_object_prefix,
                ),
                metadata=_remap_metadata_paths(
                    output.metadata,
                    source_prefix=staging_prefix,
                    target_prefix=request.output_object_prefix,
                ),
            )
            for output in run_result.outputs
        )
        return replace(
            run_result,
            outputs=remapped_outputs,
            metadata=_remap_metadata_paths(
                run_result.metadata,
                source_prefix=staging_prefix,
                target_prefix=request.output_object_prefix,
            ),
        )


def _remap_prefix(value: str, *, source_prefix: str, target_prefix: str) -> str:
    """把 staging object key 前缀替换为最终发布前缀。"""

    if value == source_prefix:
        return target_prefix
    marker = f"{source_prefix}/"
    if value.startswith(marker):
        return f"{target_prefix}/{value[len(marker):]}"
    return value


def _remap_metadata_paths(
    value: Any,
    *,
    source_prefix: str,
    target_prefix: str,
) -> Any:
    """递归替换 metadata 中的 staging object key。"""

    if isinstance(value, str):
        return _remap_prefix(
            value,
            source_prefix=source_prefix,
            target_prefix=target_prefix,
        )
    if isinstance(value, dict):
        return {
            key: _remap_metadata_paths(
                item,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _remap_metadata_paths(
                item,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            _remap_metadata_paths(
                item,
                source_prefix=source_prefix,
                target_prefix=target_prefix,
            )
            for item in value
        )
    return value


__all__ = ["SupervisedConversionRunner"]
