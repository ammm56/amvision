import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import ProfileSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/ProfileSettingsEditor.vue'
import { newDisplacement, newProfileInput, profilesValid } from '../../../custom_nodes/metrology3d_nodes/frontend/profile-form'
import { object, put } from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import { trustedParameterEditor } from '@/workflows/workflow-editor/parameters/trusted-editors'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue', () => ({ default: { template: '<div />' } }))
afterEach(() => { document.body.innerHTML = '' })
const valid = () => ({kind:'file',file_format:'npz',has_validity:false,profiles:{...object(newProfileInput().profiles),
  point_count:6,profile_count:4,dtype:'float32',position_dtype:'float64',calibration_id:'scanner',calibration_revision:'r1',
  spatial:{length_unit:'mm',unit_source:'configuration',frame_id:'fixture',axes:{handedness:'right',axis_labels:['X','Y','Z'],definition_source:'configuration'}},
  origin:[10,20,30],x_direction:[.6,.8,0],scan_direction:[0,0,1],height_direction:[.8,-.6,0],displacement:{kind:'fixed-step',origin_line_id:5,step:2}}})
const button = (text: string) => [...document.querySelectorAll('button')].find(b => b.textContent?.trim() === text)!

it('validates explicit scan definitions without guessing physical parameters', () => {
  expect(trustedParameterEditor('custom.metrology3d.profiles-to-cloud','settings')).toBe(ProfileSettingsEditor)
  expect(profilesValid(newProfileInput())).toBe(false)
  expect(profilesValid(newProfileInput('local-array'))).toBe(true)
  expect(profilesValid({...valid(),kind:'local-array'})).toBe(false)
  expect(profilesValid(valid())).toBe(true)
  expect(profilesValid(put(valid(),'profiles.displacement',{kind:'encoder-positions',dtype:'float64',scale:.5,origin:10}))).toBe(true)
  for (const [path,value] of [['profiles.point_count',0],['profiles.profile_count',2.5],['profiles.dtype','uint8'],['profiles.displacement.step',0],['profiles.displacement.origin_line_id',-1],['profiles.displacement.origin_line_id',Number.MAX_SAFE_INTEGER+1],['profiles.scan_direction',[.6,.8,0]],['profiles.origin',[0,NaN,0]],['has_validity',1]]) {
    expect(profilesValid(put(valid(),path as string,value))).toBe(false)
  }
  expect(newDisplacement('encoder-positions')).not.toHaveProperty('step')
  expect(profilesValid({...valid(),extra:1})).toBe(false)
})

it('switches input and displacement atomically and rejects stale or cancelled edits', async () => {
  const w=mount(ProfileSettingsEditor,{props:{modelValue:valid(),nodeType:'custom.metrology3d.profiles-to-cloud'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try {
    await w.get('button').trigger('click'); await flushPromises()
    expect(button('Apply').disabled).toBe(false)
    const method=document.querySelector<HTMLSelectElement>('[aria-label="Scan displacement"]')!
    method.value='encoder-positions';method.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(button('Apply').disabled).toBe(true)
    button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()
    await w.get('button').trigger('click');await flushPromises();button('Apply').click();await flushPromises()
    expect(w.emitted('update:modelValue')![0]![0]).toEqual(valid())
    await w.get('button').trigger('click');await flushPromises()
    const source=document.querySelector<HTMLSelectElement>('[aria-label="Input source"]')!
    source.value='local-array';source.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(document.querySelector('[aria-label="Scan displacement"]')).toBeNull()
    button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![1]![0]).toEqual({kind:'local-array'})
    for(const update of [{inputSources:{file:[]}}, {nodeType:'other'}, {disabled:true}]) {
      await w.get('button').trigger('click');await flushPromises();await w.setProps(update)
      expect(document.querySelector('[role=dialog]')).toBeNull()
    }
    await w.setProps({disabled:false});await w.get('button').trigger('click');await flushPromises();w.unmount()
    expect(document.querySelector('[role=dialog]')).toBeNull()
  } finally { w.unmount() }
})
