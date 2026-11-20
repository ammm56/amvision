import { ref, watch } from 'vue'
import { readCatalogVersionNames } from '../model-display-name'

export function useCatalogVersionLabel(
  source: () => readonly [string | null | undefined, string | null | undefined, string | null | undefined],
) {
  const label = ref('')
  watch(source, async ([projectId, taskType, versionId], _, onCleanup) => {
    label.value = ''
    if (!projectId || !versionId) return
    const request = new AbortController()
    onCleanup(() => request.abort())
    try {
      const names = await readCatalogVersionNames(projectId, taskType || '', [versionId], request.signal)
      if (!request.signal.aborted) label.value = names.get(versionId) ?? ''
    } catch { /* 旧版本已删除或目录不可见时保留任务自身的信息。 */ }
  }, { immediate: true })
  return label
}
