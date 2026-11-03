import {afterEach,expect,it} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import BoundarySelectionEditor from '../../../custom_nodes/metrology3d_nodes/frontend/BoundarySelectionEditor.vue'
import {changeCircleFit,newFragmentTarget,fragmentIssues,selectionIssues,robustIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/circle-form'
import {newBoundarySettings} from '../../../custom_nodes/metrology3d_nodes/frontend/boundary-form'
import {dimensionFeatureChoices,dimensionRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/dimension-form'
import {curveItems,curveStrokes} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import CurveSamples from '@/workflows/workflow-editor/point-cloud/CurveSamples.vue'
import type {CurveDisplay} from '@/workflows/workflow-editor/point-cloud/boundary-display'

afterEach(()=>{document.body.innerHTML=''})
it('pages complete recorded samples without creating a row for every support point',async()=>{
  const curve={fit_weights:Array(41).fill(1),radial_residuals:Array(41).fill(.01),angular_sectors:Array(41).fill(0),inlier_flags:Array(41).fill(true),topology:{segments:[{segment_id:'a',group_id:'g',start:0,count:21},{segment_id:'b',group_id:'g',start:21,count:20}]}} as CurveDisplay
  const w=mount(CurveSamples,{props:{curve,segment:'g',unit:'mm'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{expect(w.findAll('tbody tr')).toHaveLength(20);await w.get('[aria-label="Next page"]').trigger('click');expect(w.findAll('tbody tr')).toHaveLength(20);expect(w.get('tbody tr').text()).toContain('20 / a');await w.get('[aria-label="Next page"]').trigger('click');expect(w.findAll('tbody tr')).toHaveLength(1);expect(w.get('tbody tr').text()).toContain('40 / b');await w.setProps({segment:'a'});expect(w.text()).toContain('1 / 2');expect(w.get('tbody tr').text()).toContain('0 / a')}finally{w.unmount()}
})
it('uses stable groups without retaining stale segment IDs or inventing parameters',async()=>{
  const w=mount(BoundarySelectionEditor,{props:{modelValue:{feature_id:'boundary',segment_ids:['old']},segments:['old'],groups:['S2']},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('select').setValue('group_ids')
    const empty=w.emitted('update:modelValue')!.at(-1)![0]
    expect(empty).toEqual({feature_id:'boundary',group_ids:[]})
    await w.setProps({modelValue:empty});await flushPromises()
    await w.get('input[type=checkbox]').setValue(true)
    expect(w.emitted('update:modelValue')!.at(-1)![0]).toEqual({feature_id:'boundary',group_ids:['S2']})
  }finally{w.unmount()}
  expect(selectionIssues({feature_id:'boundary',group_ids:['S2']})).toEqual([])
  expect(selectionIssues({feature_id:'boundary',group_ids:['S2'],segment_ids:['old']})).not.toEqual([])
  const grouped=newFragmentTarget({segment_id:'S2',region:{}})
  expect(grouped.arc).toMatchObject({center:[null,null],radius_range:[null,null]})
  expect(fragmentIssues(grouped)).not.toEqual([])
  expect(grouped).not.toHaveProperty('closed')
  const robust=changeCircleFit(newBoundarySettings('fit-circle'),'angular-soft-l1')
  expect(robustIssues(robust.robust,robust.quality_policy)).not.toEqual([])
  expect(changeCircleFit(robust,'linear').robust).toBeNull()
})

it('resolves current upstream group IDs without turning absent segment IDs into strings',()=>{
  const sources={features:[{nodeId:'b',nodeTypeId:'custom.metrology3d.extract-boundary',outputPort:'features',parameters:{settings:{feature_id:'boundary',targets:[{group_id:'S2'}]}}}]}
  expect(dimensionFeatureChoices(sources)[0]).toMatchObject({segments:[],groups:['S2']})
  const p={source:{kind:'boundary',selection:{feature_id:'boundary',group_ids:['missing']}}}
  expect(dimensionRecipeValidator({node_id:'d',node_type_id:'custom.metrology3d.measure-extents',enabled:true,ui_state:{},metadata:{},parameters:{settings:p}},sources,false)).toContain('Selected fragment group is not in current boundary')
})

it.each(['angular-soft-l1','arc-length-soft-l1'])('draws %s evidence without connecting missing angles and rejects mixed representations',method=>{
  const curve={feature_id:'circle',kind:'circle',valid:true,reason:null,vertex_kind:'generated',support_point_count:4,
    points:[[1,0,0],[.98,.2,0],[-1,0,0],[-.98,-.2,0]],
    topology:{point_count:4,segments:[{segment_id:'a',group_id:'S2',start:0,count:4,closed:false,role:'open',orientation:'open'}]},
    geometry:{center:[0,0,0],normal:[0,0,1],radius:1},quality:{usable:true,metrics:{observation_id:'obs'}},
    method:{method_id:'fit-circle',method_version:1,parameters:{evaluation:{frame_id:'fixture',length_unit:'mm'},robust:{kind:method,sector_count:16}},evaluation:{frame_id:'fixture',length_unit:'mm',origin:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]}},
    radial_residuals:[0,0,0,0],fit_weights:[1,1,1,1],angular_sectors:[0,0,8,8],
    inlier_flags:[true,true,true,true],intervals:[{segment_id:'a',start_angle:null,sweep:null,pieces:[{start_angle:0,sweep:.2},{start_angle:Math.PI,sweep:.2}]}]}
  const payload={observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},geometry:{format_id:'amvision.geometry-preview.v1',curves:[curve]}}
  const policy={max_points:100,max_data_bytes:10000,max_cpu_bytes:100000,max_gpu_bytes:100000,max_canvas_pixels:100000,max_position_error:.001}
  const fitted=curveStrokes(curveItems(payload),policy).filter(v=>v.fitted)
  expect(fitted).toHaveLength(2)
  expect(fitted[0]!.points.at(-1)![1]).toBeCloseTo(Math.sin(.2))
  expect(fitted[1]!.points[0]![0]).toBeCloseTo(-1)
  const broken=structuredClone(payload)
  Object.assign(broken.geometry.curves[0]!.intervals[0]!,{start_angle:0,sweep:Math.PI+.2})
  expect(()=>curveItems(broken)).toThrow('cloud_preview_invalid')
  expect(()=>curveStrokes(curveItems(payload),{...policy,max_points:1})).toThrow('cloud_preview_capacity')
  const missing=structuredClone(payload)
  delete (missing.geometry.curves[0] as Partial<typeof curve>).fit_weights
  expect(()=>curveItems(missing)).toThrow('cloud_preview_invalid')
  const unknown=structuredClone(payload)
  unknown.geometry.curves[0]!.method.parameters.robust.kind='unknown'
  expect(()=>curveItems(unknown)).toThrow('cloud_preview_invalid')
})
