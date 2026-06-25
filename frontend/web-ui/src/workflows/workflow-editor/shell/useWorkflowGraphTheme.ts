import { computed } from 'vue'

export interface WorkflowGraphThemeOptions<TTheme extends string> {
  readTheme: () => TTheme
  setTheme: (theme: TTheme) => void
  lightTheme: TTheme
  darkTheme: TTheme
  clearContextMenu: () => void
}

export function useWorkflowGraphTheme<TTheme extends string>(options: WorkflowGraphThemeOptions<TTheme>) {
  const graphTheme = computed(() => options.readTheme())

  function toggleGraphTheme(): void {
    options.setTheme(graphTheme.value === options.darkTheme ? options.lightTheme : options.darkTheme)
    options.clearContextMenu()
  }

  return {
    graphTheme,
    toggleGraphTheme,
  }
}
