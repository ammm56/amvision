import { computed, ref, type Ref } from 'vue'

import type {
  FlowApplicationBinding,
  NodePortDefinition,
  WorkflowGraphInput,
  WorkflowGraphOutput,
  WorkflowJsonObject,
} from '../types'

export type WorkflowBoundaryKind = 'entry' | 'result'

export interface WorkflowBoundaryPosition {
  x: number
  y: number
}

export interface WorkflowPublicBindingSelectOption {
  label: string
  value: string
}

export interface WorkflowPublicBindingNodeLike {
  node: {
    node_id: string
    node_type_id: string
  }
}

export interface WorkflowPublicBindingDocument {
  applicationDocument: {
    application: {
      bindings: FlowApplicationBinding[]
      metadata: WorkflowJsonObject
    }
  }
}

export interface WorkflowPublicBindingsOptions {
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  renamePreviewInputState: (oldBindingId: string, nextBindingId: string, binding: FlowApplicationBinding) => void
  removePreviewInputState: (bindingId: string) => void
}

const workflowGraphEditorMetadataKey = 'workflow_graph_editor'
const boundaryPositionsMetadataKey = 'boundary_positions'
const inputBindingKindOptions = ['api-request', 'trigger-source-input']
const outputBindingKindOptions = ['http-response', 'zeromq-publish']

function isJsonObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function readBoundaryPosition(value: unknown): WorkflowBoundaryPosition | null {
  if (!isJsonObject(value)) return null
  const x = readNumber(value.x)
  const y = readNumber(value.y)
  return x === null || y === null ? null : { x, y }
}

export function normalizePublicIdentifier(value: string, fallback: string): string {
  return value.trim().replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || fallback
}

export function createUniquePublicId(baseValue: string, existingIds: Set<string>): string {
  const baseId = normalizePublicIdentifier(baseValue, 'public_port')
  let candidateId = baseId
  let suffix = 1
  while (existingIds.has(candidateId)) {
    suffix += 1
    candidateId = `${baseId}_${suffix}`
  }
  return candidateId
}

export function buildPublicPortMetadata(node: WorkflowPublicBindingNodeLike, port: NodePortDefinition): WorkflowJsonObject {
  return {
    payload_type_id: port.payload_type_id,
    display_name: port.display_name || port.name,
    node_id: node.node.node_id,
    node_type_id: node.node.node_type_id,
    port_name: port.name,
    source: 'workflow-graph-editor',
  }
}

