import { afterEach, expect, it, vi } from 'vitest'
import { computed, effectScope, ref, shallowRef } from 'vue'
import { useWorkflowDocumentLoader, type WorkflowDocumentLoaderOptions } from '@/workflows/workflow-editor/documents/useWorkflowDocumentLoader'
import { getWorkflowNodeCatalog } from '@/workflows/workflow-editor/services/node-catalog.service'
import { getWorkflowApp } from '@/workflows/workflow-editor/services/workflow-app.service'

vi.mock('@/workflows/workflow-editor/services/node-catalog.service', () => ({getWorkflowNodeCatalog: vi.fn()}))
vi.mock('@/workflows/workflow-editor/services/workflow-app.service', () => ({getWorkflowApp: vi.fn()}))
vi.mock('@/workflows/workflow-editor/canvas/graph-engine/litegraph-adapter', () => ({createWorkflowLiteGraphAdapter: () => ({loadTemplate: vi.fn()})}))
const scopes: ReturnType<typeof effectScope>[] = []
afterEach(() => { scopes.splice(0).forEach(s => s.stop()); vi.resetAllMocks() })
function setup() {
  const scope = effectScope(); scopes.push(scope)
  const route = ref('old'), project = ref('p')
  const options = {
    loading: ref(false), workflowApp: ref(null), nodeCatalog: ref(null), graphNodes: ref([]), graphEdges: ref([]),
    graphGroups: ref([]), graphNotes: ref([]), templateInputs: ref([]), templateOutputs: ref([]), applicationBindingsDraft: ref([]),
    liteGraphAdapter: shallowRef(null), selectedProjectId: computed(() => project.value), routeApplicationId: computed(() => route.value), isNewApp: computed(() => false),
    readLoadFailedMessage: () => 'failed', clearActionMessages: vi.fn(), resetPreviewRun: vi.fn(), clearComplexParameterDrafts: vi.fn(),
    revokePreviewImageObjectUrls: vi.fn(), updateStageSize: vi.fn(), fitView: vi.fn(), setErrorMessage: vi.fn(),
    readSelection: () => ({}), setSelection: vi.fn(), buildGraphNodeViews: () => [], initializePublicBindings: vi.fn(),
    initializePreviewInputs: vi.fn(), resetNewWorkflowAppDraft: vi.fn(), createLocalWorkflowAppDraft: vi.fn(), restoreSelectionAfterGraphRefresh: vi.fn(),
  } as unknown as WorkflowDocumentLoaderOptions
  vi.mocked(getWorkflowNodeCatalog).mockResolvedValue({node_definitions: []} as any)
  const loader = scope.run(() => useWorkflowDocumentLoader(options))!
  return {scope, route, project, options, loader}
}
const app = (id: string) => ({ applicationDocument: {application_id: id}, graphDocument: {template: {
  nodes: [], edges: [], groups: [], notes: [], template_inputs: [], template_outputs: [],
}}, bindings: [] }) as any

it('does not install an old document or reset the new loading state after app navigation', async () => {
  const h = setup(), resolve: ((value: any) => void)[] = []
  vi.mocked(getWorkflowApp).mockImplementation(() => new Promise(r => resolve.push(r)))
  const first = h.loader.loadPage()
  await vi.waitFor(() => expect(getWorkflowApp).toHaveBeenCalledTimes(1))
  h.route.value = 'imported'
  const second = h.loader.loadPage()
  await vi.waitFor(() => expect(getWorkflowApp).toHaveBeenCalledTimes(2))
  resolve[0]!(app('old')); await first
  expect(h.options.workflowApp.value).toBe(null); expect(h.options.loading.value).toBe(true)
  resolve[1]!(app('imported')); await second
  expect(h.options.workflowApp.value?.applicationDocument.application_id).toBe('imported')
  expect(h.options.loading.value).toBe(false)
})
it.each(['project', 'dispose'])('ignores late failed catalog after %s change', async mode => {
  const h = setup()
  let reject!: (e: Error) => void
  vi.mocked(getWorkflowNodeCatalog).mockImplementation(() => new Promise((_r, e) => { reject = e }))
  const pending = h.loader.loadPage()
  if (mode === 'project') h.project.value = 'q'
  else h.scope.stop()
  reject(new Error('late')); await pending
  expect(h.options.setErrorMessage).not.toHaveBeenCalled()
  expect(getWorkflowApp).not.toHaveBeenCalled()
  expect(h.options.updateStageSize).not.toHaveBeenCalled()
})
