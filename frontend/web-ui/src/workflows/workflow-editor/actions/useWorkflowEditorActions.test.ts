import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowPreviewRunActionInput } from './useWorkflowEditorActions'
import { useWorkflowEditorActions } from './useWorkflowEditorActions'
import { useSessionStore } from '@/app/stores/session.store'

const mocks = vi.hoisted(() => ({
  validateWorkflowTemplate: vi.fn(),
  validateWorkflowApplication: vi.fn(),
  createWorkflowPreviewRun: vi.fn(),
  getWorkflowPreviewRun: vi.fn(),
  cancelWorkflowPreviewRun: vi.fn(),
  stream: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  refreshNow: vi.fn(),
  saveWorkflowApp: vi.fn(),
}))

vi.mock('@/platform/i18n', () => ({
  translate: (key: string) => key,
}))

vi.mock('../services/workflow-template.service', () => ({
  validateWorkflowTemplate: mocks.validateWorkflowTemplate,
}))

vi.mock('../services/workflow-application.service', () => ({
  validateWorkflowApplication: mocks.validateWorkflowApplication,
}))

vi.mock('../services/workflow-runtime.service', () => ({
  createWorkflowPreviewRun: mocks.createWorkflowPreviewRun,
  getWorkflowPreviewRun: mocks.getWorkflowPreviewRun,
  cancelWorkflowPreviewRun: mocks.cancelWorkflowPreviewRun,
}))

vi.mock('../composables/useWorkflowResourceStream', () => ({ useWorkflowResourceStream: mocks.stream }))

vi.mock('../services/workflow-app.service', () => ({
  saveWorkflowApp: mocks.saveWorkflowApp,
}))

describe('useWorkflowEditorActions Preview guard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    sessionStorage.clear()
    mocks.stream.mockReturnValue({ start: mocks.start, stop: mocks.stop, refreshNow: mocks.refreshNow })
    mocks.validateWorkflowApplication.mockResolvedValue({})
    mocks.createWorkflowPreviewRun.mockResolvedValue({
      preview_run_id: 'preview-run-1',
      state: 'succeeded',
    })
  })

  it('rejects a second Preview before validation completes', async () => {
    let releaseValidation: () => void = () => undefined
    mocks.validateWorkflowTemplate.mockImplementation(
      () => new Promise<void>((resolve) => {
        releaseValidation = resolve
      }),
    )
    const actions = useWorkflowEditorActions()
    const input = {
      projectId: 'project-1',
      template: {
        nodes: [],
      },
      application: {},
      inputBindings: {},
    } as unknown as WorkflowPreviewRunActionInput

    const firstRun = actions.runWorkflowPreview(input)
    expect(actions.previewing.value).toBe(true)

    const duplicateRun = await actions.runWorkflowPreview(input)
    expect(duplicateRun).toBeNull()
    expect(actions.statusMessage.value).toBe(
      'workflowEditor.feedback.previewAlreadyRunning',
    )
    expect(mocks.createWorkflowPreviewRun).not.toHaveBeenCalled()

    releaseValidation()
    await firstRun
    expect(mocks.createWorkflowPreviewRun).toHaveBeenCalledTimes(1)
    expect(actions.previewing.value).toBe(false)
  })

  it('forwards node execution scope and retains node records', async () => {
    mocks.validateWorkflowTemplate.mockResolvedValue({})
    const actions = useWorkflowEditorActions()
    await actions.runWorkflowPreview({
      projectId: 'project-1',
      template: {
        nodes: [],
      },
      application: {},
      inputBindings: {},
      executionScope: {
        kind: 'node',
        targetNodeId: 'mask-editor-1',
      },
    } as unknown as WorkflowPreviewRunActionInput)

    expect(mocks.createWorkflowPreviewRun).toHaveBeenCalledWith(
      expect.objectContaining({
        executionScope: {
          kind: 'node',
          targetNodeId: 'mask-editor-1',
        },
        executionMetadata: expect.objectContaining({
          retain_node_records_enabled: true,
        }),
      }),
    )
  })

  it('keeps accepted long runs busy until a terminal snapshot, including cancellation', async () => {
    mocks.validateWorkflowTemplate.mockResolvedValue({})
    const running = { preview_run_id: 'preview-long', state: 'running', project_id: 'project-1', application_id: 'app-1' }
    mocks.createWorkflowPreviewRun.mockResolvedValue(running)
    const actions = useWorkflowEditorActions()
    const input = { projectId: 'project-1', application: { application_id: 'app-1' }, template: { nodes: [] }, inputBindings: {} } as unknown as WorkflowPreviewRunActionInput
    await actions.runWorkflowPreview(input)
    expect(mocks.createWorkflowPreviewRun).toHaveBeenCalledWith(expect.objectContaining({ waitMode: 'async' }))
    expect(actions.previewing.value).toBe(true)
    expect(mocks.start).toHaveBeenCalledWith('preview-long')
    await actions.runWorkflowPreview(input)
    expect(mocks.createWorkflowPreviewRun).toHaveBeenCalledTimes(1)
    await actions.cancelPreviewRun()
    await actions.cancelPreviewRun()
    expect(mocks.cancelWorkflowPreviewRun).toHaveBeenCalledTimes(1)
    expect(actions.previewing.value).toBe(true)
    expect(actions.previewCancelling.value).toBe(true)
    mocks.stream.mock.calls[0]![0].onSnapshot({ ...running, state: 'cancelled' })
    expect(actions.previewing.value).toBe(false)
    expect(actions.previewCancelling.value).toBe(false)
  })

  it('restores only the same user, project and app; terminal snapshots clear the stored run', async () => {
    mocks.validateWorkflowTemplate.mockResolvedValue({})
    useSessionStore().currentUser = { principal_id: 'user-1' } as NonNullable<ReturnType<typeof useSessionStore>['currentUser']>
    const running = { preview_run_id: 'preview-long', state: 'running', project_id: 'project-1', application_id: 'app-1' }
    mocks.createWorkflowPreviewRun.mockResolvedValue(running)
    mocks.getWorkflowPreviewRun.mockResolvedValue(running)
    const actions = useWorkflowEditorActions()
    await actions.runWorkflowPreview({ projectId: 'project-1', application: { application_id: 'app-1' }, template: { nodes: [] }, inputBindings: {} } as unknown as WorkflowPreviewRunActionInput)
    actions.resetPreviewRun()
    await actions.restorePreviewRun('other-project', 'app-1')
    expect(mocks.getWorkflowPreviewRun).not.toHaveBeenCalled()
    await actions.restorePreviewRun('project-1', 'app-1')
    expect(mocks.getWorkflowPreviewRun).toHaveBeenCalledWith('preview-long')
    expect(actions.previewing.value).toBe(true)
    mocks.stream.mock.calls[0]![0].onSnapshot({ ...running, state: 'succeeded' })
    expect(sessionStorage.length).toBe(0)
  })
})
