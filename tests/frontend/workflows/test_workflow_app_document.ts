import { computed, ref, shallowRef } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowNewAppDraft } from '@/workflows/workflow-editor/documents/useWorkflowNewAppDraft'
import {
  createWorkflowAppDocument,
  parseWorkflowAppDocumentV1,
  retargetWorkflowAppDocument,
  serializeWorkflowAppDocument,
  WORKFLOW_DOCUMENT_MAX_BYTES,
  WORKFLOW_DOCUMENT_MAX_GRAPH_ITEMS,
  WORKFLOW_DOCUMENT_MAX_JSON_DEPTH,
  WORKFLOW_DOCUMENT_MAX_JSON_VALUES,
  WORKFLOW_DOCUMENT_MAX_NODES,
  WORKFLOW_DOCUMENT_MAX_NOTES,
} from '@/workflows/workflow-editor/documents/workflow-app-document'
import { useWorkflowGraphNodeViews } from '@/workflows/workflow-editor/nodes/useWorkflowGraphNodeViews'
import { useWorkflowDocumentBuilder } from '@/workflows/workflow-editor/documents/useWorkflowDocumentBuilder'
import { useWorkflowDocumentLoader } from '@/workflows/workflow-editor/documents/useWorkflowDocumentLoader'
import { canvasSnapshotToWorkflowTemplate } from '@/workflows/workflow-editor/canvas/graph-engine/workflow-graph-conversion'
import type { WorkflowLiteGraphAdapter } from '@/workflows/workflow-editor/canvas/graph-engine/litegraph-adapter'
import type { WorkflowGraphNode, WorkflowGraphEdge, NodeDefinition } from '@/workflows/workflow-editor/types'

function fixture() {
  const app = useWorkflowNewAppDraft({ isNewApp: computed(() => true), selectedProjectId: computed(() => 'target-project'), readNodeCount: () => 0, translate: key => key }).createLocalWorkflowAppDraft()
  app.applicationDocument.application.metadata = { project_id: 'source-project', app_mode: { extension: ['preserve'] } }
  const node: WorkflowGraphNode = { node_id: 'source-node', node_type_id: 'missing.custom', enabled: true, parameters: { project_id: 'node-business-field', nested: { a: [1, 2] } }, ui_state: {}, metadata: { extension: true } }
  app.graphDocument.template.nodes = [node]
  app.graphDocument.template.notes = [{ note_id: 'n', title: 'note', content: 'content', content_format: 'markdown', rect: { x: 1, y: 2, width: 300, height: 200 }, tone: 'info', collapsed: false, locked: true, metadata: { nested: { kept: true } } }]
  app.graphDocument.template.groups = [{ group_id: 'g', name: 'group', rect: { x: 0, y: 0, width: 900, height: 900 }, enabled: true, member_node_ids: [node.node_id], member_note_ids: ['n'], membership_policy: 'full-containment', collapsed: false, locked: false, color: '#667085', metadata: {} }]
  return app
}

