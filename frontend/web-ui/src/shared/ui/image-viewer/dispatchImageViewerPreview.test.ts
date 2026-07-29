import { describe, expect, it, vi } from 'vitest'

import { dispatchImageViewerPreview } from './dispatchImageViewerPreview'

describe('dispatchImageViewerPreview', () => {
  it('把有草稿的 Apply 和 Preview 作为一个原子父级事件发送', () => {
    const previewInteraction = vi.fn()
    const runPreview = vi.fn()
    const event = { nodeId: 'mask-editor', maskDataUrl: 'data:image/png;base64,AA==' }

    const result = dispatchImageViewerPreview(true, event, {
      previewInteraction,
      runPreview,
    })

    expect(result).toBe('interaction')
    expect(previewInteraction).toHaveBeenCalledOnce()
    expect(previewInteraction).toHaveBeenCalledWith(event)
    expect(runPreview).not.toHaveBeenCalled()
  })

  it('没有交互草稿时只请求重新执行 Preview', () => {
    const previewInteraction = vi.fn()
    const runPreview = vi.fn()

    const result = dispatchImageViewerPreview(false, null, {
      previewInteraction,
      runPreview,
    })

    expect(result).toBe('preview')
    expect(previewInteraction).not.toHaveBeenCalled()
    expect(runPreview).toHaveBeenCalledOnce()
  })

  it('草稿无法构造参数时不会触发任何执行', () => {
    const previewInteraction = vi.fn()
    const runPreview = vi.fn()

    const result = dispatchImageViewerPreview(true, null, {
      previewInteraction,
      runPreview,
    })

    expect(result).toBe('invalid')
    expect(previewInteraction).not.toHaveBeenCalled()
    expect(runPreview).not.toHaveBeenCalled()
  })
})
