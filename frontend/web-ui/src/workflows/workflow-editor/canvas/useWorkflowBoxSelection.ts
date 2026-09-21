import { onBeforeUnmount, ref } from 'vue'

interface Point { x: number; y: number }
interface Box extends Point { width: number; height: number }
interface Candidate extends Box { id: string }

/** 框选仅缓存本次手势的几何，不读取或复制节点参数。 */
export function useWorkflowBoxSelection(options: {
  candidates: () => Candidate[]
  readSelection: () => Iterable<string>
  select: (ids: Iterable<string>) => void
  screenToWorld: (x: number, y: number) => Point
  blocked: () => boolean
}) {
  const rect = ref<Box | null>(null)
  let gesture: { start: Point; previous: string[]; nodes: Candidate[] } | null = null
  let last: Point | null = null
  let frame = 0
  let suppressClick = false

  function render(): void {
    frame = 0
    if (!gesture || !last) return
    const start = gesture.start
    const box = { x: Math.min(start.x, last.x), y: Math.min(start.y, last.y), width: Math.abs(start.x - last.x), height: Math.abs(start.y - last.y) }
    rect.value = box
    options.select(gesture.nodes.filter(n => n.x >= box.x && n.y >= box.y && n.x + n.width <= box.x + box.width && n.y + n.height <= box.y + box.height).map(n => n.id))
  }
  function cleanup(): void {
    cancelAnimationFrame(frame)
    frame = 0
    document.removeEventListener('mousemove', move)
    document.removeEventListener('mouseup', finish)
    window.removeEventListener('blur', cancel)
    gesture = null
    rect.value = null
    last = null
  }
  function finish(event: MouseEvent): void {
    cancelAnimationFrame(frame)
    last = options.screenToWorld(event.clientX, event.clientY)
    render()
    cleanup()
    // mouseup 随后的 click 不能清空框选或选中背景节点组。
    suppressClick = true
  }
  function cancel(): boolean {
    if (!gesture) return false
    const previous = gesture.previous
    cleanup()
    suppressClick = true
    options.select(previous)
    return true
  }
  function move(event: MouseEvent): void {
    if (!(event.buttons & 1)) { cancel(); return }
    last = options.screenToWorld(event.clientX, event.clientY)
    if (!frame) frame = requestAnimationFrame(render)
  }
  function start(event: MouseEvent): boolean {
    // 新手势解除上一手势未产生 click 的抑制；Esc 后松手仍保留原选择。
    suppressClick = false
    if (!event.ctrlKey || event.button !== 0 || options.blocked()) return false
    const excluded = '.workflow-graph-node, .workflow-graph-boundary-node, .workflow-graph-note, .workflow-graph-toolbar, .workflow-graph-floating-panel, .workflow-graph-context-menu, .workflow-node-picker, .workflow-graph-navigation-dock, .workflow-graph-minimap, .workflow-graph-port, input, textarea, select, button, [contenteditable], [role="dialog"], [role="menu"]'
    if (event.target instanceof Element && event.target.closest(excluded)) return false
    event.preventDefault()
    event.stopPropagation()
    const start = options.screenToWorld(event.clientX, event.clientY)
    gesture = { start, previous: [...options.readSelection()], nodes: options.candidates() }
    rect.value = { ...start, width: 0, height: 0 }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', finish)
    window.addEventListener('blur', cancel)
    return true
  }
  function consumeClick(event: MouseEvent): boolean {
    if (!suppressClick) return false
    suppressClick = false
    event.stopPropagation()
    event.preventDefault()
    return true
  }
  onBeforeUnmount(cleanup)
  return { rect, start, cancel, consumeClick }
}
