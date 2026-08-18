import { ref, type Ref } from 'vue'

import { isPrimaryMouseButtonPressed } from './workflowMouseDrag'

interface PanState {
  startClientX: number
  startClientY: number
  startX: number
  startY: number
}

interface WorkflowCanvasPanOptions {
  viewportX: Ref<number>
  viewportY: Ref<number>
  shouldIgnorePointerTarget: (target: EventTarget | null) => boolean
  beforeStart?: () => void
}

export function useWorkflowCanvasPan(options: WorkflowCanvasPanOptions) {
  const panState = ref<PanState | null>(null)

  function startStagePan(event: MouseEvent): void {
    if (event.button !== 0 || options.shouldIgnorePointerTarget(event.target)) return
    options.beforeStart?.()
    panState.value = {
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: options.viewportX.value,
      startY: options.viewportY.value,
    }
    event.preventDefault()
    document.addEventListener('mousemove', moveStagePan)
    document.addEventListener('mouseup', stopStagePan)
    window.addEventListener('blur', stopStagePan)
  }

  function moveStagePan(event: MouseEvent): void {
    const pan = panState.value
    if (!pan) return
    if (!isPrimaryMouseButtonPressed(event)) {
      stopStagePan()
      return
    }
    options.viewportX.value = pan.startX + event.clientX - pan.startClientX
    options.viewportY.value = pan.startY + event.clientY - pan.startClientY
  }

  function stopStagePan(): void {
    panState.value = null
    document.removeEventListener('mousemove', moveStagePan)
    document.removeEventListener('mouseup', stopStagePan)
    window.removeEventListener('blur', stopStagePan)
  }

  return {
    startStagePan,
    stopStagePan,
  }
}
