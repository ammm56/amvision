import {afterEach, expect, it, vi} from 'vitest'
import {flushPromises, mount} from '@vue/test-utils'
import {reactive} from 'vue'
import {createI18n} from 'vue-i18n'
import DenoiseSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DenoiseSettingsEditor.vue'
import {denoiseValid, newDenoise} from '../../../custom_nodes/metrology3d_nodes/frontend/denoise-form'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML=''})
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===name)!
it('requires explicit finite parameters without manufacturing defaults',()=>{
  expect(denoiseValid(newDenoise('radius'))).toBe(false)
  expect(denoiseValid(newDenoise('statistical'))).toBe(false)
  expect(denoiseValid({kind:'radius',radius:1,min_neighbors:2})).toBe(true)
  expect(denoiseValid({kind:'radius',radius:0,min_neighbors:2})).toBe(false)
  expect(denoiseValid({kind:'statistical',neighbors:1.5,std_ratio:2})).toBe(false)
  expect(denoiseValid({kind:'statistical',neighbors:3,std_ratio:Infinity})).toBe(false)
})
it('supports reactive drafts, discards other-method fields and cancels on task/source changes',async()=>{
  const value=reactive({kind:'statistical',neighbors:3,std_ratio:1})
  const w=mount(DenoiseSettingsEditor,{props:{modelValue:value,nodeType:'custom.metrology3d.denoise-cloud'},attachTo:document.body,
    global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await w.get('button').trigger('click');await flushPromises()
  expect(button('Apply').disabled).toBe(false)
  const select=document.querySelector('select')!;select.value='radius';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
  expect(button('Apply').disabled).toBe(true)
  const inputs=[...document.querySelectorAll<HTMLInputElement>('input')];expect(inputs.map(i=>i.value)).toEqual(['',''])
  // 与真实逐字段操作一致，父组件先接收当前字段再编辑下一字段。
  for (const [index, input] of inputs.entries()) {
    input.value=String(index+1)
    input.dispatchEvent(new Event('input',{bubbles:true}))
    await flushPromises()
  }
  button('Apply').click();await flushPromises()
  expect(w.emitted('update:modelValue')![0]![0]).toEqual({kind:'radius',radius:1,min_neighbors:2})
  expect(value).toEqual({kind:'statistical',neighbors:3,std_ratio:1})
  await w.get('button').trigger('click');await flushPromises();button('Cancel').click();await flushPromises()
  expect(w.emitted('update:modelValue')).toHaveLength(1)
  await w.get('button').trigger('click');await w.setProps({inputSources:{cloud:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
  w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
})
