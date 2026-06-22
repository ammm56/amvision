"""workflow 文档校验摘要构建函数。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.service.application.workflows.documents.contracts import (
    WorkflowApplicationValidationSummary,
    WorkflowTemplateValidationSummary,
)


def summarize_workflow_template(template: WorkflowGraphTemplate) -> WorkflowTemplateValidationSummary:
    """构建图模板的结构摘要。"""

    return WorkflowTemplateValidationSummary(
        template_id=template.template_id,
        template_version=template.template_version,
        node_count=len(template.nodes),
        edge_count=len(template.edges),
        template_input_ids=tuple(item.input_id for item in template.template_inputs),
        template_output_ids=tuple(item.output_id for item in template.template_outputs),
        referenced_node_type_ids=tuple(node.node_type_id for node in template.nodes),
    )


def summarize_workflow_application(
    application: FlowApplication,
) -> WorkflowApplicationValidationSummary:
    """构建流程应用的结构摘要。"""

    return WorkflowApplicationValidationSummary(
        application_id=application.application_id,
        template_id=application.template_ref.template_id,
        template_version=application.template_ref.template_version,
        binding_count=len(application.bindings),
        input_binding_ids=tuple(
            binding.binding_id for binding in application.bindings if binding.direction == "input"
        ),
        output_binding_ids=tuple(
            binding.binding_id for binding in application.bindings if binding.direction == "output"
        ),
    )
