import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/shared/api/error'
import { useWorkflowPreviewDisplays } from '@/workflows/workflow-editor/preview/useWorkflowPreviewDisplays'
import { readProjectObjectContentBlob } from '@/workflows/workflow-editor/services/workflow-runtime.service'

vi.mock('@/workflows/workflow-editor/services/workflow-runtime.service', () => ({ readProjectObjectContentBlob: vi.fn() }))
describe('结果文件授权失败', () => {
  it('项目图片显示权限错误，纯值输出继续显示', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.mocked(readProjectObjectContentBlob).mockRejectedValue(new ApiError(403, { message: 'forbidden' }))
    const displays = useWorkflowPreviewDisplays()
    await displays.refreshDisplayOutputs({ project_id: 'project-1', readonly: true }, [
      { nodeId: 'image', nodeTypeId: 'core.io.image-preview', outputName: 'body', payload: { type: 'image-preview', image: { transport_kind: 'storage-ref', object_key: 'projects/project-1/results/result.png' } } },
      { nodeId: 'value', nodeTypeId: 'core.io.value-preview', outputName: 'body', payload: { type: 'value-preview', value: { count: 24 } } },
    ])
    expect(displays.previewNodeDisplays.value.image?.image?.statusText).toBe('缺少查看项目文件权限')
    expect(displays.previewNodeDisplays.value.value?.formattedValue).toContain('24')
    vi.restoreAllMocks()
  })
})
