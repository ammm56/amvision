import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {reactive} from 'vue'
import PoseSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/PoseSettingsEditor.vue'
import {parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML=''})
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!
it.each(['invert-pose','compose-pose'])('registers %s, applies only identity, rejects bad IDs and closes on switching',async kind=>{
  expect(trustedParameterEditor('custom.metrology3d.'+kind,'settings')).toBe(PoseSettingsEditor)
  const w=mount(PoseSettingsEditor,{props:{modelValue:{pose_id:'result'},nodeType:'custom.metrology3d.'+kind},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('button').trigger('click');await flushPromises();expect(button('Apply').disabled).toBe(false)
    button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![0]).toEqual([{pose_id:'result'}])
    await w.setProps({modelValue:{pose_id:'bad id'}});await w.get('button').trigger('click');expect(button('Apply').disabled).toBe(true)
    button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(1)
    await w.get('button').trigger('click');await w.setProps({inputSources:{first:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})
it('shows actual execution order and rejects only fresh known coordinate mismatches',async()=>{
  const state=reactive({runId:'one',succeeded:true})
  const source=(nodeId:string,source_frame_id:string,target_frame_id:string)=>({nodeId,nodeTypeId:'custom.metrology3d.build-frame',parameters:{settings:{pose_id:nodeId}},previewOutput:{source_frame_id,target_frame_id,state:'found'}})
  const w=mount(PoseSettingsEditor,{props:{modelValue:{pose_id:'combined'},nodeType:'custom.metrology3d.compose-pose',inputSources:{first:[source('a','source','part')],second:[source('b','other','tool')]}},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterPreviewStateKey as symbol]:()=>state}}})
  try{
    await w.get('button').trigger('click');await flushPromises();expect(document.body.textContent).toContain('first → second');expect(document.body.textContent).toContain('source → part');expect(button('Apply').disabled).toBe(true)
    state.succeeded=false;await flushPromises();expect(document.body.textContent).not.toContain('source → part');expect(document.querySelector('[role=alert]')).toBeNull()
    await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})
