import { onMounted, onUnmounted, type Ref } from 'vue'

export interface WorkflowEditorLifecycleOptions {
  canvasRef: Ref<HTMLElement | null>
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

  onMounted(() => {
    void options.loadPage()
    window.addEventListener('keydown', options.handleKeydown)
    window.addEventListener('resize', options.updateStageSize)
    if (typeof ResizeObserver !== 'undefined' && options.canvasRef.value) {
      resizeObserver = new ResizeObserver(options.updateStageSize)
      resizeObserver.observe(options.canvasRef.value)
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
    window.removeEventListener('resize', options.updateStageSize)
    resizeObserver?.disconnect()
  })
}
