import type { Ref, ShallowRef } from 'vue'

import type { WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import type { WorkflowCanvasGraphSnapshot } from '../canvas/graph-engine/workflow-graph-conversion'
import type { WorkflowAppDocument } from '../services/workflow-app.service'
import type {
  FlowApplication,
  FlowApplicationBinding,
  WorkflowGraphEdge,
  WorkflowGraphInput,
  WorkflowGraphOutput,
  WorkflowGraphTemplate,
  WorkflowJsonObject,
} from '../types'

export interface WorkflowDocumentBuilderNodeView {
  node: {
    node_id: string
    node_type_id: string
    parameters: WorkflowJsonObject
    metadata: WorkflowJsonObject
    ui_state: WorkflowJsonObject
  }
  x: number
  y: number
  width: number
}

export interface WorkflowDocumentBuilderOptions<NodeView extends WorkflowDocumentBuilderNodeView> {
  workflowApp: Ref<WorkflowAppDocument | null>
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  applicationBindingsDraft: Ref<FlowApplicationBinding[]>
  liteGraphAdapter: ShallowRef<WorkflowLiteGraphAdapter | null>
  applyNewWorkflowTemplateSettings: (template: WorkflowGraphTemplate) => WorkflowGraphTemplate
  buildNewWorkflowApplicationPatch: (sourceApplication: FlowApplication, template: WorkflowGraphTemplate) => FlowApplication
  writeBoundaryPositionsToMetadata: (metadata: WorkflowJsonObject) => WorkflowJsonObject
}

export function useWorkflowDocumentBuilder<NodeView extends WorkflowDocumentBuilderNodeView>(
  options: WorkflowDocumentBuilderOptions<NodeView>,
) {
  function createCanvasSnapshot(): WorkflowCanvasGraphSnapshot {
    return {
      nodes: options.graphNodes.value.map((node) => ({
        node_id: node.node.node_id,
        node_type_id: node.node.node_type_id,
        x: node.x,
        y: node.y,
        width: node.width,
        parameters: { ...node.node.parameters },
        metadata: { ...node.node.metadata },
        ui_state: { ...node.node.ui_state, x: node.x, y: node.y, width: node.width },
      })),
      edges: options.graphEdges.value.map((edge) => ({ ...edge, metadata: { ...edge.metadata } })),
      template_inputs: options.templateInputs.value.map((input) => ({ ...input, metadata: { ...input.metadata } })),
      template_outputs: options.templateOutputs.value.map((output) => ({ ...output, metadata: { ...output.metadata } })),
    }
  }

  function buildCurrentTemplate(): WorkflowGraphTemplate | null {
    const sourceTemplate = options.workflowApp.value?.graphDocument.template
    if (!sourceTemplate) return null
    const snapshot = createCanvasSnapshot()
    const template = options.liteGraphAdapter.value?.exportTemplate(sourceTemplate, snapshot) ?? sourceTemplate
    return options.applyNewWorkflowTemplateSettings(template)
  }

  function buildCurrentApplication(template: WorkflowGraphTemplate): FlowApplication | null {
    const sourceApplication = options.workflowApp.value?.applicationDocument.application
    if (!sourceApplication) return null
    return {
      ...options.buildNewWorkflowApplicationPatch(sourceApplication, template),
      bindings: options.applicationBindingsDraft.value.map((binding) => ({
        ...binding,
        config: { ...binding.config },
        metadata: { ...binding.metadata },
      })),
      metadata: options.writeBoundaryPositionsToMetadata(sourceApplication.metadata),
    }
  }

  return {
    createCanvasSnapshot,
    buildCurrentTemplate,
    buildCurrentApplication,
  }
}
