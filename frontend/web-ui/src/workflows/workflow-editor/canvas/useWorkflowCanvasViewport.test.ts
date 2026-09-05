import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { useWorkflowCanvasViewport } from './useWorkflowCanvasViewport'

interface TestNode {
  id: string
  x: number
  y: number
  width: number
  height: number
}

describe('useWorkflowCanvasViewport', () => {
  it('适配大型流程时同时居中并计算缩放比例', () => {
    const canvasRef = ref({
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 800 }),
    } as HTMLElement)
    const graphNodes = ref<TestNode[]>([
      { id: 'node-1', x: 0, y: 0, width: 200, height: 100 },
      { id: 'node-2', x: 2000, y: 1000, width: 200, height: 100 },
    ])
    const clearTransientUi = vi.fn()
    const viewport = useWorkflowCanvasViewport({
      canvasRef,
      graphNodes,
      graphNotes: ref([]),
      readBoundaryNodes: () => [],
      readNodeId: (node) => node.id,
      readNodeHeight: (node) => node.height,
      readBoundaryHeight: () => 0,
      selectNode: vi.fn(),
      shouldIgnoreWheelTarget: () => false,
      clearTransientUi,
    })

    viewport.updateStageSize()
    viewport.fitView()

    expect(viewport.viewportScale.value).toBeLessThan(1)
    expect(viewport.viewportScalePercent.value).toBe(37)
    expect(viewport.viewportX.value).not.toBe(0)
    expect(viewport.viewportY.value).not.toBe(0)
    expect(clearTransientUi).toHaveBeenCalledOnce()
  })

  it('以画布中心执行分级缩放并可重置到 100%', () => {
    const canvasRef = ref({
      getBoundingClientRect: () => ({ left: 20, top: 30, width: 800, height: 600 }),
    } as HTMLElement)
    const graphNodes = ref<TestNode[]>([{ id: 'node-1', x: 0, y: 0, width: 200, height: 100 }])
    const viewport = useWorkflowCanvasViewport({
      canvasRef,
      graphNodes,
      graphNotes: ref([]),
      readBoundaryNodes: () => [],
      readNodeId: (node) => node.id,
      readNodeHeight: (node) => node.height,
      readBoundaryHeight: () => 0,
      selectNode: vi.fn(),
      shouldIgnoreWheelTarget: () => false,
      clearTransientUi: vi.fn(),
    })

    viewport.updateStageSize()
    viewport.zoomIn()
    expect(viewport.viewportScalePercent.value).toBe(120)
    viewport.zoomOut()
    expect(viewport.viewportScalePercent.value).toBe(100)
    viewport.resetView()
    expect(viewport.viewportScale.value).toBe(1)
  })

  it('连续缩小时不低于 10%', () => {
    const canvasRef = ref({
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    } as HTMLElement)
    const viewport = useWorkflowCanvasViewport({
      canvasRef,
      graphNodes: ref<TestNode[]>([{ id: 'node-1', x: 0, y: 0, width: 200, height: 100 }]),
      graphNotes: ref([]),
      readBoundaryNodes: () => [],
      readNodeId: (node) => node.id,
      readNodeHeight: (node) => node.height,
      readBoundaryHeight: () => 0,
      selectNode: vi.fn(),
      shouldIgnoreWheelTarget: () => false,
      clearTransientUi: vi.fn(),
    })

    viewport.updateStageSize()
    for (let index = 0; index < 24; index += 1) viewport.zoomOut()

    expect(viewport.viewportScale.value).toBeCloseTo(0.1)
    expect(viewport.viewportScalePercent.value).toBe(10)
  })

  it('定位超大流程时将缩放限制在 10%', () => {
    const canvasRef = ref({
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 600 }),
    } as HTMLElement)
    const viewport = useWorkflowCanvasViewport({
      canvasRef,
      graphNodes: ref<TestNode[]>([
        { id: 'node-1', x: 0, y: 0, width: 200, height: 100 },
        { id: 'node-2', x: 12000, y: 8000, width: 200, height: 100 },
      ]),
      graphNotes: ref([]),
      readBoundaryNodes: () => [],
      readNodeId: (node) => node.id,
      readNodeHeight: (node) => node.height,
      readBoundaryHeight: () => 0,
      selectNode: vi.fn(),
      shouldIgnoreWheelTarget: () => false,
      clearTransientUi: vi.fn(),
    })

    viewport.updateStageSize()
    viewport.fitView()

    expect(viewport.viewportScale.value).toBeCloseTo(0.1)
    expect(viewport.viewportScalePercent.value).toBe(10)
  })
})
