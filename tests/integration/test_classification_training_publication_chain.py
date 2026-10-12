"""分类 full core 从数据导入到常驻部署的真实 GPU 验收。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.integration import yolo_model_full_chain_smoke as smoke


@pytest.mark.parametrize("model_type", ["yolo11", "yolov8", "yolo26"])
def test_classification_training_publication_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model_type: str
) -> None:
    """通过正式服务验证训练、评估、三个转换后端和两种部署模式。"""

    if os.environ.get("AMVISION_RUN_TRAINING_PUBLICATION_SMOKE") != "1":
        pytest.skip("需要显式启用真实 CUDA/ONNX/OpenVINO/TensorRT 全链路验收")
    run_dir = tmp_path / "training-publication"
    run_dir.mkdir()
    storage_root = run_dir / "files"
    port = smoke.find_free_port(5760, 5799)
    original_environment = smoke.build_e2e_process_environment

    def environment(*, run_dir: Path, port: int) -> dict[str, str]:
        """隔离数据集、任务和模型输出，不写入开发服务的存储。"""

        values = original_environment(run_dir=run_dir, port=port)
        values["AMVISION_DATASET_STORAGE__ROOT_DIR"] = str(storage_root)
        values["AMVISION_WORKER_DATASET_STORAGE__ROOT_DIR"] = str(storage_root)
        values["AMVISION_PROJECTS__ITEMS"] = json.dumps(
            [{"project_id": "project-1", "display_name": "training publication smoke"}]
        )
        return values

    monkeypatch.setattr(smoke, "build_e2e_process_environment", environment)
    case = smoke.build_default_task_cases()["classification"]
    processes = smoke.start_service_processes(
        run_dir=run_dir, port=port, service_timeout_seconds=90
    )
    client = smoke.SmokeApiClient(
        base_url=f"http://127.0.0.1:{port}",
        token=smoke.DEFAULT_TOKEN,
        timeout_seconds=180,
    )
    try:
        result = smoke.run_task_case(
            client=client,
            case=case,
            run_dir=run_dir,
            project_id="project-1",
            model_type=model_type,
            model_scale="nano",
            target_formats=("onnx", "openvino-ir", "tensorrt-engine"),
            max_epochs=2,
            batch_size=2,
            training_device="cuda:0",
            timeout_seconds=600,
            skip_deployment=False,
            run_workflow=True,
            max_images_per_split=0,
            storage_root=storage_root,
        )
        assert result["status"] == "succeeded"
        assert result["evaluation"]["state"] == "succeeded"
        for metric in ("top1_accuracy", "top5_accuracy"):
            assert 0 <= result["training_test_metrics"][metric] <= 1
            assert 0 <= result["evaluation"][metric] <= 1

        training = client.get(
            f"/tasks/{result['training_task_id']}", params={"include_events": "true"}
        )
        assert training["events"]
        validation = smoke.load_registered_report(
            training, "validation_metrics_object_key", storage_root=storage_root
        )
        assert [row["epoch"] for row in validation["epoch_history"]] == [1, 2]
        for row in validation["epoch_history"]:
            assert 0 <= row["top1_accuracy"] <= 1
            assert 0 <= row["top5_accuracy"] <= 1
        train_metrics = smoke.load_registered_report(
            training, "metrics_object_key", storage_root=storage_root
        )
        assert train_metrics["implementation_mode"] == f"{model_type}-classification-core"
        assert train_metrics["training_runtime"]["optimizer_successful_steps"] > 0

        versions = client.client.get(
            "/models/deployment-sources",
            params={"project_id": "project-1", "task_type": "classification"},
        )
        versions.raise_for_status()
        source = next(
            version
            for model in versions.json()
            for version in model["available_versions"]
            if version["model_version_id"] == result["model_version_id"]
        )
        labels = source["metadata"]["category_names"]
        assert labels == ["ng", "ok"]
        assert source["labels_file_id"]
        assert (storage_root / source["checkpoint_storage_uri"]).stat().st_size > 0
        assert (storage_root / source["labels_storage_uri"]).read_text(
            encoding="utf-8-sig"
        ).splitlines() == labels
        for conversion in result["conversions"].values():
            deployment = conversion["deployment"]
            assert deployment["workflow"]["run"]["state"] == "succeeded"
            for mode, result_key in (("sync", "result_summary"), ("async", "result")):
                assert deployment[mode]["status"]["process_state"] == "running"
                assert deployment[mode]["status"]["process_id"] is not None
                prediction = deployment[mode][result_key]
                assert prediction["top_category"]["class_name"] in labels
                for category in prediction["categories"]:
                    assert category["class_name"] == labels[category["class_id"]]
                    assert 0 <= category["probability"] <= 1
            assert deployment["async"]["task"]["state"] == "succeeded"
        print(
            f"verified {model_type} classification: import/export, 2-epoch full core "
            "training, validation/test/evaluation, labels, ONNX/OpenVINO/TensorRT, "
            "sync/async resident processes, inference, workflow",
            flush=True,
        )
    finally:
        client.close()
        smoke.stop_managed_processes(processes)
