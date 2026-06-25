import { nextTick, type ComputedRef, type Ref, type ShallowRef } from 'vue'

import { createUniquePublicId, normalizePublicIdentifier } from '../bindings/useWorkflowPublicBindings'
import { createWorkflowLiteGraphAdapter, type WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { getWorkflowApp, type WorkflowAppDocument } from '../services/workflow-app.service'
import type {
  FlowApplicationBinding,
  WorkflowGraphEdge,
  WorkflowGraphInput,
  WorkflowGraphNode,
  WorkflowGraphOutput,
  WorkflowNodeCatalogResponse,
} from '../types'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowSelectionState } from '../selection/useWorkflowSelectionState'

export interface WorkflowDocumentLoaderOptions {
  loading: Ref<boolean>
  nodeCatalog: Ref<WorkflowNodeCatalogResponse | null>
  workflowApp: Ref<WorkflowAppDocument | null>
  graphNodes: Ref<WorkflowGraphNodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  templateInputs: Ref<WorkflowGraphInput[]>
  templateOutputs: Ref<WorkflowGraphOutput[]>
  applicationBindingsDraft: Ref<FlowApplicationBinding[]>
  liteGraphAdapter: ShallowRef<WorkflowLiteGraphAdapter | null>
  selectedProjectId: ComputedRef<string>
  isNewApp: ComputedRef<boolean>
  routeApplicationId: ComputedRef<string>
  readLoadFailedMessage: () => string
  clearActionMessages: () => void
  resetPreviewRun: () => void
  resetNewWorkflowAppDraft: () => void
  createLocalWorkflowAppDraft: () => WorkflowAppDocument
  initializePublicBindings: (appDocument: WorkflowAppDocument) => void
  initializePreviewInputs: (bindings: FlowApplicationBinding[]) => void
  normalizeLoadedRequestImageInputBindings: () => void
  readSelection: () => WorkflowSelectionState
  setSelection: (selection: WorkflowSelectionState) => void
  restoreSelectionAfterGraphRefresh: (previousSelection: WorkflowSelectionState, fallbackNodeId: string | null) => void
  buildGraphNodeViews: (nodes: WorkflowGraphNode[]) => WorkflowGraphNodeView[]
  clearComplexParameterDrafts: () => void
  revokePreviewImageObjectUrls: () => void
  updateStageSize: () => void
  fitView: () => void
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowDocumentLoader(options: WorkflowDocumentLoaderOptions) {
  function initializeWorkflowAppDrafts(appDocument: WorkflowAppDocument): void {
    options.templateInputs.value = appDocument.graphDocument.template.template_inputs.map((input) => ({ ...input, metadata: { ...input.metadata } }))
    options.templateOutputs.value = appDocument.graphDocument.template.template_outputs.map((output) => ({ ...output, metadata: { ...output.metadata } }))
    options.initializePublicBindings(appDocument)
    normalizeLoadedHttpResponseOutputIds(appDocument.graphDocument.template.nodes)
    options.normalizeLoadedRequestImageInputBindings()
    options.initializePreviewInputs(options.applicationBindingsDraft.value)
  }

  async function refreshSavedWorkflowApp(applicationId: string): Promise<void> {
    const previousSelection = options.readSelection()
    const refreshedApp = await getWorkflowApp(options.selectedProjectId.value, applicationId)
    options.workflowApp.value = refreshedApp
    initializeWorkflowAppDrafts(refreshedApp)
    options.clearComplexParameterDrafts()
    options.liteGraphAdapter.value?.loadTemplate(refreshedApp.graphDocument.template)
    options.graphEdges.value = cloneGraphEdges(refreshedApp.graphDocument.template.edges)
    options.graphNodes.value = options.buildGraphNodeViews(refreshedApp.graphDocument.template.nodes)
    options.restoreSelectionAfterGraphRefresh(previousSelection, options.graphNodes.value[0]?.node.node_id ?? null)
  }

  async function loadPage(): Promise<void> {
    options.loading.value = true
    options.clearActionMessages()
    options.resetPreviewRun()
    options.clearComplexParameterDrafts()
    options.revokePreviewImageObjectUrls()
    try {
      options.nodeCatalog.value = await getWorkflowNodeCatalog()
      options.liteGraphAdapter.value = createWorkflowLiteGraphAdapter({ nodeDefinitions: options.nodeCatalog.value.node_definitions })
      if (!options.isNewApp.value && options.routeApplicationId.value) {
        await loadSavedWorkflowApp()
      } else {
        loadNewWorkflowAppDraft()
      }
      await nextTick()
      options.updateStageSize()
      if (options.graphNodes.value.length > 0) {
        options.fitView()
      }
    } catch (error) {
      options.setErrorMessage(error instanceof Error ? error.message : options.readLoadFailedMessage())
    } finally {
      options.loading.value = false
    }
  }

  async function loadSavedWorkflowApp(): Promise<void> {
    const loadedApp = await getWorkflowApp(options.selectedProjectId.value, options.routeApplicationId.value)
    options.workflowApp.value = loadedApp
    initializeWorkflowAppDrafts(loadedApp)
    options.liteGraphAdapter.value?.loadTemplate(loadedApp.graphDocument.template)
    options.graphEdges.value = cloneGraphEdges(loadedApp.graphDocument.template.edges)
    options.graphNodes.value = options.buildGraphNodeViews(loadedApp.graphDocument.template.nodes)
    options.setSelection({ nodeId: options.graphNodes.value[0]?.node.node_id ?? null, edgeId: null, boundaryKind: null })
  }

  function loadNewWorkflowAppDraft(): void {
    options.resetNewWorkflowAppDraft()
    const draftApp = options.createLocalWorkflowAppDraft()
    options.workflowApp.value = draftApp
    initializeWorkflowAppDrafts(draftApp)
    options.liteGraphAdapter.value?.loadTemplate(draftApp.graphDocument.template)
    options.graphEdges.value = []
    options.graphNodes.value = []
    options.setSelection({ nodeId: null, edgeId: null, boundaryKind: null })
  }

  function normalizeLoadedHttpResponseOutputIds(nodes: WorkflowGraphNode[]): void {
    const nodeTypeById = new Map(nodes.map((node) => [node.node_id, node.node_type_id]))
    for (const output of options.templateOutputs.value) {
      if (nodeTypeById.get(output.source_node_id) !== 'core.output.http-response') continue
      if (output.source_port !== 'response') continue
      const legacyOutputId = normalizePublicIdentifier(`${output.source_node_id}_${output.source_port}`, output.output_id)
      if (output.output_id !== legacyOutputId) continue
      const existingIds = new Set([
        ...options.templateOutputs.value.filter((item) => item !== output).map((item) => item.output_id),
        ...options.applicationBindingsDraft.value
          .filter((binding) => binding.template_port_id !== output.output_id && binding.binding_id !== output.output_id)
          .map((binding) => binding.binding_id),
      ])
      const nextOutputId = createUniquePublicId(output.source_node_id, existingIds)
      if (nextOutputId === output.output_id) continue
      renameHttpResponseOutput(output, nextOutputId)
    }
  }

  function renameHttpResponseOutput(output: WorkflowGraphOutput, nextOutputId: string): void {
    const previousOutputId = output.output_id
    output.output_id = nextOutputId
    for (const binding of options.applicationBindingsDraft.value) {
      if (binding.direction !== 'output' || binding.template_port_id !== previousOutputId) continue
      binding.template_port_id = nextOutputId
      if (binding.binding_id === previousOutputId) binding.binding_id = nextOutputId
    }
  }

  return {
    initializeWorkflowAppDrafts,
    refreshSavedWorkflowApp,
    loadPage,
  }
}

function cloneGraphEdges(edges: WorkflowGraphEdge[]): WorkflowGraphEdge[] {
  return edges.map((edge) => ({ ...edge, metadata: { ...edge.metadata } }))
}
