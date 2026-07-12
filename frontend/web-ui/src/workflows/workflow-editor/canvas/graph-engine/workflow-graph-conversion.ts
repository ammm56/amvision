import type {
  WorkflowGraphEdge,
  WorkflowGraphGroup,
  WorkflowGraphInput,
  WorkflowGraphNode,
  WorkflowGraphOutput,
  WorkflowGraphTemplate,
  WorkflowJsonObject,
} from '../../types'

export interface WorkflowCanvasNodeSnapshot {
  node_id: string
  node_type_id: string
  enabled: boolean
  x: number
  y: number
  width: number
  parameters: WorkflowJsonObject
  metadata: WorkflowJsonObject
  ui_state: WorkflowJsonObject
}

export interface WorkflowCanvasGraphSnapshot {
  nodes: WorkflowCanvasNodeSnapshot[]
  edges: WorkflowGraphEdge[]
  template_inputs: WorkflowGraphInput[]
  template_outputs: WorkflowGraphOutput[]
  groups: WorkflowGraphGroup[]
}

function readNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function snapshotNodeToGraphNode(snapshot: WorkflowCanvasNodeSnapshot): WorkflowGraphNode {
  return {
    node_id: snapshot.node_id,
    node_type_id: snapshot.node_type_id,
    enabled: snapshot.enabled !== false,
    parameters: { ...snapshot.parameters },
    ui_state: {
      ...snapshot.ui_state,
      x: snapshot.x,
      y: snapshot.y,
      width: snapshot.width,
    },
    metadata: { ...snapshot.metadata },
  }
}

function cloneGraphGroup(group: WorkflowGraphGroup): WorkflowGraphGroup {
  return {
    ...group,
    rect: { ...group.rect },
    member_node_ids: [...group.member_node_ids],
    metadata: { ...group.metadata },
  }
}

export function workflowTemplateToCanvasSnapshot(template: WorkflowGraphTemplate): WorkflowCanvasGraphSnapshot {
  return {
    nodes: template.nodes.map((node, index) => ({
      node_id: node.node_id,
      node_type_id: node.node_type_id,
      enabled: node.enabled !== false,
      x: readNumber(node.ui_state.x ?? node.ui_state.pos_x ?? node.ui_state.position_x, 360 + (index % 3) * 280),
      y: readNumber(node.ui_state.y ?? node.ui_state.pos_y ?? node.ui_state.position_y, 120 + Math.floor(index / 3) * 180),
      width: readNumber(node.ui_state.width, 230),
      parameters: { ...node.parameters },
      metadata: { ...node.metadata },
      ui_state: { ...node.ui_state },
    })),
    edges: template.edges.map((edge) => ({ ...edge, metadata: { ...edge.metadata } })),
    template_inputs: template.template_inputs.map((input) => ({ ...input, metadata: { ...input.metadata } })),
    template_outputs: template.template_outputs.map((output) => ({ ...output, metadata: { ...output.metadata } })),
    groups: template.groups.map(cloneGraphGroup),
  }
}

export function canvasSnapshotToWorkflowTemplate(
  sourceTemplate: WorkflowGraphTemplate,
  snapshot: WorkflowCanvasGraphSnapshot,
): WorkflowGraphTemplate {
  return {
    ...sourceTemplate,
    nodes: snapshot.nodes.map(snapshotNodeToGraphNode),
    edges: snapshot.edges.map((edge) => ({ ...edge, metadata: { ...edge.metadata } })),
    template_inputs: snapshot.template_inputs.map((input) => ({ ...input, metadata: { ...input.metadata } })),
    template_outputs: snapshot.template_outputs.map((output) => ({ ...output, metadata: { ...output.metadata } })),
    groups: snapshot.groups.map(cloneGraphGroup),
    metadata: { ...sourceTemplate.metadata },
  }
}
