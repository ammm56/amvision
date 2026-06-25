import type { ComputedRef, Ref } from 'vue'

import type { WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import type {
  FlowApplication,
  NodeDefinition,
  NodePortDefinition,
  WorkflowGraphEdge,
  WorkflowGraphTemplate,
} from '../types'

export interface WorkflowPreflightNodeView {
  node: {
    node_id: string
    node_type_id: string
  }
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

export interface WorkflowValidationIssue {
  message: string
  nodeId?: string
  edgeId?: string
  boundaryKind?: WorkflowBoundaryKind
  bindingId?: string
}

export interface WorkflowValidationSelection {
  nodeId: string | null
  edgeId: string | null
  boundaryKind: WorkflowBoundaryKind | null
}

export interface WorkflowPreflightOptions<NodeView extends WorkflowPreflightNodeView> {
  graphNodes: Ref<NodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  nodeDefinitionsById: ComputedRef<Map<string, NodeDefinition>>
  portsCanConnect: (sourcePort: NodePortDefinition, targetPort: NodePortDefinition) => boolean
  focusGraphNode: (nodeId: string) => void
  setSelection: (selection: WorkflowValidationSelection) => void
  clearTransientUi: () => void
  setErrorMessage: (message: string | null) => void
  setStatusMessage: (message: string | null) => void
}

export function useWorkflowPreflight<NodeView extends WorkflowPreflightNodeView>(options: WorkflowPreflightOptions<NodeView>) {
  function runWorkflowPreflight(template: WorkflowGraphTemplate, application: FlowApplication): WorkflowValidationIssue | null {
    if (template.nodes.length === 0) return { message: '图至少需要一个节点。' }
    const duplicateNodeId = findDuplicateValue(template.nodes.map((node) => node.node_id))
    if (duplicateNodeId) return { message: `节点 id 重复：${duplicateNodeId}`, nodeId: duplicateNodeId }
    const duplicateEdgeId = findDuplicateValue(template.edges.map((edge) => edge.edge_id))
    if (duplicateEdgeId) return { message: `连线 id 重复：${duplicateEdgeId}`, edgeId: duplicateEdgeId }
    const duplicateInputId = findDuplicateValue(template.template_inputs.map((input) => input.input_id))
    if (duplicateInputId) return { message: `应用输入 id 重复：${duplicateInputId}`, boundaryKind: 'entry', bindingId: duplicateInputId }
    const duplicateOutputId = findDuplicateValue(template.template_outputs.map((output) => output.output_id))
    if (duplicateOutputId) return { message: `应用输出 id 重复：${duplicateOutputId}`, boundaryKind: 'result', bindingId: duplicateOutputId }

    const nodeViewsById = new Map(options.graphNodes.value.map((node) => [node.node.node_id, node]))
    const inputUsage = new Map<string, string[]>()
    for (const node of template.nodes) {
      const graphNode = nodeViewsById.get(node.node_id)
      if (!graphNode) return { message: `节点 ${node.node_id} 没有画布视图，请刷新后重试。`, nodeId: node.node_id }
      if (!options.nodeDefinitionsById.value.has(node.node_type_id)) return { message: `节点 ${node.node_id} 引用了不可用的 Node type：${node.node_type_id}`, nodeId: node.node_id }
    }

    for (const edge of template.edges) {
      const sourceNode = nodeViewsById.get(edge.source_node_id)
      const targetNode = nodeViewsById.get(edge.target_node_id)
      if (!sourceNode) return { message: `连线 ${edge.edge_id} 引用了不存在的源节点：${edge.source_node_id}`, edgeId: edge.edge_id }
      if (!targetNode) return { message: `连线 ${edge.edge_id} 引用了不存在的目标节点：${edge.target_node_id}`, edgeId: edge.edge_id }
      const sourcePort = sourceNode.outputs.find((port) => port.name === edge.source_port)
      const targetPort = targetNode.inputs.find((port) => port.name === edge.target_port)
      if (!sourcePort) return { message: `连线 ${edge.edge_id} 引用了不存在的源端口：${edge.source_node_id}.${edge.source_port}`, nodeId: edge.source_node_id, edgeId: edge.edge_id }
      if (!targetPort) return { message: `连线 ${edge.edge_id} 引用了不存在的目标端口：${edge.target_node_id}.${edge.target_port}`, nodeId: edge.target_node_id, edgeId: edge.edge_id }
      if (!options.portsCanConnect(sourcePort, targetPort)) return { message: `连线 ${edge.edge_id} 的 payload type 不匹配：${sourcePort.payload_type_id || 'unknown'} -> ${targetPort.payload_type_id || 'unknown'}`, edgeId: edge.edge_id }
      const issue = registerInputUsage(inputUsage, targetNode, targetPort, `连线 ${edge.edge_id}`)
      if (issue) return { ...issue, edgeId: edge.edge_id }
    }

    for (const input of template.template_inputs) {
      const targetNode = nodeViewsById.get(input.target_node_id)
      if (!targetNode) return { message: `应用输入 ${input.input_id} 引用了不存在的目标节点：${input.target_node_id}`, boundaryKind: 'entry', bindingId: input.input_id }
      const targetPort = targetNode.inputs.find((port) => port.name === input.target_port)
      if (!targetPort) return { message: `应用输入 ${input.input_id} 引用了不存在的目标端口：${input.target_node_id}.${input.target_port}`, nodeId: input.target_node_id, boundaryKind: 'entry', bindingId: input.input_id }
      if (input.payload_type_id !== targetPort.payload_type_id) return { message: `应用输入 ${input.input_id} 的 payload type 与目标端口不匹配：${input.payload_type_id || 'unknown'} -> ${targetPort.payload_type_id || 'unknown'}`, nodeId: input.target_node_id, boundaryKind: 'entry', bindingId: input.input_id }
      const issue = registerInputUsage(inputUsage, targetNode, targetPort, `应用输入 ${input.input_id}`)
      if (issue) return { ...issue, nodeId: input.target_node_id, boundaryKind: 'entry', bindingId: input.input_id }
    }

    for (const output of template.template_outputs) {
      const sourceNode = nodeViewsById.get(output.source_node_id)
      if (!sourceNode) return { message: `应用输出 ${output.output_id} 引用了不存在的源节点：${output.source_node_id}`, boundaryKind: 'result', bindingId: output.output_id }
      const sourcePort = sourceNode.outputs.find((port) => port.name === output.source_port)
      if (!sourcePort) return { message: `应用输出 ${output.output_id} 引用了不存在的源端口：${output.source_node_id}.${output.source_port}`, nodeId: output.source_node_id, boundaryKind: 'result', bindingId: output.output_id }
      if (output.payload_type_id !== sourcePort.payload_type_id) return { message: `应用输出 ${output.output_id} 的 payload type 与源端口不匹配：${sourcePort.payload_type_id || 'unknown'} -> ${output.payload_type_id || 'unknown'}`, nodeId: output.source_node_id, boundaryKind: 'result', bindingId: output.output_id }
    }

    if (application.template_ref.template_id !== template.template_id) return { message: `应用引用的图 id 与当前图不一致：${application.template_ref.template_id} / ${template.template_id}` }
    if (application.template_ref.template_version !== template.template_version) return { message: `应用引用的图版本与当前图不一致：${application.template_ref.template_version} / ${template.template_version}` }

    const duplicateBindingId = findDuplicateValue(application.bindings.map((binding) => binding.binding_id))
    if (duplicateBindingId) return { message: `公开接口 id 重复：${duplicateBindingId}`, boundaryKind: findBindingBoundaryKind(application, duplicateBindingId), bindingId: duplicateBindingId }

    const templateInputIds = new Set(template.template_inputs.map((input) => input.input_id))
    const templateOutputIds = new Set(template.template_outputs.map((output) => output.output_id))
    const inputBindingCounts = new Map<string, number>()
    const outputBindingCounts = new Map<string, number>()
    for (const binding of application.bindings) {
      const boundaryKind = binding.direction === 'input' ? 'entry' : 'result'
      if (!binding.binding_id.trim()) return { message: '公开接口 id 不能为空。', boundaryKind, bindingId: binding.binding_id }
      if (!binding.template_port_id.trim()) return { message: `公开接口 ${binding.binding_id} 缺少 template port id。`, boundaryKind, bindingId: binding.binding_id }
      if (!binding.binding_kind.trim()) return { message: `公开接口 ${binding.binding_id} 缺少 binding kind。`, boundaryKind, bindingId: binding.binding_id }
      if (binding.direction === 'input') {
        if (!templateInputIds.has(binding.template_port_id)) return { message: `输入绑定 ${binding.binding_id} 引用了不存在的应用输入：${binding.template_port_id}`, boundaryKind, bindingId: binding.binding_id }
        const templateInput = template.template_inputs.find((input) => input.input_id === binding.template_port_id)
        if (templateInput?.required && !binding.required) return { message: `输入绑定 ${binding.binding_id} 不能把必填应用输入标记为可选。`, boundaryKind, bindingId: binding.binding_id }
        inputBindingCounts.set(binding.template_port_id, (inputBindingCounts.get(binding.template_port_id) ?? 0) + 1)
        if ((inputBindingCounts.get(binding.template_port_id) ?? 0) > 1) return { message: `应用输入 ${binding.template_port_id} 只能绑定一个输入端点。`, boundaryKind, bindingId: binding.binding_id }
        continue
      }
      if (!templateOutputIds.has(binding.template_port_id)) return { message: `输出绑定 ${binding.binding_id} 引用了不存在的应用输出：${binding.template_port_id}`, boundaryKind, bindingId: binding.binding_id }
      outputBindingCounts.set(binding.template_port_id, (outputBindingCounts.get(binding.template_port_id) ?? 0) + 1)
    }

    for (const input of template.template_inputs) {
      if (!inputBindingCounts.has(input.input_id)) return { message: `应用输入 ${input.input_id} 缺少输入绑定。`, boundaryKind: 'entry', bindingId: input.input_id }
    }
    for (const output of template.template_outputs) {
      if (!outputBindingCounts.has(output.output_id)) return { message: `应用输出 ${output.output_id} 缺少输出绑定。`, boundaryKind: 'result', bindingId: output.output_id }
    }
    return null
  }

  function applyWorkflowValidationIssue(issue: WorkflowValidationIssue): void {
    options.setErrorMessage(issue.message)
    options.setStatusMessage(issue.bindingId ? `检查公开接口 ${issue.bindingId}` : null)
    options.clearTransientUi()
    if (issue.edgeId && options.graphEdges.value.some((edge) => edge.edge_id === issue.edgeId)) {
      options.setSelection({ edgeId: issue.edgeId, nodeId: null, boundaryKind: null })
      return
    }
    if (issue.nodeId && options.graphNodes.value.some((node) => node.node.node_id === issue.nodeId)) {
      options.focusGraphNode(issue.nodeId)
      return
    }
    if (issue.boundaryKind) {
      options.setSelection({ edgeId: null, nodeId: null, boundaryKind: issue.boundaryKind })
    }
  }

  return {
    runWorkflowPreflight,
    applyWorkflowValidationIssue,
  }
}

function registerInputUsage<NodeView extends WorkflowPreflightNodeView>(inputUsage: Map<string, string[]>, node: NodeView, port: NodePortDefinition, sourceLabel: string): WorkflowValidationIssue | null {
  const inputKey = `${node.node.node_id}.${port.name}`
  const sources = inputUsage.get(inputKey) ?? []
  sources.push(sourceLabel)
  inputUsage.set(inputKey, sources)
  if (sources.length > 1 && !port.multiple) {
    return { message: `输入端口 ${inputKey} 不能同时接收多个来源：${sources.join('、')}`, nodeId: node.node.node_id }
  }
  return null
}

function findDuplicateValue(values: string[]): string | null {
  const seen = new Set<string>()
  for (const value of values) {
    if (seen.has(value)) return value
    seen.add(value)
  }
  return null
}

function findBindingBoundaryKind(application: FlowApplication, bindingId: string): WorkflowBoundaryKind | undefined {
  const binding = application.bindings.find((item) => item.binding_id === bindingId)
  if (!binding) return undefined
  return binding.direction === 'input' ? 'entry' : 'result'
}
