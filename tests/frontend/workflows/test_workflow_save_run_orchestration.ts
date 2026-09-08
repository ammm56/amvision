import { computed, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useWorkflowSaveRunOrchestration } from '@/workflows/workflow-editor/actions/useWorkflowSaveRunOrchestration'
import type { WorkflowAppSaveResult } from '@/workflows/workflow-editor/services/workflow-app.service'
function setup() {
  const result = { applicationDocument: { draft_fingerprint: 'saved-fingerprint' }, graphDocument: {} } as WorkflowAppSaveResult
  const options = { workflowApp: ref({ id: 'source' }), isNewApp: computed(() => false), selectedProjectId: computed(() => 'p'), readNewWorkflowAppSaveBlocker: () => null, buildCurrentTemplate: () => ({}) as never, buildCurrentApplication: () => ({}) as never, runWorkflowPreflight: () => null, applyWorkflowValidationIssue: vi.fn(), buildPreviewInputBindings: vi.fn().mockResolvedValue({ inputBindings: {}, fileUploads: [] }), saveWorkflowDocument: vi.fn().mockResolvedValue(result), runWorkflowPreview: vi.fn(), applyWorkflowSaveFeedback: vi.fn().mockResolvedValue(undefined), applyPreviewRunFeedback: vi.fn(), clearActionMessages: vi.fn(), revokePreviewImageObjectUrls: vi.fn(), setActionError: vi.fn(), clearContextMenu: vi.fn(), commitParameterDrafts: vi.fn(() => true) }
  return { result, options, actions: useWorkflowSaveRunOrchestration(options) }
}
describe('save and preview orchestration', () => {
  it('keeps the save lock through feedback and rejects a second save', async () => {
    const { options, actions } = setup()
    let finish!: () => void
    options.applyWorkflowSaveFeedback.mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
    const first = actions.saveCurrentWorkflowApp()
    await Promise.resolve()
    expect(actions.saveInProgress.value).toBe(true)
    expect(await actions.saveCurrentWorkflowApp()).toBeNull()
    expect(options.saveWorkflowDocument).toHaveBeenCalledOnce()
    finish()
    await first
    expect(actions.saveInProgress.value).toBe(false)
  })
  it('does not replace a different document with late save feedback', async () => {
    const { result, options, actions } = setup()
    let finish!: (result: WorkflowAppSaveResult) => void
    options.saveWorkflowDocument.mockImplementation(() => new Promise(resolve => { finish = resolve }))
    const first = actions.saveCurrentWorkflowApp()
    options.workflowApp.value = { id: 'other' }
    finish(result)
    expect(await first).toEqual({ result })
    expect(options.applyWorkflowSaveFeedback).not.toHaveBeenCalled()
  })
  it('blocks save and preview while another document operation is pending', async () => {
    const { options } = setup()
    const actions = useWorkflowSaveRunOrchestration({ ...options, isDocumentBusy: () => true })
    expect(await actions.saveCurrentWorkflowApp()).toBeNull()
    await actions.runPreview()
    expect(options.saveWorkflowDocument).not.toHaveBeenCalled()
    expect(options.buildPreviewInputBindings).not.toHaveBeenCalled()
  })
  it('returns the successful write even if the subsequent page refresh fails', async () => {
    const { result, options, actions } = setup()
    const failure = new Error('read failed')
    options.applyWorkflowSaveFeedback.mockRejectedValue(failure)
    expect(await actions.saveCurrentWorkflowApp()).toEqual({ result, refreshError: failure })
    expect(options.saveWorkflowDocument).toHaveBeenCalledOnce()
  })
  it('does not save invalid pending JSON parameter text', async () => {
    const { options, actions } = setup()
    options.commitParameterDrafts.mockReturnValue(false)
    expect(await actions.saveCurrentWorkflowApp()).toBeNull()
    expect(options.saveWorkflowDocument).not.toHaveBeenCalled()
  })
  it('does not report a rejected write as saved or refresh its state', async () => {
    const { options, actions } = setup()
    options.saveWorkflowDocument.mockResolvedValue(null)
    expect(await actions.saveCurrentWorkflowApp()).toBeNull()
    expect(options.applyWorkflowSaveFeedback).not.toHaveBeenCalled()
  })
  it('ignores pending preview input preparation after the document is replaced', async () => {
    const { options, actions } = setup()
    let resolve!: (value: unknown) => void
    options.buildPreviewInputBindings.mockImplementation(() => new Promise(done => { resolve = done }))
    const request = actions.runPreview()
    options.workflowApp.value = { id: 'replacement' }
    resolve({ inputBindings: {}, fileUploads: [] })
    await request
    expect(options.runWorkflowPreview).not.toHaveBeenCalled()
  })
})
