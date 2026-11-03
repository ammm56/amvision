import {effectScope, nextTick, ref} from 'vue'
import {expect, it} from 'vitest'
import {roiLeaves, useRoiVisibility} from '@/workflows/workflow-editor/point-cloud/roi-visibility'
import type {RoiRecord} from '@/workflows/workflow-editor/point-cloud/roi-graph'

const roi=(id:string,kind='box',geometry:Record<string,unknown>={})=>({roi_id:id,kind,geometry,frame_id:'source',length_unit:'mm'})
const graph=()=>[roi('all','union',{roi_ids:['a','nested']}),roi('nested','union',{roi_ids:['a','b']}),roi('slice','section-band',{bounds_roi_id:'nested'}),roi('a'),roi('b')]

it('shares leaf visibility across unions and sections without changing membership',()=>{
  const scope=effectScope(),rois=ref<RoiRecord[]>(graph()),before=JSON.stringify(rois.value)
  const view=scope.run(()=>useRoiVisibility(rois,()=>1))!
  expect(roiLeaves(rois.value,'all')).toEqual(['a','b'])
  view.toggle('a')
  expect(view.state('all')).toBe('partial');expect(view.state('slice')).toBe('partial')
  view.toggle('slice');expect(view.hidden.value.size).toBe(0)
  view.toggle('all');expect(view.state('nested')).toBe('hidden')
  view.toggle('b');expect(view.state('all')).toBe('partial')
  expect(JSON.stringify(rois.value)).toBe(before);scope.stop()
})

it('keeps explicit rename, removes deleted leaves, and isolates every scope',async()=>{
  const scope=effectScope(),rois=ref<RoiRecord[]>([roi('a')]),key=ref('run-1')
  const view=scope.run(()=>useRoiVisibility(rois,key))!
  view.toggle('a');rois.value=[roi('renamed')];view.rename('a','renamed');await nextTick()
  expect(view.state('renamed')).toBe('hidden')
  rois.value.push(roi('new'));await nextTick();expect(view.state('new')).toBe('visible')
  rois.value=[roi('new')];await nextTick();expect(view.hidden.value.size).toBe(0)
  view.toggle('new');key.value='run-2';expect(view.hidden.value.size).toBe(0)
  scope.stop()
})

it('does not accept hidden cyclic or missing dependencies',()=>{
  const scope=effectScope(),rois=ref<RoiRecord[]>(graph()),view=scope.run(()=>useRoiVisibility(rois,()=>1))!
  view.toggle('all');rois.value.push(roi('bad','union',{roi_ids:['bad']}))
  expect(view.state('all')).toBe('unavailable');view.toggle('all');expect(view.hidden.value.size).toBe(2)
  scope.stop()
})
