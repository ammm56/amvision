import { onMounted, onUnmounted, type Ref } from 'vue'

export interface WorkflowEditorLifecycleOptions {
  canvasRef: Ref<HTMLElement | null>
  toolbarRef?: Ref<{ $el: HTMLElement } | null>
  loadPage: () => void | Promise<void>
  handleKeydown: (event: KeyboardEvent) => void
  updateStageSize: () => void
  stopNodeDrag: () => void
  stopBoundaryDrag: () => void
  stopPortConnection: () => void
  stopStagePan: () => void
  stopMinimapNavigation: () => void
  cancelTransientGraphOperations?: () => void
  revokePreviewImageObjectUrls: () => void
}

export function useWorkflowEditorLifecycle(options: WorkflowEditorLifecycleOptions): void {
  let resizeObserver: ResizeObserver | null = null

  function updateLayout(): void {
    options.updateStageSize()
    const stage = options.canvasRef.value
    const toolbar = options.toolbarRef?.value?.$el
    if (!stage || !toolbar) return
    // 保留标题和状态两行空间；按钮换行时再按实际工具栏高度扩展。
    const inset = `${Math.max(104, toolbar.offsetTop + toolbar.offsetHeight + 12)}px`
    if (stage.style.getPropertyValue('--workflow-toolbar-bottom') !== inset) {
      stage.style.setProperty('--workflow-toolbar-bottom', inset)
    }
  }

  onMounted(() => {
    void options.loadPage()
    window.addEventListener('keydown', options.handleKeydown)
    window.addEventListener('resize', updateLayout)
    updateLayout()
    if (typeof ResizeObserver !== 'undefined' && options.canvasRef.value) {
      resizeObserver = new ResizeObserver(updateLayout)
      resizeObserver.observe(options.canvasRef.value)
      const toolbar = options.toolbarRef?.value?.$el
      if (toolbar) resizeObserver.observe(toolbar)
    }
  })

  onUnmounted(() => {
    options.stopNodeDrag()
    options.stopBoundaryDrag()
    options.stopPortConnection()
    options.stopStagePan()
    options.stopMinimapNavigation()
    options.cancelTransientGraphOperations?.()
    options.revokePreviewImageObjectUrls()
    window.removeEventListener('keydown', options.handleKeydown)
    window.removeEventListener('resize', updateLayout)
    resizeObserver?.disconnect()
    options.canvasRef.value?.style.removeProperty('--workflow-toolbar-bottom')
  })
}
