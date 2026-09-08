import { nextTick, type ComputedRef, type Ref, type ShallowRef } from 'vue'

import { cloneWorkflowJson } from './workflow-app-document'
import { createWorkflowLiteGraphAdapter, type WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { getWorkflowApp, type WorkflowAppDocument } from '../services/workflow-app.service'
import type {
  FlowApplicationBinding,
  WorkflowGraphEdge,
  WorkflowGraphGroup,
  WorkflowGraphInput,
  WorkflowGraphNode,
  WorkflowGraphNote,
  WorkflowGraphOutput,
  WorkflowNodeCatalogResponse,
} from '../types'
import type { WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import type { WorkflowSelectionState } from '../selection/useWorkflowSelectionState'

export interface WorkflowDocumentLoaderOptions {
  onDocumentReplaced?: (preserveExisting: boolean) => void
  loading: Ref<boolean>
  nodeCatalog: Ref<WorkflowNodeCatalogResponse | null>
  workflowApp: Ref<WorkflowAppDocument | null>
  graphNodes: Ref<WorkflowGraphNodeView[]>
  graphEdges: Ref<WorkflowGraphEdge[]>
  graphGroups: Ref<WorkflowGraphGroup[]>
  graphNotes: Ref<WorkflowGraphNote[]>
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
  initializePreviewInputs: (bindings: FlowApplicationBinding[], options?: { preserveExisting?: boolean }) => void
  readSelection: () => WorkflowSelectionState
  setSelection: (selection: WorkflowSelectionState) => void
  restoreSelectionAfterGraphRefresh: (previousSelection: WorkflowSelectionState, fallbackNodeId: string | null) => void
  buildGraphNodeViews: (nodes: WorkflowGraphNode[], edges?: WorkflowGraphEdge[]) => WorkflowGraphNodeView[]
  clearComplexParameterDrafts: () => void
  revokePreviewImageObjectUrls: () => void
  updateStageSize: () => void
  fitView: () => void
  setErrorMessage: (message: string | null) => void
}

export function useWorkflowDocumentLoader(options: WorkflowDocumentLoaderOptions) {
  function initializeWorkflowAppDrafts(appDocument: WorkflowAppDocument, draftOptions: { preservePreviewInputs?: boolean } = {}): void {
    options.templateInputs.value = cloneWorkflowJson(appDocument.graphDocument.template.template_inputs)
    options.templateOutputs.value = cloneWorkflowJson(appDocument.graphDocument.template.template_outputs)
    options.initializePublicBindings(appDocument)
    options.initializePreviewInputs(options.applicationBindingsDraft.value, { preserveExisting: draftOptions.preservePreviewInputs === true })
  }

  /** 所有来源共用替换入口；准备完成后才替换编辑状态。保存回读保留选择和输入。 */
  function replaceWorkflowEditorDocument(source: WorkflowAppDocument, preserveExisting = false): void {
    const app = cloneWorkflowJson(source)
    const template = app.graphDocument.template
    const nodes = options.buildGraphNodeViews(template.nodes, template.edges)
    const previousSelection = options.readSelection()
    options.liteGraphAdapter.value?.loadTemplate(template)
    if (!preserveExisting) {
      options.resetPreviewRun()
      options.revokePreviewImageObjectUrls()
    }
    options.workflowApp.value = app
    options.graphEdges.value = cloneWorkflowJson(template.edges)
    options.graphGroups.value = cloneWorkflowJson(template.groups)
    options.graphNotes.value = cloneWorkflowJson(template.notes ?? [])
    options.graphNodes.value = nodes
    initializeWorkflowAppDrafts(app, { preservePreviewInputs: preserveExisting })
    options.clearComplexParameterDrafts()
    options.onDocumentReplaced?.(preserveExisting)
    if (preserveExisting) options.restoreSelectionAfterGraphRefresh(previousSelection, nodes[0]?.node.node_id ?? null)
    else options.setSelection({ nodeId: nodes[0]?.node.node_id ?? null, edgeId: null, boundaryKind: null })
  }

  async function refreshSavedWorkflowApp(applicationId: string): Promise<void> {
    const refreshedApp = await getWorkflowApp(options.selectedProjectId.value, applicationId)
    replaceWorkflowEditorDocument(refreshedApp, true)
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
    replaceWorkflowEditorDocument(loadedApp)
  }

  function loadNewWorkflowAppDraft(): void {
    options.resetNewWorkflowAppDraft()
    replaceWorkflowEditorDocument(options.createLocalWorkflowAppDraft())
  }

  return {
    initializeWorkflowAppDrafts,
    replaceWorkflowEditorDocument,
    refreshSavedWorkflowApp,
    loadPage,
  }
}
