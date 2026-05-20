import type { NodeDefinition, WorkflowGraphTemplate } from '../../types'
import {
  canvasSnapshotToWorkflowTemplate,
  workflowTemplateToCanvasSnapshot,
  type WorkflowCanvasGraphSnapshot,
} from './workflow-graph-conversion'

export interface WorkflowLiteGraphAdapterInput {
  nodeDefinitions: NodeDefinition[]
}

export interface WorkflowLiteGraphGraphState {
  vars: Record<string, unknown>
}

export interface WorkflowLiteGraphAdapter {
  readonly graph: WorkflowLiteGraphGraphState
  loadTemplate(template: WorkflowGraphTemplate): WorkflowCanvasGraphSnapshot
  exportTemplate(sourceTemplate: WorkflowGraphTemplate, snapshot: WorkflowCanvasGraphSnapshot): WorkflowGraphTemplate
}

export function createWorkflowLiteGraphAdapter(input: WorkflowLiteGraphAdapterInput): WorkflowLiteGraphAdapter {
  const graph: WorkflowLiteGraphGraphState = { vars: {} }
  const nodeDefinitionById = new Map(input.nodeDefinitions.map((definition) => [definition.node_type_id, definition]))

  return {
    graph,
    loadTemplate(template) {
      const snapshot = workflowTemplateToCanvasSnapshot(template)
      graph.vars = {
        ...graph.vars,
        nodeDefinitionCount: nodeDefinitionById.size,
        workflowNodeCount: snapshot.nodes.length,
        workflowEdgeCount: snapshot.edges.length,
      }
      return snapshot
    },
    exportTemplate(sourceTemplate, snapshot) {
      return canvasSnapshotToWorkflowTemplate(sourceTemplate, snapshot)
    },
  }
}
