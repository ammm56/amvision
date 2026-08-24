"""Conversion attempt 硬时限、staging 与原子发布边界。"""

from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path, PurePosixPath
import pickle
import shutil
import sys
from typing import Any

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
    deserialize_conversion_run_result,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.application.conversions.runtime.model_conversion_common import (
    resolve_conversion_project_root,
)
from backend.runtime.processes import ProcessTreeSupervisor
from backend.runtime.processes import AttemptDeadline


class SupervisedConversionRunner:
    """在独立受监督进程树中执行完整 conversion runner。"""

    RESULT_DESCRIPTOR_MAX_BYTES = 1024 * 1024

    def __init__(
        self,
        *,
        runner_kind: str,
        dataset_storage: LocalDatasetStorage,
        workspace_dir: Path,
        helper_timeout_seconds: float = 7200.0,
        termination_grace_seconds: float = 15.0,
        device_lease_config: DeviceLeaseProviderConfig | None = None,
        device_lease_provider: DeviceLeaseProvider | None = None,
    ) -> None:
        """初始化 attempt 监督与存储边界。"""

        self.runner_kind = runner_kind
        self.dataset_storage = dataset_storage
        self.workspace_dir = workspace_dir.resolve()
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

        attempt_deadline = self._require_attempt_deadline(request)
        requested_cuda_device = self._resolve_requested_cuda_device(request)
        if requested_cuda_device is None:
            return self._run_conversion_attempt(request, device_lease_metadata=None)
        remaining_seconds = attempt_deadline.remaining_seconds()
        if remaining_seconds <= 0:
            raise OperationTimeoutError("conversion Attempt 总 deadline 已到期")
        with self.device_lease_provider.acquire_cuda(
            requested_cuda_device,
            mode=DeviceLeaseMode.EXCLUSIVE,
            purpose="conversion",
            owner_id=request.conversion_task_id,
            timeout_seconds=min(
                self.device_lease_config.exclusive_acquire_timeout_seconds,
                remaining_seconds,
            ),
        ) as device_lease:
            return self._run_conversion_attempt(
                self._pin_request_to_leased_visible_device(request),
                device_lease_metadata=device_lease.info.to_dict(),
            )

    @staticmethod
    def _require_attempt_deadline(
        request: ConversionBackendRunRequest,
    ) -> AttemptDeadline:
        """从请求中恢复同一 Attempt 的持久总 deadline。"""

        if request.attempt_deadline_at is None:
            raise ServiceConfigurationError(
                "conversion run request 缺少持久 Attempt deadline"
            )
        deadline = AttemptDeadline.from_deadline_at(request.attempt_deadline_at)
        if deadline.expired():
            raise OperationTimeoutError("conversion Attempt 总 deadline 已到期")
        return deadline

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

        attempt_id = request.metadata.get("conversion_file_attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id.strip():
            raise ServiceConfigurationError(
                "conversion run request 缺少 conversion_file_attempt_id"
            )
        staging_prefix = request.output_object_prefix
        if not staging_prefix.endswith(f"/attempts/{attempt_id}/staging"):
            raise ServiceConfigurationError("conversion run request staging identity 无效")
        attempt_object_prefix = staging_prefix.removesuffix("/staging")
        attempt_deadline = self._require_attempt_deadline(request)
        staged_request = replace(
            request,
            cancel_requested=None,
        )
        control_dir = self.workspace_dir / "conversion-attempts" / attempt_id
        control_dir.mkdir(parents=True, exist_ok=False)
        request_path = control_dir / "request.pkl"
        result_path = control_dir / "result.json"
        with request_path.open("wb") as stream:
            pickle.dump(staged_request, stream, protocol=pickle.HIGHEST_PROTOCOL)

        stdout_object_key = f"{attempt_object_prefix}/logs/stdout.log"
        stderr_object_key = f"{attempt_object_prefix}/logs/stderr.log"
        stdout_log_path = self.dataset_storage.resolve(stdout_object_key)
        stderr_log_path = self.dataset_storage.resolve(stderr_object_key)
        project_root = resolve_conversion_project_root()
        process_env = dict(os.environ)
        process_env["AMVISION_WORKER_CONVERSION__HELPER_TIMEOUT_SECONDS"] = str(
            min(self.helper_timeout_seconds, attempt_deadline.remaining_seconds())
        )
        process_env["AMVISION_WORKER_CONVERSION__ATTEMPT_DEADLINE_AT"] = (
            attempt_deadline.deadline_at_iso
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
                deadline=attempt_deadline,
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
                cancel_requested=request.cancel_requested,
            )
            payload = self._read_attempt_payload(
                result_path=result_path,
                process_returncode=process_result.returncode,
                stdout_tail=process_result.stdout,
                stderr_tail=process_result.stderr,
                expected_task_id=request.conversion_task_id,
                expected_output_prefix=staging_prefix,
            )
            run_result = payload["result"]
            self._validate_staged_outputs(
                request=staged_request,
                run_result=run_result,
            )
            return replace(
                run_result,
                metadata={
                    **run_result.metadata,
                    "stdout_log_object_key": stdout_object_key,
                    "stderr_log_object_key": stderr_object_key,
                    "attempt_timeout_seconds": request.attempt_timeout_seconds,
                    "attempt_deadline_at": request.attempt_deadline_at,
                    "device_lease": device_lease_metadata,
                },
            )
        finally:
            shutil.rmtree(control_dir, ignore_errors=True)

    @staticmethod
    def _read_attempt_payload(
        *,
        result_path: Path,
        process_returncode: int,
        stdout_tail: str,
        stderr_tail: str,
        expected_task_id: str,
        expected_output_prefix: str,
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
        descriptor_size = result_path.stat().st_size
        if descriptor_size > SupervisedConversionRunner.RESULT_DESCRIPTOR_MAX_BYTES:
            raise ServiceConfigurationError(
                "conversion attempt result descriptor 超过 1 MiB 上限",
                details={"descriptor_size": descriptor_size},
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ServiceConfigurationError(
                "conversion attempt result descriptor 不是合法 JSON"
            ) from error
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
        return {
            **payload,
            "result": deserialize_conversion_run_result(
                payload.get("result"),
                expected_task_id=expected_task_id,
                expected_output_prefix=expected_output_prefix,
            ),
        }

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

__all__ = ["SupervisedConversionRunner"]