export function useWorkflowPublicBindings(options: WorkflowPublicBindingsOptions) {
  const applicationBindingsDraft = ref<FlowApplicationBinding[]>([])
  const boundaryPositions = ref<Partial<Record<WorkflowBoundaryKind, WorkflowBoundaryPosition>>>({})

  const applicationBindings = computed(() => applicationBindingsDraft.value)
  const appInputBindings = computed(() => applicationBindings.value.filter((binding) => binding.direction === 'input'))
  const appOutputBindings = computed(() => applicationBindings.value.filter((binding) => binding.direction === 'output'))
  const templateInputById = computed(() => new Map(options.templateInputs.value.map((input) => [input.input_id, input])))
  const templateOutputById = computed(() => new Map(options.templateOutputs.value.map((output) => [output.output_id, output])))

  function initializePublicBindings(appDocument: WorkflowPublicBindingDocument): void {
    applicationBindingsDraft.value = appDocument.applicationDocument.application.bindings.map((binding: FlowApplicationBinding) => ({
      ...binding,
      config: { ...binding.config },
      metadata: { ...binding.metadata },
    }))
    boundaryPositions.value = readBoundaryPositionsFromMetadata(appDocument.applicationDocument.application.metadata)
  }

  function readBoundaryPositionsFromMetadata(metadata: WorkflowJsonObject): Partial<Record<WorkflowBoundaryKind, WorkflowBoundaryPosition>> {
    const editorMetadata = metadata[workflowGraphEditorMetadataKey]
    if (!isJsonObject(editorMetadata)) return {}
    const rawPositions = editorMetadata[boundaryPositionsMetadataKey]
    if (!isJsonObject(rawPositions)) return {}
    const entryPosition = readBoundaryPosition(rawPositions.entry)
    const resultPosition = readBoundaryPosition(rawPositions.result)
    return {
      ...(entryPosition ? { entry: entryPosition } : {}),
      ...(resultPosition ? { result: resultPosition } : {}),
    }
  }

  function writeBoundaryPositionsToMetadata(metadata: WorkflowJsonObject): WorkflowJsonObject {
    const nextMetadata: WorkflowJsonObject = { ...metadata }
    const editorMetadataValue = nextMetadata[workflowGraphEditorMetadataKey]
    const editorMetadata: WorkflowJsonObject = isJsonObject(editorMetadataValue) ? { ...editorMetadataValue } : {}
    const serializedPositions: WorkflowJsonObject = {}
    for (const kind of ['entry', 'result'] as WorkflowBoundaryKind[]) {
      const position = boundaryPositions.value[kind]
      if (position) serializedPositions[kind] = { x: position.x, y: position.y }
    }
    if (Object.keys(serializedPositions).length > 0) {
      editorMetadata[boundaryPositionsMetadataKey] = serializedPositions
    } else {
      delete editorMetadata[boundaryPositionsMetadataKey]
    }
    if (Object.keys(editorMetadata).length > 0) {
      nextMetadata[workflowGraphEditorMetadataKey] = editorMetadata
    } else {
      delete nextMetadata[workflowGraphEditorMetadataKey]
    }
    return nextMetadata
  }

  function readTemplatePortForBinding(binding: FlowApplicationBinding): WorkflowGraphInput | WorkflowGraphOutput | null {
    return binding.direction === 'input'
      ? templateInputById.value.get(binding.template_port_id) ?? null
      : templateOutputById.value.get(binding.template_port_id) ?? null
  }

  function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
    const templatePort = readTemplatePortForBinding(binding)
    if (templatePort?.payload_type_id) return templatePort.payload_type_id
    const configPayloadType = binding.config.payload_type_id
    if (typeof configPayloadType === 'string' && configPayloadType.trim()) return configPayloadType.trim()
    const metadataPayloadType = binding.metadata.payload_type_id
    if (typeof metadataPayloadType === 'string' && metadataPayloadType.trim()) return metadataPayloadType.trim()
    return ''
  }

  function bindingDisplayName(binding: FlowApplicationBinding): string {
    const templatePort = readTemplatePortForBinding(binding)
    if (templatePort && 'display_name' in templatePort) return templatePort.display_name
    const metadataDisplayName = binding.metadata.display_name
    return typeof metadataDisplayName === 'string' ? metadataDisplayName : binding.binding_id
  }

  function bindingKindOptions(binding: FlowApplicationBinding): string[] {
    const defaultOptions = binding.direction === 'input' ? inputBindingKindOptions : outputBindingKindOptions
    return defaultOptions.includes(binding.binding_kind) ? defaultOptions : [binding.binding_kind, ...defaultOptions].filter(Boolean)
  }

  function bindingKindSelectOptions(binding: FlowApplicationBinding): WorkflowPublicBindingSelectOption[] {
    return bindingKindOptions(binding).map((option) => ({ label: option, value: option }))
  }

  function renameApplicationBinding(binding: FlowApplicationBinding, nextBindingId: string): boolean {
    const oldBindingId = binding.binding_id
    const existingBindingIds = new Set(applicationBindingsDraft.value.filter((item) => item !== binding).map((item) => item.binding_id))
    if (existingBindingIds.has(nextBindingId)) return false
    const templatePort = readTemplatePortForBinding(binding)
    if (binding.direction === 'input' && templatePort && 'input_id' in templatePort) {
      templatePort.input_id = nextBindingId
    }
    if (binding.direction === 'output' && templatePort && 'output_id' in templatePort) {
      templatePort.output_id = nextBindingId
    }
    binding.binding_id = nextBindingId
    binding.template_port_id = nextBindingId
    binding.config = { ...binding.config, payload_type_id: getBindingPayloadTypeId(binding) }
    if (binding.direction === 'input' && oldBindingId !== nextBindingId) {
      options.renamePreviewInputState(oldBindingId, nextBindingId, binding)
    }
    return true
  }

  function setBindingDisplayName(binding: FlowApplicationBinding, nextDisplayName: string): void {
    const templatePort = readTemplatePortForBinding(binding)
    if (templatePort && 'display_name' in templatePort) templatePort.display_name = nextDisplayName
    binding.metadata = { ...binding.metadata, display_name: nextDisplayName }
  }

  function updateApplicationBindingRequired(binding: FlowApplicationBinding, required: boolean): void {
    binding.required = required
    const templateInput = binding.direction === 'input' ? templateInputById.value.get(binding.template_port_id) : null
    if (templateInput) templateInput.required = required
  }

  function deleteApplicationBinding(binding: FlowApplicationBinding): WorkflowBoundaryKind {
    applicationBindingsDraft.value = applicationBindingsDraft.value.filter((item) => item !== binding)
    if (binding.direction === 'input') {
      options.templateInputs.value = options.templateInputs.value.filter((input) => input.input_id !== binding.template_port_id)
      options.removePreviewInputState(binding.binding_id)
      return 'entry'
    }
    options.templateOutputs.value = options.templateOutputs.value.filter((output) => output.output_id !== binding.template_port_id)
    return 'result'
  }

  function resetBoundaryPosition(boundaryKind: WorkflowBoundaryKind): void {
    const nextPositions = { ...boundaryPositions.value }
    delete nextPositions[boundaryKind]
    boundaryPositions.value = nextPositions
  }

  return {
    applicationBindingsDraft,
    boundaryPositions,
    applicationBindings,
    appInputBindings,
    appOutputBindings,
    templateInputById,
    templateOutputById,
    initializePublicBindings,
    readBoundaryPositionsFromMetadata,
    writeBoundaryPositionsToMetadata,
    readTemplatePortForBinding,
    getBindingPayloadTypeId,
    bindingDisplayName,
    bindingKindSelectOptions,
    renameApplicationBinding,
    setBindingDisplayName,
    updateApplicationBindingRequired,
    deleteApplicationBinding,
    resetBoundaryPosition,
  }
}
