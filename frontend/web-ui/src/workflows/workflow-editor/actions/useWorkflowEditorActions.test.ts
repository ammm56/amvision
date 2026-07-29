import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowPreviewRunActionInput } from './useWorkflowEditorActions'
import { useWorkflowEditorActions } from './useWorkflowEditorActions'

const mocks = vi.hoisted(() => ({
  validateWorkflowTemplate: vi.fn(),
  validateWorkflowApplication: vi.fn(),
  createWorkflowPreviewRun: vi.fn(),
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
}))

vi.mock('../services/workflow-app.service', () => ({
  saveWorkflowApp: mocks.saveWorkflowApp,
}))

describe('useWorkflowEditorActions Preview guard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
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
})
