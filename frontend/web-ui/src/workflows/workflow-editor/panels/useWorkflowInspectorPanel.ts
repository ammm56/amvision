import { ref } from 'vue'

export function useWorkflowInspectorPanel() {
  const inspectorCollapsed = ref(false)

  function collapseInspector(): void {
    inspectorCollapsed.value = true
  }

  function expandInspector(): void {
    inspectorCollapsed.value = false
  }

  return {
    inspectorCollapsed,
    collapseInspector,
    expandInspector,
  }
}