describe('portable Workflow document', () => {
  it('exports full current JSON without server wrappers or recursive removal of business fields', () => {
    const app = fixture()
    const doc = createWorkflowAppDocument(app.applicationDocument.application, app.graphDocument.template)
    expect(doc.application.metadata.project_id).toBeUndefined()
    expect(doc.template.nodes[0]!.parameters.project_id).toBe('node-business-field')
    expect(doc.application.template_ref).toMatchObject({ source_kind: 'embedded', source_uri: null })
    expect(parseWorkflowAppDocumentV1(JSON.parse(serializeWorkflowAppDocument(doc)))).toEqual(doc)
    doc.template.nodes[0]!.parameters.nested = null
    expect(app.graphDocument.template.nodes[0]!.parameters.nested).toEqual({ a: [1, 2] })
    expect(Object.keys(doc)).toEqual(['format_id', 'application', 'template'])
  })

  it('accepts unfinished graphs and unavailable nodes but rejects malformed references, duplicates and formats', () => {
    const app = fixture()
    const doc = createWorkflowAppDocument(app.applicationDocument.application, app.graphDocument.template)
    expect(() => parseWorkflowAppDocumentV1(doc)).not.toThrow()
    expect(() => parseWorkflowAppDocumentV1({ ...doc, format_id: 'other.v1' })).toThrow()
    doc.template.nodes.push(doc.template.nodes[0]!)
    expect(() => parseWorkflowAppDocumentV1(doc)).toThrow('duplicate')
    doc.template.nodes = []
    doc.template.groups = []
    expect(() => parseWorkflowAppDocumentV1(doc)).not.toThrow()
    doc.template.edges = [{ edge_id: 'e', source_node_id: 'missing', source_port: 'out', target_node_id: 'absent', target_port: 'in', metadata: {} }]
    expect(() => parseWorkflowAppDocumentV1(doc)).toThrow('unknown id')
  })

  it('rejects non-finite JSON numbers instead of silently changing the document', () => {
    const app = fixture()
    app.graphDocument.template.nodes[0]!.parameters.nested = { value: Infinity }
    expect(() => createWorkflowAppDocument(app.applicationDocument.application, app.graphDocument.template)).toThrow('finite number')
  })

  it('rejects oversized graph collections before constructing editor state', () => {
    const tooManyNodes = fixture()
    tooManyNodes.graphDocument.template.nodes = Array.from(
      { length: WORKFLOW_DOCUMENT_MAX_NODES + 1 },
      (_, index) => ({ ...tooManyNodes.graphDocument.template.nodes[0]!, node_id: `node-${index}` }),
    )
    expect(() => createWorkflowAppDocument(tooManyNodes.applicationDocument.application, tooManyNodes.graphDocument.template))
      .toThrow(expect.objectContaining({ kind: 'nodes' }))

    const tooManyNotes = fixture()
    tooManyNotes.graphDocument.template.notes = Array.from(
      { length: WORKFLOW_DOCUMENT_MAX_NOTES + 1 },
      (_, index) => ({ ...tooManyNotes.graphDocument.template.notes[0]!, note_id: `note-${index}` }),
    )
    expect(() => createWorkflowAppDocument(tooManyNotes.applicationDocument.application, tooManyNotes.graphDocument.template))
      .toThrow(expect.objectContaining({ kind: 'notes' }))

    const tooManyItems = fixture()
    tooManyItems.graphDocument.template.edges = Array(WORKFLOW_DOCUMENT_MAX_GRAPH_ITEMS + 1).fill(null)
    expect(() => createWorkflowAppDocument(tooManyItems.applicationDocument.application, tooManyItems.graphDocument.template))
      .toThrow(expect.objectContaining({ kind: 'graph-items' }))
  })

  it('bounds free JSON nesting and total values without recursive validation', () => {
    const buildNested = (depthLimit: number) => {
      const app = fixture()
      let cursor: Record<string, unknown> = {}
      app.graphDocument.template.nodes[0]!.parameters = cursor
      for (let depth = 0; depth < depthLimit; depth += 1) {
        const next: Record<string, unknown> = {}
        cursor.value = next
        cursor = next
      }
      return app
    }
    const atDepthLimit = buildNested(WORKFLOW_DOCUMENT_MAX_JSON_DEPTH)
    expect(() => createWorkflowAppDocument(atDepthLimit.applicationDocument.application, atDepthLimit.graphDocument.template)).not.toThrow()

    const deeplyNested = buildNested(WORKFLOW_DOCUMENT_MAX_JSON_DEPTH + 1)
    expect(() => createWorkflowAppDocument(deeplyNested.applicationDocument.application, deeplyNested.graphDocument.template))
      .toThrow(expect.objectContaining({ kind: 'json-depth' }))

    const tooManyValues = fixture()
    tooManyValues.applicationDocument.application.metadata.values = Array(WORKFLOW_DOCUMENT_MAX_JSON_VALUES).fill(null)
    expect(() => createWorkflowAppDocument(tooManyValues.applicationDocument.application, tooManyValues.graphDocument.template))
      .toThrow(expect.objectContaining({ kind: 'json-values' }))
  })

  it('rejects an export larger than the import byte limit', () => {
    const app = fixture()
    app.applicationDocument.application.description = 'x'.repeat(WORKFLOW_DOCUMENT_MAX_BYTES)
    const document = createWorkflowAppDocument(app.applicationDocument.application, app.graphDocument.template)
    expect(() => serializeWorkflowAppDocument(document)).toThrow(expect.objectContaining({ kind: 'bytes' }))
  })

  it('loads source names and configuration while retaining target App, Template and Project identity', () => {
    const source = fixture()
    const doc = createWorkflowAppDocument(source.applicationDocument.application, source.graphDocument.template)
    const current = fixture()
    current.applicationDocument.application.application_id = 'target-app'
    current.applicationDocument.application.metadata.project_id = 'target-project'
    current.graphDocument.template.template_id = 'target-template'
    current.applicationDocument.application.template_ref.template_id = 'target-template'
    doc.application.display_name = 'history name'
    const result = retargetWorkflowAppDocument(doc, { application: current.applicationDocument.application, template: current.graphDocument.template })
    expect(result.application.application_id).toBe('target-app')
    expect(result.application.display_name).toBe('history name')
    expect(result.application.metadata.project_id).toBe('target-project')
    expect(result.template.template_id).toBe('target-template')
    expect(result.application.template_ref).toEqual(current.applicationDocument.application.template_ref)
    expect(doc.template.template_id).not.toBe('target-template')
  })

  it('does not inject current node defaults or fallback layout when opening and exporting; retains real edits', () => {
    const app = fixture()
    const graphEdges = ref<WorkflowGraphEdge[]>([])
    const definition = { node_type_id: 'missing.custom', display_name: 'Custom', input_ports: [], output_ports: [], metadata: {}, config_schema: { properties: { added: { default: 99 } } } } as unknown as NodeDefinition
    const views = useWorkflowGraphNodeViews({ graphEdges, nodeCatalog: ref({ node_definitions: [definition] } as never) })
    const graphNodes = ref(views.buildGraphNodeViews(app.graphDocument.template.nodes))
    const builder = useWorkflowDocumentBuilder({ workflowApp: ref(app), graphNodes, graphEdges, graphGroups: ref(app.graphDocument.template.groups), graphNotes: ref(app.graphDocument.template.notes), templateInputs: ref([]), templateOutputs: ref([]), applicationBindingsDraft: ref([]), liteGraphAdapter: shallowRef({ exportTemplate: canvasSnapshotToWorkflowTemplate } as WorkflowLiteGraphAdapter), applyNewWorkflowTemplateSettings: t => t, buildNewWorkflowApplicationPatch: a => a, writeBoundaryPositionsToMetadata: m => m })
    expect(builder.buildCurrentTemplate()).toEqual(app.graphDocument.template)
    graphNodes.value[0]!.x += 7
    graphNodes.value[0]!.node.parameters.unsaved = true
    const exported = builder.buildCurrentTemplate()!
    expect(exported.nodes[0]!.ui_state).toEqual({ x: graphNodes.value[0]!.x })
    expect(exported.nodes[0]!.parameters.unsaved).toBe(true)
    expect(exported.nodes[0]!.parameters.added).toBeUndefined()
  })

  it('prepares replacement before resetting the old graph, and save feedback retains inputs/selection', () => {
    const app = fixture()
    const workflowApp = ref(app)
    const reset = vi.fn()
    const initializePreviewInputs = vi.fn()
    const buildViews = vi.fn(() => { throw new Error('cannot build') })
    const options = { loading: ref(false), nodeCatalog: ref(null), workflowApp, graphNodes: ref([]), graphEdges: ref([]), graphGroups: ref([]), graphNotes: ref([]), templateInputs: ref([]), templateOutputs: ref([]), applicationBindingsDraft: ref([]), liteGraphAdapter: shallowRef(null), selectedProjectId: computed(() => 'p'), isNewApp: computed(() => false), routeApplicationId: computed(() => 'a'), readLoadFailedMessage: () => 'error', clearActionMessages: vi.fn(), resetPreviewRun: reset, resetNewWorkflowAppDraft: vi.fn(), createLocalWorkflowAppDraft: () => app, initializePublicBindings: vi.fn(), initializePreviewInputs, readSelection: () => ({ nodeId: null, edgeId: null, boundaryKind: null }), setSelection: vi.fn(), restoreSelectionAfterGraphRefresh: vi.fn(), buildGraphNodeViews: buildViews, clearComplexParameterDrafts: vi.fn(), revokePreviewImageObjectUrls: vi.fn(), updateStageSize: vi.fn(), fitView: vi.fn(), setErrorMessage: vi.fn() }
    const loader = useWorkflowDocumentLoader(options)
    const before = workflowApp.value
    expect(() => loader.replaceWorkflowEditorDocument(fixture())).toThrow('cannot build')
    expect(workflowApp.value).toBe(before)
    expect(reset).not.toHaveBeenCalled()
    buildViews.mockImplementation(() => [] as never)
    loader.replaceWorkflowEditorDocument(fixture(), true)
    expect(reset).not.toHaveBeenCalled()
    expect(initializePreviewInputs).toHaveBeenCalledWith([], { preserveExisting: true })
    expect(options.restoreSelectionAfterGraphRefresh).toHaveBeenCalledOnce()
    loader.replaceWorkflowEditorDocument(fixture())
    expect(reset).toHaveBeenCalledOnce()
    expect(initializePreviewInputs).toHaveBeenLastCalledWith([], { preserveExisting: false })
  })
})
