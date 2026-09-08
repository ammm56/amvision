import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/shared/api/error'
import { useWorkflowEditorActions, type WorkflowPreviewRunActionInput } from '@/workflows/workflow-editor/actions/useWorkflowEditorActions'

const mocks = vi.hoisted(() => ({ validate: vi.fn(), save: vi.fn(), preview: vi.fn() }))
vi.mock('@/workflows/workflow-editor/services/workflow-template.service', () => ({ validateWorkflowTemplate: vi.fn().mockResolvedValue({}) }))
vi.mock('@/workflows/workflow-editor/services/workflow-application.service', () => ({ validateWorkflowApplication: mocks.validate }))
vi.mock('@/workflows/workflow-editor/services/workflow-app.service', () => ({ saveWorkflowApp: mocks.save }))
vi.mock('@/workflows/workflow-editor/services/workflow-runtime.service', () => ({ createWorkflowPreviewRun: mocks.preview, getWorkflowPreviewRun: vi.fn() }))

const input = { projectId: 'project-1', application: {}, template: { nodes: [] }, inputBindings: {} } as unknown as WorkflowPreviewRunActionInput

beforeEach(() => { setActivePinia(createPinia()); vi.clearAllMocks() })

describe('工作流校验错误详情', () => {
  it.each(['save', 'preview'] as const)('%s 显示后端具体节点原因，校验失败不提交', async (action) => {
    mocks.validate.mockRejectedValue(new ApiError(422, {
      message: 'workflow application 校验失败',
      details: { reason: 'App Mode 引用了已禁用的节点 core_io_image_preview_3' },
    }))
    const editor = useWorkflowEditorActions()
    const result = action === 'save' ? await editor.saveWorkflowDocument(input) : await editor.runWorkflowPreview(input)
    expect(result).toBeNull()
    expect(editor.errorMessage.value).toBe('workflow application 校验失败：App Mode 引用了已禁用的节点 core_io_image_preview_3')
    expect(mocks.save).not.toHaveBeenCalled()
    expect(mocks.preview).not.toHaveBeenCalled()
  })
  it.each([undefined, { reason: '' }, { reason: { node: 'invalid' } }])('缺失或非文本 reason 保留原始消息', async (details) => {
    mocks.validate.mockRejectedValue(new ApiError(422, { message: '校验失败', details }))
    const editor = useWorkflowEditorActions()
    await editor.saveWorkflowDocument(input)
    expect(editor.errorMessage.value).toBe('校验失败')
  })
  it('原始消息已经包含原因时不重复追加', async () => {
    mocks.validate.mockRejectedValue(new ApiError(422, { message: '校验失败：节点已禁用', details: { reason: '节点已禁用' } }))
    const editor = useWorkflowEditorActions()
    await editor.saveWorkflowDocument(input)
    expect(editor.errorMessage.value).toBe('校验失败：节点已禁用')
  })
})
