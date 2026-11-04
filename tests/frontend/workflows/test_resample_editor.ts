import {afterEach, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import ResampleSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/ResampleSettingsEditor.vue'
import {newResample,resampleValid} from '../../../custom_nodes/metrology3d_nodes/frontend/resample-form'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML=''})
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===name)!
it('requires explicit phase and units, separates measured representative from centroid',()=>{
  for(const kind of ['stride','voxel-representative','voxel-centroid'])expect(resampleValid(newResample(kind))).toBe(false)
  expect(resampleValid({kind:'stride',every_k_points:3,offset:2})).toBe(true)
  expect(resampleValid({kind:'stride',every_k_points:3,offset:3})).toBe(false)
  const p={kind:'voxel-centroid',voxel_size:1,grid_origin:[0,0,0],frame_id:'sensor',length_unit:'mm',max_position_error:1e-5,attributes:'positions-only'}
  expect(resampleValid(p)).toBe(true)
  expect(resampleValid({...p,grid_origin:[0,0,NaN]})).toBe(false)
  expect(resampleValid({...p,attributes:'average-all'})).toBe(false)
  expect(resampleValid({...p,max_position_error:0})).toBe(false)
})
it('discards method fields and uncommitted drafts on cancel, source changes and unmount',async()=>{
  const value={kind:'stride',every_k_points:3,offset:0}
  const w=mount(ResampleSettingsEditor,{props:{modelValue:value,nodeType:'custom.metrology3d.resample-cloud'},attachTo:document.body,
    global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await w.get('button').trigger('click');await flushPromises()
  expect(button('Apply').disabled).toBe(false)
  const select=document.querySelector('select')!;select.value='voxel-centroid';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
  expect(button('Apply').disabled).toBe(true)
  expect(document.body.textContent).toContain('Generated points')
  expect([...document.querySelectorAll('input')].map(i=>i.value)).toEqual(['','','','','',''])
  button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.get('button').trigger('click');await flushPromises();button('Apply').click();await flushPromises()
  expect(w.emitted('update:modelValue')![0]![0]).toEqual(value)
  await w.get('button').trigger('click');await w.setProps({inputSources:{cloud:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
})
