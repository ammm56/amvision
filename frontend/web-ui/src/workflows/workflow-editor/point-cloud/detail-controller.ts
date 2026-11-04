import type { CloudRendererPolicy } from '../services/measurement-resource.service'
import type { CloudDisplayData } from './preview-data'
import type { DetailIndex, DetailBlock } from './asset-details'

export type DetailStatus = 'overview' | 'loading' | 'ready' | 'limited' | 'error'

/** 相机停止后只加载当前视野；切换时撤销旧请求，未完成集合不冒充完整视野。 */
export function createDetailController(index: DetailIndex, policy: CloudRendererPolicy, baseCount: number,
  load: (block: DetailBlock, signal: AbortSignal) => Promise<CloudDisplayData>,
  target: { clear(): void; add(data: CloudDisplayData): void; complete(): void; visible(block: DetailBlock): boolean },
  report: (status: DetailStatus, count: number, error?: string) => void) {
  let closed = false, enabled = false, failed = false, serial = 0, timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | null = null
  function cancel() { serial++; clearTimeout(timer); controller?.abort(); controller = null; target.clear() }
  async function loadView(token: number) {
    if (closed || !enabled || token !== serial) return
    const selected = index.blocks.filter(target.visible), count = selected.reduce((n, b) => n + b.count, 0)
    const bytes = selected.reduce((n, b) => n + b.byte_length, 0)
    if (!count || count + baseCount > policy.max_points || bytes > policy.max_data_bytes) { report('limited', 0); return }
    controller = new AbortController()
    const signal = controller.signal
    report('loading', 0)
    try {
      for (const block of selected) {
        const data = await load(block, signal)
        if (closed || token !== serial || signal.aborted) { data.dispose(); return }
        try { target.add(data) } catch (error) { data.dispose(); throw error }
      }
      if (closed || token !== serial || signal.aborted) return
      target.complete(); report('ready', count)
    } catch (error) {
      if (closed || token !== serial || signal.aborted) return
      failed = true
      target.clear(); report('error', 0, error instanceof Error ? error.message : 'cloud_preview_invalid')
    }
  }
  function changed() {
    if (closed) return
    cancel()
    // 错误可改变布局并触发 resize；只有显式重载建立新控制器才能重试。
    if (failed) return
    report('overview', 0)
    if (enabled) { const token = serial; timer = setTimeout(() => { void loadView(token) }, 150) }
  }
  return {
    changed,
    enable(value: boolean) { enabled = value; changed() },
    dispose() { closed = true; cancel() },
  }
}
