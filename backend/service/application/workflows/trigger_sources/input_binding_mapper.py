"""TriggerSource input binding 映射器。"""

from __future__ import annotations

from backend.contracts.workflows import TriggerEventContract
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.trigger_sources.path_values import (
    MISSING_PATH_VALUE,
    read_dotted_path,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


class InputBindingMapper:
    """把 TriggerEventContract 转换为 WorkflowRuntime input_bindings。"""

    def map_input_bindings(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        trigger_event: TriggerEventContract,
    ) -> dict[str, object]:
        """执行 input binding 映射。

        参数：
        - trigger_source：触发源配置。
        - trigger_event：标准化后的触发事件。

        返回：
        - dict[str, object]：可传入 WorkflowRuntime 的 input_bindings。
        """

        event_context = {
            "payload": dict(trigger_event.payload),
            "metadata": dict(trigger_event.metadata),
            "event": trigger_event.model_dump(exclude={"payload", "metadata"}),
        }
        input_bindings: dict[str, object] = {}
        for binding_id, mapping_rule in trigger_source.input_binding_mapping.items():
            input_bindings[binding_id] = self._resolve_mapping_rule(
                binding_id=binding_id,
                mapping_rule=mapping_rule,
                event_context=event_context,
            )
        return input_bindings

    def _resolve_mapping_rule(
        self,
        *,
        binding_id: str,
        mapping_rule: object,
        event_context: dict[str, object],
    ) -> object:
        """解析单条 input binding 映射规则。"""

        if not isinstance(mapping_rule, dict):
            return mapping_rule
        if "value" in mapping_rule:
            return mapping_rule["value"]
        source_path = mapping_rule.get("source")
        if not isinstance(source_path, str) or not source_path.strip():
            if bool(mapping_rule.get("required", True)):
                raise InvalidRequestError(
                    "input binding 映射缺少 source",
                    details={"binding_id": binding_id},
                )
            return None
        mapped_value = read_dotted_path(event_context, source_path)
        if mapped_value is MISSING_PATH_VALUE:
            if bool(mapping_rule.get("required", True)):
                raise InvalidRequestError(
                    "input binding 映射来源不存在",
                    details={"binding_id": binding_id, "source": source_path},
                )
            return None
        return mapped_value
