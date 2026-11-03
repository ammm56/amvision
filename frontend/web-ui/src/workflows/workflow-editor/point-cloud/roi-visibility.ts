import {computed, shallowRef, watch, type MaybeRefOrGetter, toValue} from 'vue'
import {roiDependencyClosure, roiGraphIssues, type RoiRecord} from './roi-graph'

export type RoiVisibility = 'visible' | 'partial' | 'hidden' | 'unavailable'

/** 显示归属落在有限叶上；共享叶和截面路径复用同一状态。 */
export function roiLeaves(rois: RoiRecord[], id: string): string[] {
  return roiDependencyClosure(rois, [id]).filter(r => r.kind === 'box' || r.kind === 'cylinder').map(r => String(r.roi_id))
}

export function roiVisibility(rois: RoiRecord[], id: string, hidden: ReadonlySet<string>): RoiVisibility {
  const leaves = roiLeaves(rois, id)
  if (!leaves.length) return 'unavailable'
  const count = leaves.filter(leaf => hidden.has(leaf)).length
  return count === 0 ? 'visible' : count === leaves.length ? 'hidden' : 'partial'
}

/** 仅属于组件会话，不写入 ROI 或发布正文。 */
export function useRoiVisibility(rois: MaybeRefOrGetter<RoiRecord[]>, scope: MaybeRefOrGetter<unknown>) {
  const hidden = shallowRef<ReadonlySet<string>>(new Set())
  const valid = computed(() => !roiGraphIssues(toValue(rois)).length)
  const state = (id: string): RoiVisibility => valid.value ? roiVisibility(toValue(rois), id, hidden.value) : 'unavailable'
  function toggle(id: string) {
    const current = state(id)
    if (current === 'unavailable') return
    const next = new Set(hidden.value)
    for (const leaf of roiLeaves(toValue(rois), id)) {
      if (current === 'visible') next.add(leaf)
      else next.delete(leaf)
    }
    hidden.value = next
  }
  function rename(previous: string, next: string) {
    if (!hidden.value.has(previous)) return
    const value = new Set(hidden.value)
    value.delete(previous); value.add(next); hidden.value = value
  }
  watch(() => toValue(scope), () => { hidden.value = new Set() }, {flush: 'sync'})
  watch(() => toValue(rois), value => {
    const ids = new Set(value.filter(r => r.kind === 'box' || r.kind === 'cylinder').map(r => String(r.roi_id)))
    const next = new Set([...hidden.value].filter(id => ids.has(id)))
    if (next.size !== hidden.value.size) hidden.value = next
  }, {deep: true})
  return {hidden, state, toggle, rename}
}
