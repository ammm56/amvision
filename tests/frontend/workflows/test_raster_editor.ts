import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import RasterSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RasterSettingsEditor.vue'
import {newRasterInput,newProjection,rasterValid} from '../../../custom_nodes/metrology3d_nodes/frontend/raster-form'
import {object,put} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML=''})
const valid=()=>({kind:'file',file_format:'npy',raster:{...object(newRasterInput().raster),width:4,height:3,dtype:'float32',calibration_id:'camera',calibration_revision:'r1',spatial:{length_unit:'mm',unit_source:'configuration',frame_id:'fixture',axes:{handedness:'right',axis_labels:['X','Y','Z'],definition_source:'configuration'}},projection:{kind:'rectified-pinhole',depth_kind:'axial-z',fx:2,fy:3,cx:1,cy:1},value_scale:1,value_offset:0,position_dtype:'float32'}})
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!
it('validates three projections and rejects hidden conflicting calibration',()=>{
  expect(trustedParameterEditor('custom.metrology3d.raster-to-cloud','settings')).toBe(RasterSettingsEditor)
  expect(rasterValid(newRasterInput())).toBe(false)
  expect(rasterValid(newRasterInput('local-array'))).toBe(true)
  expect(rasterValid({...valid(),kind:'local-array'})).toBe(false)
  expect(rasterValid(valid())).toBe(true)
  expect(rasterValid(put(valid(),'raster.projection.depth_kind','ray-range'))).toBe(true)
  const height=put(valid(),'raster.projection',{kind:'orthographic-height',origin:[0,0,0],column_direction:[1,0,0],row_direction:[0,1,0],height_direction:[0,0,1],column_step:.1,row_step:.2})
  expect(rasterValid(height)).toBe(true)
  for(const [path,value] of [['raster.projection.row_direction',[1,0,0]],['raster.width',0],['raster.dtype','float16'],['raster.validity.invalid_raw_values',[.1]],['raster.validity.minimum',NaN],['raster.width',1e10]])expect(rasterValid(put(height,path as string,value))).toBe(false)
  expect(rasterValid({...valid(),file_format:'png'})).toBe(false)
  expect(rasterValid(put({...valid(),file_format:'tiff'},'raster.dtype','float64'))).toBe(false)
  expect(newProjection('orthographic-height')).not.toHaveProperty('fx')
})
it('applies fixed file calibration; switches atomically and discards cancelled or stale drafts',async()=>{
  const w=mount(RasterSettingsEditor,{props:{modelValue:valid(),nodeType:'custom.metrology3d.raster-to-cloud'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('button').trigger('click');await flushPromises();expect(button('Apply').disabled).toBe(false)
    button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![0]![0]).toEqual(valid())
    await w.get('button').trigger('click');await flushPromises()
    const source=document.querySelector<HTMLSelectElement>('[aria-label="Input source"]')!;source.value='local-array';source.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(document.querySelector('[aria-label="Projection model"]')).toBeNull()
    button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![1]![0]).toEqual({kind:'local-array'})
    await w.get('button').trigger('click');await flushPromises();button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(2)
    await w.get('button').trigger('click');await flushPromises();await w.setProps({inputSources:{file:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');await flushPromises();await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.setProps({disabled:false});await w.get('button').trigger('click');await flushPromises();w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})
