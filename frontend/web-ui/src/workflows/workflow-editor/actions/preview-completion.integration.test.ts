import { computed, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkflowEditorActions } from './useWorkflowEditorActions'
import { useWorkflowSaveRunOrchestration } from './useWorkflowSaveRunOrchestration'
import { useWorkflowSaveRunFeedback } from './useWorkflowSaveRunFeedback'
import { useWorkflowPreviewDisplays } from '../preview/useWorkflowPreviewDisplays'
import type { WorkflowPreviewRun } from '../types'

const io = vi.hoisted(() => ({ create: vi.fn(), get: vi.fn(), stream: vi.fn(), start: vi.fn(), stop: vi.fn() }))
vi.mock('@/platform/i18n', () => ({ translate: (key: string) => key }))
vi.mock('../services/workflow-template.service', () => ({ validateWorkflowTemplate: vi.fn() }))
vi.mock('../services/workflow-application.service', () => ({ validateWorkflowApplication: vi.fn() }))
vi.mock('../services/workflow-app.service', () => ({ saveWorkflowApp: vi.fn() }))
vi.mock('../services/workflow-runtime.service', () => ({
  createWorkflowPreviewRun: io.create, getWorkflowPreviewRun: io.get,
  cancelWorkflowPreviewRun: vi.fn(), readProjectObjectContentBlob: vi.fn(), readWorkflowPreviewRunArtifactBlob: vi.fn(),
}))
vi.mock('../composables/useWorkflowResourceStream', () => ({ useWorkflowResourceStream: io.stream }))
vi.mock('../preview/previewDisplayResults', () => ({ loadPreviewDisplayResult: async () => ({ run: await io.get(), errors: [] }) }))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  io.stream.mockReturnValue({ start: io.start, stop: io.stop, refreshNow: vi.fn() })
})

it('renders image and false value after async completion through the editor feedback pipeline', async () => {
  const running = { preview_run_id: 'run-1', project_id: 'p', application_id: 'app', state: 'running', node_records: [] } as unknown as WorkflowPreviewRun
  io.create.mockResolvedValue(running)
  const displays = useWorkflowPreviewDisplays()
  const actions = useWorkflowEditorActions()
  const feedback = useWorkflowSaveRunFeedback({
    replaceRouteWithSavedApp: vi.fn(), refreshSavedWorkflowApp: vi.fn(), resetPreviewRun: actions.resetPreviewRun,
    revokePreviewImageObjectUrls: displays.revokePreviewImageObjectUrls, refreshPreviewNodeDisplays: displays.refreshPreviewNodeDisplays,
    focusGraphNode: vi.fn(), setActionError: actions.setActionError, setActionStatus: actions.setActionStatus,
  })
  actions.setPreviewFeedback(feedback.applyPreviewRunFeedback)
  const template = { nodes: [{ node_id: 'image', node_type_id: 'core.io.image-preview', parameters: {} }], template_inputs: [], edges: [] }
  const orchestration = useWorkflowSaveRunOrchestration({
    workflowApp: ref({}), isNewApp: computed(() => false), selectedProjectId: computed(() => 'p'),
    readNewWorkflowAppSaveBlocker: () => null, buildCurrentTemplate: () => template, buildCurrentApplication: () => ({ application_id: 'app', bindings: [] }),
    runWorkflowPreflight: () => null, applyWorkflowValidationIssue: vi.fn(), buildPreviewInputBindings: async () => ({ inputBindings: {}, fileUploads: [] }),
    saveWorkflowDocument: actions.saveWorkflowDocument, runWorkflowPreview: actions.runWorkflowPreview,
    applyWorkflowSaveFeedback: feedback.applyWorkflowSaveFeedback, applyPreviewRunFeedback: feedback.applyPreviewRunFeedback,
    clearActionMessages: actions.clearActionMessages, revokePreviewImageObjectUrls: displays.revokePreviewImageObjectUrls,
    setActionError: actions.setActionError, clearContextMenu: vi.fn(),
  } as unknown as Parameters<typeof useWorkflowSaveRunOrchestration>[0])
  await orchestration.runPreview()
  expect(displays.hasPreviewNodeDisplays.value).toBe(false)
  const terminal = { ...running, state: 'succeeded', node_records: [
    { node_id: 'image', node_type_id: 'core.io.image-preview', outputs: { body: { type: 'image-preview', image: { transport_kind: 'inline-base64', media_type: 'image/png', image_base64: 'aW1hZ2U=', width: 2, height: 2 } } } },
    { node_id: 'value', node_type_id: 'core.io.value-preview', outputs: { body: { type: 'value-preview', value: false } } },
  ] } as unknown as WorkflowPreviewRun
  io.get.mockResolvedValue(terminal)
  await io.stream.mock.calls[0]![0].onSnapshot(terminal)
  await flushPromises()
  expect(displays.getPreviewNodeDisplay('value')?.payload.value).toBe(false)
  expect(displays.getPreviewNodeDisplay('image')?.image?.src).toContain('data:image/png;base64,')
  expect(actions.previewing.value).toBe(false)
  displays.revokePreviewImageObjectUrls()
})
