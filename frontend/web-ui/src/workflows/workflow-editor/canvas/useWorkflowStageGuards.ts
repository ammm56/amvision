const stagePointerIgnoreSelector = [
  '.workflow-graph-node',
  '.workflow-graph-boundary-node',
  '.workflow-graph-floating-panel',
  '.workflow-graph-minimap',
  '.workflow-graph-minimap-toggle',
  '.workflow-graph-context-menu',
  '.workflow-node-picker',
  '.workflow-graph-link',
  '.workflow-graph-link-hit-area',
  '.workflow-graph-link-handle',
  '.workflow-graph-port',
].join(', ')

const stageWheelIgnoreSelector = [
  'input',
  'textarea',
  'select',
  'button',
  '.workflow-graph-floating-panel',
  '.workflow-graph-minimap',
  '.workflow-graph-minimap-toggle',
  '.workflow-graph-context-menu',
  '.workflow-node-picker',
  '.image-viewer',
].join(', ')

export function useWorkflowStageGuards() {
  function shouldIgnoreStagePointer(target: EventTarget | null): boolean {
    return target instanceof Element && Boolean(target.closest(stagePointerIgnoreSelector))
  }

  function shouldIgnoreStageWheelTarget(target: EventTarget | null): boolean {
    return target instanceof Element && Boolean(target.closest(stageWheelIgnoreSelector))
  }

  return {
    shouldIgnoreStagePointer,
    shouldIgnoreStageWheelTarget,
  }
}
