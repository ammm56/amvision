import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {ref} from 'vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {Scene,PerspectiveCamera,Points,LineSegments} from 'three'
import fixture from './fixtures/envelope.json'
import BoundaryEditor from '../../../custom_nodes/metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import DimensionEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DimensionSettingsEditor.vue'
import {boundaryIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/boundary-form'
import {dimensionIssues,dimensionFeatureChoices} from '../../../custom_nodes/metrology3d_nodes/frontend/dimension-form'
import {newEnvelope} from '../../../custom_nodes/metrology3d_nodes/frontend/envelope-form'
import {curveItems,curveStrokes} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import {measurementItems} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import MeasurementSummary from '@/workflows/workflow-editor/point-cloud/MeasurementSummary.vue'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({__esModule:true,default:{name:'TestCloudViewer',props:['payload','allowPick'],emits:['candidate'],template:'<div />'}}))
const plugins=[createI18n({legacy:false,locale:'en-US'})]
const policy={max_points:100,max_data_bytes:100000,max_cpu_bytes:1000000,max_gpu_bytes:1000000,max_canvas_pixels:10000,max_position_error:.001}
afterEach(()=>{document.body.innerHTML=''})

it('shows the statistical method and contact evidence instead of implying raw extrema',async()=>{
  const items=measurementItems(fixture.payload)
  const w=mount(MeasurementSummary,{props:{items,unit:'mm',selected:items[0]!.item_id},global:{plugins}})
  try{
    expect(w.text()).toContain('Visible envelope · robust profile spans')
    expect(w.text()).toContain('0.02 / 0.98 · linear')
    expect(w.text()).toContain('Statistical contacts')
    expect(w.text()).toContain('Cell-center interpolation / cell-edge estimates')
    expect(w.text()).toContain('u-min')
    await w.setProps({selected:''})
    expect(w.text()).not.toContain('Statistical contacts')
    await w.setProps({items:[{...items[0]!,kind:'height-query',method:{method_id:'height-query'}}],selected:items[0]!.item_id})
    expect(w.text()).not.toContain('Statistical contacts')
  }finally{w.unmount()}
})

it('accepts real Python contracts without Delaunay settings and without guessed defaults',()=>{
  expect(boundaryIssues('extract-boundary',fixture.boundary)).toEqual([])
  expect(dimensionIssues('measure-extents',fixture.dimension)).toEqual([])
  expect(newEnvelope()).toMatchObject({grid:{step:null},selection:{connectivity:null},profiles:{min_observed_length:null}})
  expect(boundaryIssues('extract-boundary',{...fixture.boundary,surface:{alpha_radius:1}})).toContain('surface')
  const p=structuredClone(fixture.boundary);p.method.envelope.profiles.foreground='below'
  expect(boundaryIssues('extract-boundary',p)).toContain('foreground / order')
  expect(dimensionFeatureChoices({features:[{nodeId:'edge',nodeTypeId:'custom.metrology3d.extract-boundary',parameters:{settings:fixture.boundary}}]})[0]!.segments).toEqual(['u-min','u-max','v-min','v-max'])
})
it('reads statistical contacts from actual Python evidence and rejects fabricated rank or indices',()=>{
  measurementItems(fixture.payload).forEach((item,i)=>expect(item.value).toBeCloseTo([4,6][i]!,12))
  for(const kind of ['rank','index','method']){
    const p=structuredClone(fixture.payload),s=p.measurements.items[0]!.geometry!.contacts[0]!.statistic
    if(kind==='rank')s.ranks=[1000,1001]
    if(kind==='index')s.vertex_indices=[1000,1001]
    if(kind==='method')s.method='nearest'
    expect(()=>measurementItems(p)).toThrow('cloud_preview_invalid')
  }
})
it('retains isolated stations as markers and never bridges profile breaks',()=>{
  const p=structuredClone(fixture.payload),curve=p.geometry.curves[0]!
  ;(curve.topology!.segments[0]!.profile! as {breaks:number[]}).breaks=[1,2]
  curve.profile_kinds[0]=2
  const strokes=curveStrokes(curveItems(p),policy).filter(s=>s.segmentId==='u-min')
  expect(strokes.filter(s=>s.markers).flatMap(s=>s.points)).toHaveLength(6)
  expect(strokes.filter(s=>!s.markers).flatMap(s=>s.points)).toHaveLength(6)
  expect(strokes.find(s=>s.markers&&s.estimate==='edge')!.points).toEqual([curve.points[0]])
  const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{overlay.update({payload:p});let markers=0,lines=0;scene.traverse(o=>{if(o instanceof Points)markers++;if(o instanceof LineSegments)lines++});expect(markers).toBeGreaterThan(0);expect(lines).toBeGreaterThan(0)}finally{overlay.dispose()}
  expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})
