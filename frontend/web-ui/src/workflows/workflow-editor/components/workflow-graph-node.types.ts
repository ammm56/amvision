import type { PreviewNodeDisplay, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowNodePortRowView } from '../nodes/useWorkflowNodeDisplayHelpers'
import type { WorkflowNodeParameterSelectOption, WorkflowNodeParameterSelectValue } from '../parameters/useWorkflowNodeParameters'
import type { NodeParameterUiField, NodePortDefinition } from '../types'

type PortDirection = 'input' | 'output'

export interface WorkflowGraphNodeProps {
  node: WorkflowGraphNodeView
  selectedNodeId: string | null
  lastPreviewFailureNodeId: string | null
  readNodeHeight: (node: WorkflowGraphNodeView) => number
  readTitle: (node: WorkflowGraphNodeView) => string
  readPortRows: (node: WorkflowGraphNodeView) => WorkflowNodePortRowView[]
  readPortLabel: (port: NodePortDefinition) => string
  isPortConnected: (nodeId: string, portName: string, direction: PortDirection) => boolean
  isSelectedEdgeEndpoint: (nodeId: string, portName: string, direction: PortDirection) => boolean
  isDraftAnchorPort: (nodeId: string, portName: string, direction: PortDirection) => boolean
  readParameterFields: (node: WorkflowGraphNodeView) => NodeParameterUiField[]
  readParameterLabel: (field: NodeParameterUiField) => string
  readParameterEnumIndex: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => string
  readParameterEnumOptions: (field: NodeParameterUiField) => WorkflowNodeParameterSelectOption[]
  isBooleanParameter: (field: NodeParameterUiField) => boolean
  readParameterBooleanValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => boolean
  isNumberParameter: (field: NodeParameterUiField) => boolean
  readParameterTextValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => string
  isStringParameter: (field: NodeParameterUiField) => boolean
  isColorMapParameter: (field: NodeParameterUiField) => boolean
  readParameterValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => unknown
  isJsonParameter: (field: NodeParameterUiField) => boolean
  readParameterJsonTextValue: (node: WorkflowGraphNodeView, field: NodeParameterUiField) => string
  readParameterJsonPlaceholder: (field: NodeParameterUiField) => string
  readInputSourceLabel: (nodeId: string, portName: string) => string
  readPreviewDisplay: (nodeId: string) => PreviewNodeDisplay | null
  readPreviewDisplayTooltip: (display: PreviewNodeDisplay | null) => string
  readPreviewDurationMs: (nodeId: string) => number | null
  readPreviewStatus?: (nodeId: string) => string
}

export interface WorkflowGraphNodeEvents {
  startNodeDrag: [event: MouseEvent, node: WorkflowGraphNodeView]
  nodeClick: [nodeId: string]
  openNodeContextMenu: [event: MouseEvent, node: WorkflowGraphNodeView]
  startPortConnection: [event: MouseEvent, node: WorkflowGraphNodeView, port: NodePortDefinition, direction: PortDirection]
  selectPortEndpoint: [node: WorkflowGraphNodeView, port: NodePortDefinition, direction: PortDirection]
  openPortContextMenu: [event: MouseEvent, node: WorkflowGraphNodeView, port: NodePortDefinition, direction: PortDirection]
  updateEnumParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, value: WorkflowNodeParameterSelectValue]
  updateCheckboxParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  updateNumberParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  updateTextParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  updateValueParameter: [node: WorkflowGraphNodeView, field: NodeParameterUiField, value: unknown]
  updateJsonParameterDraft: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  commitJsonParameterDraft: [node: WorkflowGraphNodeView, field: NodeParameterUiField, event: Event]
  selectDeploymentInstance: [node: WorkflowGraphNodeView]
  openPreviewDisplay: [display: PreviewNodeDisplay]
  openPreviewImage: [image: PreviewViewerImage]
}
