import {afterEach,expect,it,vi} from 'vitest'
import {reactive,nextTick} from 'vue'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import CloudPreviewSelector from '../../../custom_nodes/metrology3d_nodes/frontend/CloudPreviewSelector.vue'
import RoiCreationTools from '../../../custom_nodes/metrology3d_nodes/frontend/RoiCreationTools.vue'
import {createPickedRoi,createPickedSection,previewAxisRange} from '../../../custom_nodes/metrology3d_nodes/frontend/roi-creation'
import {parameterNodeContextKey,parameterInputPreviewKey} from '@/workflows/workflow-editor/parameters/editor-context'
const wrappers:ReturnType<typeof mount>[]=[]
afterEach(()=>wrappers.splice(0).forEach(w=>w.unmount()))
it('only offers the connected cloud, dispatches the selected input and clears it on reconnection',async()=>{
  const context=reactive({nodeId:'fit',cloudPorts:['cloud'],sources:{cloud:[{nodeId:'read',nodeTypeId:'read',parameters:{},outputPort:'cloud'}]}}),request=vi.fn().mockResolvedValue(undefined)
  const views=['read','other'].map(id=>({id,label:id,projectId:'p',payload:{spatial:{frame_id:'same',length_unit:'mm'}},sourceNodeId:id,sourcePort:'cloud'}))
  const w=mount(CloudPreviewSelector,{props:{modelValue:'',previews:views},global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterNodeContextKey as symbol]:()=>context,[parameterInputPreviewKey as symbol]:request}}});wrappers.push(w)
  await flushPromises();expect(w.text()).not.toContain('other');expect(w.emitted('update:modelValue')?.at(-1)).toEqual(['read'])
  await w.get('button').trigger('click');expect(request).toHaveBeenCalledWith('fit','cloud')
  context.sources.cloud=[];await nextTick();expect(w.get('button').attributes('disabled')).toBeDefined();expect(w.emitted('update:modelValue')?.at(-1)).toEqual([''])
})
it('does not choose one of multiple views or guess an unconnected input',async()=>{
  const w=mount(CloudPreviewSelector,{props:{modelValue:'',previews:[]},global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterNodeContextKey as symbol]:()=>({nodeId:'fit',cloudPorts:['cloud'],sources:{}})}}});wrappers.push(w)
  expect(w.text()).toContain('Connect a unique upstream cloud');expect(w.get('button').attributes('disabled')).toBeDefined()
})
it('ignores late input failures after reconnection without unlocking the new request',async()=>{
  const context=reactive({nodeId:'fit',cloudPorts:['cloud'],sources:{cloud:[{nodeId:'read',nodeTypeId:'read',parameters:{},outputPort:'cloud'}]}})
  const failures:((reason:Error)=>void)[]=[]
  const request=vi.fn(()=>new Promise<void>((_,reject)=>failures.push(reject)))
  const w=mount(CloudPreviewSelector,{props:{modelValue:'',previews:[]},global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterNodeContextKey as symbol]:()=>context,[parameterInputPreviewKey as symbol]:request}}});wrappers.push(w)
  await w.get('button').trigger('click')
  context.sources.cloud[0]!.nodeId='other';await nextTick()
  await w.get('button').trigger('click')
  failures[0]!(new Error('old failure'));await flushPromises()
  expect(w.text()).not.toContain('old failure');expect(w.get('button').attributes('disabled')).toBeDefined()
  failures[1]!(new Error('current failure'));await flushPromises()
  expect(w.text()).toContain('current failure');expect(w.get('button').attributes('disabled')).toBeUndefined()
})
it('discards input failure after unmount',async()=>{
  let reject!:(reason:Error)=>void
  const request=vi.fn(()=>new Promise<void>((_,fail)=>{reject=fail}))
  const w=mount(CloudPreviewSelector,{props:{modelValue:'',previews:[]},global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterNodeContextKey as symbol]:()=>({nodeId:'fit',cloudPorts:['cloud'],sources:{cloud:[{nodeId:'read',nodeTypeId:'read',parameters:{},outputPort:'cloud'}]}}),[parameterInputPreviewKey as symbol]:request}}})
  await w.get('button').trigger('click');w.unmount()
  const before=w.emitted('update:modelValue')?.length??0
  reject(new Error('late unmounted failure'));await flushPromises()
  expect(w.emitted('update:modelValue')?.length??0).toBe(before)
})
it.each(['xy','xz','yz'])('creates explicit finite candidates in %s without changing the source',plane=>{
  const roi={roi_id:'r',kind:'box'},spatial={frame_id:'input',length_unit:'um'}
  const result=createPickedRoi(roi,spatial,plane,[1,2,3],[5,8,11],-2,4)
  expect(result.frame_id).toBe('input');expect(result.length_unit).toBe('um');expect(roi).toEqual({roi_id:'r',kind:'box'})
  expect(result.geometry).toHaveProperty('rotation',[[1,0,0],[0,1,0],[0,0,1]])
})
it('creates a cylinder from a measured centre and radius candidate, never from screen pixels',()=>{
  expect(createPickedRoi({kind:'cylinder'}, {frame_id:'f',length_unit:'mm'},'xy',[1,2,9],[4,6,22],0,10).geometry).toEqual({center:[1,2,5],axis:[0,0,1],radius:5,length:10})
  expect(()=>createPickedRoi({kind:'box'},{},'xy',[1,2,3],[1,8,9],0,1)).toThrow()
  expect(()=>createPickedRoi({kind:'box'},{},'xy',[1,2,3],[4,8,9],0,0)).toThrow()
  expect(previewAxisRange({bounds:{min:[0,0,0],max:[5,6,7]}},'xz')).toEqual([0,6])
})
it.each([['xy',[0,0,1]],['xz',[0,1,0]],['yz',[1,0,0]]])('creates a bounded section in %s without guessing thickness or finite support',(plane,normal)=>{
  const roi={roi_id:'section',kind:'section-band',geometry:{thickness:.25,bounds_roi_id:'finite-box',origin:[null,null,null],normal:[null,null,null]}}
  const candidate=createPickedSection(roi,{frame_id:'source',length_unit:'mm'},String(plane),[1,2,3])
  expect(candidate.geometry).toEqual({thickness:.25,bounds_roi_id:'finite-box',origin:[1,2,3],normal})
  expect(roi.geometry.origin).toEqual([null,null,null])
  for(const geometry of [{thickness:0,bounds_roi_id:'finite-box'},{thickness:1,bounds_roi_id:''},{thickness:1,bounds_roi_id:'section'}])expect(()=>createPickedSection({...roi,geometry},{},String(plane),[1,2,3])).toThrow()
})
it('requires finite section settings and cancels picking when those settings change',async()=>{
  const payload={spatial:{frame_id:'f',length_unit:'mm'}},roi={roi_id:'band',kind:'section-band',geometry:{thickness:null,bounds_roi_id:''}}
  const w=mount(RoiCreationTools,{props:{roi,payload,scope:'run'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}});wrappers.push(w)
  expect(w.get('button').attributes('disabled')).toBeDefined()
  await w.setProps({roi:{...roi,geometry:{thickness:1,bounds_roi_id:'box'}}});await w.get('button').trigger('click')
  await w.setProps({roi:{...roi,geometry:{thickness:2,bounds_roi_id:'box'}}})
  w.vm.pick({payload:w.props('payload')!,xyz:[1,2,3]});expect(w.emitted('change')).toBeUndefined()
  await w.get('button').trigger('click');w.vm.pick({payload:w.props('payload')!,xyz:[1,2,3]});await nextTick()
  expect(w.emitted('change')?.[0]?.[0]).toMatchObject({geometry:{thickness:2,bounds_roi_id:'box',origin:[1,2,3],normal:[0,0,1]}})
  expect(w.emitted('active')?.at(-1)).toEqual([false])
})
it('cancels two-point creation on payload replacement and ignores late picks',async()=>{
  const payload={spatial:{frame_id:'f',length_unit:'mm'},bounds:{min:[0,0,-2],max:[10,10,2]}}
  const w=mount(RoiCreationTools,{props:{roi:{kind:'box',roi_id:'r'},payload,scope:'run'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}});wrappers.push(w)
  await w.get('button[title="Use input axial bounds"]').trigger('click')
  await w.findAll('button').at(-1)!.trigger('click')
  const rendered=w.props('payload')!
  w.vm.pick({payload:rendered,xyz:[1,1,0]});await nextTick()
  expect(w.text()).toContain('Select second point')
  await w.setProps({payload:{...payload}})
  w.vm.pick({payload:rendered,xyz:[5,5,0]});await nextTick()
  expect(w.emitted('change')).toBeUndefined()
  expect(w.emitted('active')?.at(-1)).toEqual([false])
  expect(w.text()).toContain('Create with two points')
})
