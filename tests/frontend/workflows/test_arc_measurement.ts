import {afterEach,expect,it} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import DimensionSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DimensionSettingsEditor.vue'
import {dimensionFeatureChoices,dimensionIssues,dimensionNumericItems,newDimension} from '../../../custom_nodes/metrology3d_nodes/frontend/dimension-form'
import {measurementUnit,validateArcGeometry} from '@/workflows/workflow-editor/point-cloud/arc-display'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
import MeasurementSummary from '@/workflows/workflow-editor/point-cloud/MeasurementSummary.vue'
import {measurementItems} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {Scene,PerspectiveCamera,LineSegments} from 'three'

afterEach(()=>{document.body.innerHTML=''})
function settings(){return {...newDimension('measure-arc'),evaluation:{kind:'feature',frame_id:'fixture',length_unit:'mm'},selection:{feature_id:'circle',segment_ids:['arc']},outputs:[{component:'signed_sweep',item_id:'angle'},{component:'arc_length',item_id:'length'}],quality_policy:{policy_id:'arc',policy_version:1,rules:[{item_id:'geometry_usable',unit:'1',lower:1}]}}}
it('reuses the dimension editor and exposes radians without changing hole units',()=>{
  expect(trustedParameterEditor('custom.metrology3d.measure-arc','settings')).toBe(DimensionSettingsEditor)
  expect(dimensionIssues('measure-arc',settings())).toEqual([])
  expect(dimensionIssues('measure-arc',newDimension('measure-arc'))).not.toEqual([])
  expect(dimensionNumericItems({nodeId:'arc',nodeTypeId:'custom.metrology3d.measure-arc',parameters:{settings:settings()}})).toEqual([{item_id:'angle',unit:'rad'},{item_id:'length',unit:'mm'}])
  expect(measurementUnit({kind:'measure-arc',component:'signed_sweep'},'mm')).toBe('rad')
  expect(measurementUnit({kind:'measure-hole',component:'diameter'},'mm')).toBe('mm')
})
it('rejects invented union endpoints, traversal and ambiguous continuous selections',()=>{
  const p=settings()
  expect(dimensionIssues('measure-arc',{...p,mode:{kind:'supported-union'}})).toContain('outputs')
  expect(dimensionIssues('measure-arc',{...p,selection:{feature_id:'circle',segment_ids:['a','b']}})).toContain('arc / mode / selection')
  expect(()=>validateArcGeometry({method:{parameters:{mode:{kind:'supported-union'}}},component:'start_x'},null)).toThrow()
})
it('takes fitted segment and group identities from the connected support only',()=>{
  const source={nodeId:'fit',nodeTypeId:'custom.metrology3d.fit-circle',parameters:{settings:{feature_id:'circle',selection:{group_ids:['fragments']}}}}
  expect(dimensionFeatureChoices({features:[source]})[0]).toMatchObject({groups:['fragments'],segments:[]})
  const previewOutput={format_id:'amvision.features3d.v1',items:[{kind:'circle',feature_id:'circle',support:{topology:{segments:[{segment_id:'a',group_id:'fragments'},{segment_id:'b',group_id:'fragments'}]}}}]}
  expect(dimensionFeatureChoices({features:[{...source,previewOutput}]})[0]).toMatchObject({segments:['a','b'],groups:['fragments']})
})
it('mode switch clears incompatible quantities only in the draft and source switch closes it',async()=>{
  const value=settings(),original=JSON.stringify(value)
  const w=mount(DimensionSettingsEditor,{props:{modelValue:value,nodeType:'custom.metrology3d.measure-arc'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    const mode=[...document.querySelectorAll('select')].find(s=>s.textContent?.includes('Supported angular union'))!
    expect(mode).toBeDefined();mode.value='supported-union';mode.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(document.querySelector('input[aria-label="Signed sweep ID"]')).toBeNull()
    expect(JSON.stringify(value)).toBe(original)
    expect(w.emitted('update:modelValue')).toBeUndefined()
    await w.setProps({inputSources:{features:[{nodeId:'changed',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{}}]}})
    expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})

function arcPayload(){
  const endpoint=(point:number[],vertex_index:number)=>({point,projected:point,vertex_index,source_index:vertex_index,lineage:null})
  return {observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[0,0,0],max:[4,4,0]},measurements:{format_id:'amvision.measurement-evidence3d.v1',observation_id:'obs',frame_id:'fixture',length_unit:'mm',items:[{
    kind:'measure-arc',component:'arc_length',item_id:'length',valid:true,value:2*Math.PI,reason:null,diagnostic:null,
    geometry:{kind:'circle-arcs',circle:{center:[0,0,0],radius:4,normal:[0,0,1]},parts:[{segment_id:'arc',point_count:3,closed:false,pieces:[{start_angle:0,sweep:Math.PI/2}],signed_sweep:Math.PI/2,angular_reason:null,polyline_length:6.1229349178}],pieces:[{start_angle:0,sweep:Math.PI/2}],coverage_angle:Math.PI/2,overlap_angle:0,polyline_length:6.1229349178,signed_sweep:Math.PI/2,direction:'ccw',start:endpoint([4,0,0],0),end:endpoint([0,4,0],2)},
    support:[{role:'source',point_count:3,source_point_count:3,vertex_kind:'source',content_sha256:'a'.repeat(64),bounds:{min:[0,0,0],max:[4,4,0]},feature:{kind:'circle',feature_id:'circle'}}],
    method:{method_id:'measure-arc',method_version:1,parameters:{mode:{kind:'continuous-arc'}},evaluation:{frame_id:'fixture',length_unit:'mm',origin:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]}},quality:{usable:true,metrics:{observation_id:'obs',items:[]}},
  }]}}
}

it('links measured segments through the existing feature selection and separates both lengths',async()=>{
  const w=mount(MeasurementSummary,{props:{items:measurementItems(arcPayload()),unit:'mm',selected:'length'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    expect(w.text()).toContain('6.2832 / 6.1229 mm')
    expect(w.text()).toContain('Counterclockwise')
    await w.findAll('button').find(b=>b.text()==='arc')!.trigger('click')
    expect(w.emitted('select-segment')).toEqual([['circle','arc']])
    await w.setProps({selected:''})
    expect(w.text()).not.toContain('Counterclockwise')
  }finally{w.unmount()}
})

it('renders arc model and direction without crossing gaps and releases selected evidence',()=>{
  const scene=new Scene(),policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:10000,max_position_error:.01}
  const overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[0,0,0],policy,()=>{},()=>{},e=>{throw e})
  try{
    const payload=arcPayload()
    overlay.update({payload,selectedMeasurement:'length'})
    const lines:LineSegments[]=[];scene.traverse(o=>{if(o instanceof LineSegments)lines.push(o)})
    const arrow=lines.at(-1)!.geometry.getAttribute('position')
    expect(arrow.count).toBe(4)
    expect([arrow.getX(1),arrow.getY(1),arrow.getZ(1)]).toEqual([0,4,0])
    expect(arrow.getX(0)).toBeGreaterThan(0)
    overlay.update({payload,selectedMeasurement:'length',selectedCurve:'circle',selectedSegment:'arc'})
    let selected=0;scene.traverse(o=>{if(o.userData.curve?.featureId==='circle'&&o.userData.curve?.segmentId==='arc')selected++})
    expect(selected).toBe(1)
    expect(overlay.focus('feature')).not.toBeNull()
    const broken=structuredClone(payload);broken.measurements.items[0]!.geometry.end.source_index=-1
    expect(()=>overlay.update({payload:broken,selectedMeasurement:'length'})).toThrow()
    expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
    overlay.update({payload,selectedMeasurement:'length'})
    expect(rendererUsage().gpuBytes).toBeGreaterThan(0)
  }finally{overlay.dispose()}
  expect(scene.children).toHaveLength(0)
  expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
})
