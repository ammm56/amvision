import { computed, ref, type Ref } from 'vue'

interface WorkflowCanvasViewportNodeView {
  x: number
  y: number
  width: number
}

interface WorkflowCanvasViewportBoundaryView {
  id: string
  x: number
  y: number
  width: number
}

interface WorkflowMinimapNode {
  nodeId: string
  style: Record<string, string>
}

interface WorkflowCanvasViewportOptions<NodeView extends WorkflowCanvasViewportNodeView, BoundaryView extends WorkflowCanvasViewportBoundaryView> {
  canvasRef: Ref<HTMLElement | null>
  graphNodes: Ref<NodeView[]>
  readBoundaryNodes: () => BoundaryView[]
  readNodeId: (node: NodeView) => string
  readNodeHeight: (node: NodeView) => number
  readBoundaryHeight: (boundary: BoundaryView) => number
  selectNode: (nodeId: string) => void
  shouldIgnoreWheelTarget: (target: EventTarget | null) => boolean
  clearTransientUi: () => void
}

const minimapWidth = 184
const minimapHeight = 116
const minimapPadding = 10
const minViewportScale = 0.35
const maxViewportScale = 2.4

export function useWorkflowCanvasViewport<NodeView extends WorkflowCanvasViewportNodeView, BoundaryView extends WorkflowCanvasViewportBoundaryView>(
  options: WorkflowCanvasViewportOptions<NodeView, BoundaryView>,
) {
  const minimapVisible = ref(true)
  const viewportX = ref(0)
  const viewportY = ref(0)
  const viewportScale = ref(1)
  const stageSize = ref({ width: 1, height: 1 })

  const worldTransformStyle = computed(() => ({
    transform: `translate(${viewportX.value}px, ${viewportY.value}px) scale(${viewportScale.value})`,
  }))

  const worldBounds = computed(() => calculateWorldBounds())

  const minimapScale = computed(() => {
    const bounds = worldBounds.value
    const availableWidth = minimapWidth - minimapPadding * 2
    const availableHeight = minimapHeight - minimapPadding * 2
    return Math.min(availableWidth / Math.max(bounds.width, 1), availableHeight / Math.max(bounds.height, 1))
  })

  const minimapNodes = computed<WorkflowMinimapNode[]>(() => {
    const bounds = worldBounds.value
    const scale = minimapScale.value
    const regularNodes = options.graphNodes.value.map((node) => ({
      nodeId: options.readNodeId(node),
      style: {
        left: `${minimapPadding + (node.x - bounds.minX) * scale}px`,
        top: `${minimapPadding + (node.y - bounds.minY) * scale}px`,
        width: `${Math.max(node.width * scale, 8)}px`,
        height: `${Math.max(72 * scale, 5)}px`,
      },
    }))
    const boundaryNodes = options.readBoundaryNodes().map((boundary) => ({
      nodeId: boundary.id,
      style: {
        left: `${minimapPadding + (boundary.x - bounds.minX) * scale}px`,
        top: `${minimapPadding + (boundary.y - bounds.minY) * scale}px`,
        width: `${Math.max(boundary.width * scale, 8)}px`,
        height: `${Math.max(options.readBoundaryHeight(boundary) * scale, 5)}px`,
      },
    }))
    return [...regularNodes, ...boundaryNodes]
  })

  const minimapViewportStyle = computed(() => {
    const bounds = worldBounds.value
    const scale = minimapScale.value
    const viewLeft = -viewportX.value / viewportScale.value
    const viewTop = -viewportY.value / viewportScale.value
    return {
      left: `${minimapPadding + (viewLeft - bounds.minX) * scale}px`,
      top: `${minimapPadding + (viewTop - bounds.minY) * scale}px`,
      width: `${Math.max((stageSize.value.width / viewportScale.value) * scale, 8)}px`,
      height: `${Math.max((stageSize.value.height / viewportScale.value) * scale, 8)}px`,
    }
  })

  function screenToWorld(clientX: number, clientY: number): { x: number; y: number } {
    const canvasBounds = options.canvasRef.value?.getBoundingClientRect()
    if (!canvasBounds) return { x: 0, y: 0 }
    return {
      x: (clientX - canvasBounds.left - viewportX.value) / viewportScale.value,
      y: (clientY - canvasBounds.top - viewportY.value) / viewportScale.value,
    }
  }

  function handleStageWheel(event: WheelEvent): void {
    if (options.shouldIgnoreWheelTarget(event.target)) return
    event.preventDefault()
    options.clearTransientUi()
    const wheelStep = Math.max(-3, Math.min(3, -event.deltaY / 100))
    const nextScale = clampNumber(viewportScale.value * Math.pow(1.12, wheelStep), minViewportScale, maxViewportScale)
    zoomViewportAt(event.clientX, event.clientY, nextScale)
  }

  function zoomViewportAt(clientX: number, clientY: number, nextScale: number): void {
    const canvasBounds = options.canvasRef.value?.getBoundingClientRect()
    if (!canvasBounds) return
    const stageX = clientX - canvasBounds.left
    const stageY = clientY - canvasBounds.top
    const worldX = (stageX - viewportX.value) / viewportScale.value
    const worldY = (stageY - viewportY.value) / viewportScale.value
    viewportScale.value = nextScale
    viewportX.value = stageX - worldX * nextScale
    viewportY.value = stageY - worldY * nextScale
  }

  function clampNumber(value: number, minValue: number, maxValue: number): number {
    return Math.min(maxValue, Math.max(minValue, value))
  }

  function calculateWorldBounds(): { minX: number; minY: number; maxX: number; maxY: number; width: number; height: number } {
    if (options.graphNodes.value.length === 0) {
      const viewLeft = -viewportX.value / viewportScale.value
      const viewTop = -viewportY.value / viewportScale.value
      const viewWidth = stageSize.value.width / viewportScale.value
      const viewHeight = stageSize.value.height / viewportScale.value
      return { minX: viewLeft, minY: viewTop, maxX: viewLeft + viewWidth, maxY: viewTop + viewHeight, width: viewWidth, height: viewHeight }
    }
    const boundaryNodes = options.readBoundaryNodes()
    const minX = Math.min(...options.graphNodes.value.map((node) => node.x), ...boundaryNodes.map((boundary) => boundary.x)) - 160
    const minY = Math.min(...options.graphNodes.value.map((node) => node.y), ...boundaryNodes.map((boundary) => boundary.y)) - 120
    const maxX = Math.max(...options.graphNodes.value.map((node) => node.x + node.width), ...boundaryNodes.map((boundary) => boundary.x + boundary.width)) + 160
    const maxY = Math.max(
      ...options.graphNodes.value.map((node) => node.y + options.readNodeHeight(node)),
      ...boundaryNodes.map((boundary) => boundary.y + options.readBoundaryHeight(boundary)),
    ) + 120
    return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
  }

  function startMinimapNavigation(event: MouseEvent): void {
    moveViewportFromMinimap(event)
    document.addEventListener('mousemove', moveViewportFromMinimap)
    document.addEventListener('mouseup', stopMinimapNavigation)
  }

  function moveViewportFromMinimap(event: MouseEvent): void {
    const target = event.currentTarget instanceof Element ? event.currentTarget : document.querySelector('.workflow-graph-minimap')
    const bounds = target?.getBoundingClientRect()
    if (!bounds) return
    const scale = minimapScale.value
    const worldBoundsValue = worldBounds.value
    const worldX = worldBoundsValue.minX + (event.clientX - bounds.left - minimapPadding) / scale
    const worldY = worldBoundsValue.minY + (event.clientY - bounds.top - minimapPadding) / scale
    viewportX.value = stageSize.value.width / 2 - worldX * viewportScale.value
    viewportY.value = stageSize.value.height / 2 - worldY * viewportScale.value
  }

  function stopMinimapNavigation(): void {
    document.removeEventListener('mousemove', moveViewportFromMinimap)
    document.removeEventListener('mouseup', stopMinimapNavigation)
  }

  function fitView(): void {
    const bounds = worldBounds.value
    viewportX.value = stageSize.value.width / 2 - (bounds.minX + bounds.width / 2) * viewportScale.value
    viewportY.value = stageSize.value.height / 2 - (bounds.minY + bounds.height / 2) * viewportScale.value
    options.clearTransientUi()
  }

  function focusGraphNode(nodeId: string): void {
    const graphNode = options.graphNodes.value.find((node) => options.readNodeId(node) === nodeId)
    if (!graphNode) return
    options.selectNode(nodeId)
    const centerX = graphNode.x + graphNode.width / 2
    const centerY = graphNode.y + options.readNodeHeight(graphNode) / 2
    viewportX.value = stageSize.value.width / 2 - centerX * viewportScale.value
    viewportY.value = stageSize.value.height / 2 - centerY * viewportScale.value
  }

  function resetView(): void {
    viewportX.value = 0
    viewportY.value = 0
    viewportScale.value = 1
    options.clearTransientUi()
  }

  function toggleMinimap(): void {
    minimapVisible.value = !minimapVisible.value
    options.clearTransientUi()
  }

  function updateStageSize(): void {
    const bounds = options.canvasRef.value?.getBoundingClientRect()
    if (!bounds) return
    stageSize.value = { width: bounds.width, height: bounds.height }
  }

  return {
    minimapVisible,
    viewportX,
    viewportY,
    viewportScale,
    stageSize,
    worldTransformStyle,
    minimapNodes,
    minimapViewportStyle,
    screenToWorld,
    handleStageWheel,
    clampNumber,
    fitView,
    focusGraphNode,
    resetView,
    toggleMinimap,
    startMinimapNavigation,
    stopMinimapNavigation,
    updateStageSize,
  }
}