it('shows only relevant boundary controls and invalidates drafts on connection changes',async()=>{
  const w=mount(BoundaryEditor,{props:{modelValue:fixture.boundary,nodeType:'custom.metrology3d.extract-boundary'},attachTo:document.body,global:{plugins}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    expect(document.body.textContent).toContain('Grid counts U/V')
    expect(document.body.textContent).not.toContain('Maximum edge length')
    expect(document.body.textContent).not.toContain('Require complete closed loop')
    await w.setProps({inputSources:{pose:[]}})
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(w.emitted('update:modelValue')).toBeUndefined()
  }finally{w.unmount()}
})
it('locks statistical dimensions to inherited evaluation and all four roles',async()=>{
  const w=mount(DimensionEditor,{props:{modelValue:fixture.dimension,nodeType:'custom.metrology3d.measure-extents',inputSources:{features:[{nodeId:'edge',nodeTypeId:'custom.metrology3d.extract-boundary',parameters:{settings:fixture.boundary}}]}},attachTo:document.body,global:{plugins}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    expect(document.body.textContent).toContain('Evaluation: inherited from boundary')
    expect(document.querySelector<HTMLInputElement>('input[aria-label="Lower quantile"]')!.value).toBe('0.02')
    const checks=[...document.querySelectorAll<HTMLInputElement>('.segments input')]
    expect(checks).toHaveLength(4);expect(checks.every(c=>c.checked&&c.disabled)).toBe(true)
  }finally{w.unmount()}
})
it('moves only the explicit seed window in the matching current pose and ignores late picks',async()=>{
  const state=ref({runId:'one',succeeded:true})
  const payload={spatial:{frame_id:'fixture',length_unit:'mm'},geometry:{frame:{state:'found',pose_id:'datum',target_frame_id:'part',transform:{matrix:[[0,1,0,-2],[0,0,1,-3],[1,0,0,-1],[0,0,0,1]]}}}}
  const w=mount(BoundaryEditor,{props:{modelValue:fixture.boundary,nodeType:'custom.metrology3d.extract-boundary'},attachTo:document.body,global:{plugins,provide:{[parameterCloudPreviewsKey as symbol]:()=>[{id:'v',label:'Cloud',projectId:'p',payload}],[parameterPreviewStateKey as symbol]:()=>state.value}}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    const select=[...document.querySelectorAll('select')].find(s=>[...s.options].some(o=>o.value==='v'))!;select.value='v';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    const cloud=w.findComponent({name:'TestCloudViewer'});expect(cloud.props('allowPick')).toBe(true)
    const lo=fixture.boundary.method.envelope.selection.seed_min,hi=fixture.boundary.method.envelope.selection.seed_max
    const targetU=(lo[0]!+hi[0]!)/2+.1,targetV=(lo[1]!+hi[1]!)/2
    cloud.vm.$emit('candidate',{payload:cloud.props('payload'),xyz:[1,targetU+2,targetV+3]});await flushPromises()
    const input=()=>document.querySelector<HTMLInputElement>('[aria-label="Seed minimum U/V 1"]')!
    expect(Number(input().value)).toBeCloseTo(lo[0]!+.1,12);expect(w.emitted('update:modelValue')).toBeUndefined()
    state.value={runId:'two',succeeded:false};await flushPromises()
    cloud.vm.$emit('candidate',{payload,xyz:[999,999,999]});await flushPromises();expect(Number(input().value)).toBeCloseTo(lo[0]!+.1,12)
    await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})
