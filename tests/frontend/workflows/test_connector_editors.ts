import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import { i18n } from '@/platform/i18n'
import {useProjectStore} from '@/app/stores/project.store'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import PinLayoutEditor from '../../../custom_nodes/connector_nodes/frontend/PinLayoutEditor.vue'
import MeasurementEditor from '../../../custom_nodes/connector_nodes/frontend/MeasurementEditor.vue'
import CalibrationPointsEditor from '@/workflows/workflow-editor/components/WorkflowCalibrationPointsEditor.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import SamplingDiagnostic from '@/workflows/workflow-editor/components/WorkflowSamplingDiagnostic.vue'
import { createPinLayout, hydratePinLayout, generatePins, inferPinArray, replacePinArray, isPinLayoutValid, samePinLayout, type PinLayout } from '../../../custom_nodes/connector_nodes/frontend/pin-layout'
import { buildMeasurementBatch, batchKinds, invalidMeasurementReferences } from '../../../custom_nodes/connector_nodes/frontend/measurement-items'

let wrapper: VueWrapper | undefined
const resources=vi.hoisted(()=>({list:vi.fn(),image:vi.fn()}))
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service',async(importOriginal)=>({...await importOriginal<object>(),listMeasurementResources:resources.list,readMeasurementResourceImage:resources.image}))
afterEach(() => { wrapper?.unmount(); wrapper = undefined; document.body.innerHTML = '';vi.unstubAllGlobals();vi.clearAllMocks() })
describe('PIN layout editor', () => {
  it('infers only regular arrays and preserves empty positions and endpoint definitions by ID',()=>{
    const pins=generatePins(2,8,[254.489123,306.194789],85.55791,50,25,'normal')
    pins[4]!.expected_present=false
    pins[0]!.endpoint_pairs=[{first_id:'tip',second_id:'root',sampling_type:'length',center_offset:[1.123456789,2]}]
    const inferred=inferPinArray(pins)!
    expect(inferred).toMatchObject({rows:2,columns:8,x:254.489123,y:306.194789,stagger:25})
    const replaced=replacePinArray(pins,generatePins(2,7,[200,300],80,50,25,'other'))
    expect(replaced[4]!.expected_present).toBe(false)
    expect(replaced[0]!.pin_type).toBe('normal')
    expect(replaced[0]!.endpoint_pairs).toEqual(pins[0]!.endpoint_pairs)
    expect(replaced[0]!.endpoint_pairs).not.toBe(pins[0]!.endpoint_pairs)
    pins[2]!.center[0]+=1
    expect(inferPinArray(pins)).toBeNull()
  })
  it('previews array replacement and restores its previous state without committing',async()=>{
    const layout=createPinLayout();layout.pins=generatePins(1,3,[100,100],50,50,0,'normal');layout.pins[1]!.expected_present=false
    wrapper=mount(PinLayoutEditor,{props:{modelValue:layout},global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.pin-edit').trigger('click')
    const dialog=wrapper.getComponent(ConfirmDialog)
    await dialog.get('input[aria-label="Columns"]').setValue('2')
    await dialog.findAll('button').find(b=>/^(生成排列|Generate array)/.test(b.text()))!.trigger('click')
    expect(dialog.text()).toContain('R1P03')
    expect(dialog.findAll('.pin-table tbody tr')).toHaveLength(3)
    await dialog.findAll('button').find(b=>/^(替换草稿排列|Replace draft array)/.test(b.text()))!.trigger('click')
    expect(dialog.findAll('.pin-table tbody tr')).toHaveLength(2)
    await dialog.findAll('button').find(b=>/^(恢复替换前排列|Restore previous array)/.test(b.text()))!.trigger('click')
    expect(dialog.findAll('.pin-table tbody tr')).toHaveLength(3)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    dialog.vm.$emit('confirm');await nextTick()
    expect((wrapper.emitted('update:modelValue')![0]![0] as PinLayout).pins).toEqual(hydratePinLayout(layout).pins)
  })
  it('allows an empty type list to be repaired without throwing or adding invalid scans',async()=>{
    const layout=createPinLayout();layout.pins=generatePins(1,1,[100,100],50,50,0,'normal');layout.types=[]
    wrapper=mount(PinLayoutEditor,{props:{modelValue:layout},global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.pin-edit').trigger('click')
    const dialog=wrapper.getComponent(ConfirmDialog)
    expect(dialog.props('confirmDisabled')).toBe(true)
    const buttons=dialog.findAll('button')
    const addType=buttons.find(button=>button.text()==='添加采样类型' || button.text()==='Add sampling type')!
    expect(buttons.filter(button=>/^(生成排列|Generate array|添加端点扫描|Add endpoint scan|添加搜索带|Add search band)/.test(button.text())).every(button=>button.attributes('disabled')!==undefined)).toBe(true)
    await addType.trigger('click')
    expect(dialog.findAll('input').some(input=>(input.element as HTMLInputElement).value==='type-1')).toBe(true)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
  it('opens valid current-schema documents with omitted defaults',async()=>{
    const value={reference_id:'reference',pins:[{pin_id:'P1',row_id:'R1',pin_type:'normal',center:[100,100]}],types:[{type_id:'normal'}]} as unknown as PinLayout
    const hydrated=hydratePinLayout(value)
    expect(isPinLayoutValid(hydrated)).toBe(true)
    expect(hydrated.pins[0]!.expected_present).toBe(true)
    expect(samePinLayout(value,hydrated)).toBe(true)
    expect(value.types[0]!.scan_lines).toBeUndefined()
    wrapper=mount(PinLayoutEditor,{props:{modelValue:value},global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.pin-edit').trigger('click')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(false)
  })
  it('rejects removed diagnostic IDs and does not reuse profiles after sampling edits', () => {
    const layout=createPinLayout();layout.pins=generatePins(1,2,[100,100],50,50,0,'normal')
    const snapshot=JSON.parse(JSON.stringify(layout))
    expect(samePinLayout(snapshot,{...layout,candidate_bands:[],diagnostic_pin_id:null})).toBe(true)
    layout.types[0]!.gradient_threshold=.1
    expect(samePinLayout(snapshot,layout)).toBe(false)
    layout.diagnostic_pin_id='absent'
    expect(isPinLayoutValid(layout)).toBe(false)
  })
  it('keeps fixed IDs across staggered rows and designed empty positions', () => {
    const layout = createPinLayout()
    layout.pins = generatePins(2, 8, [100,200], 50, 60, 25, 'normal')
    expect(layout.pins[8]).toMatchObject({pin_id:'R2P01', center:[125,260]})
    layout.pins[3].expected_present = false
    expect(layout.pins[4].pin_id).toBe('R1P05')
    expect(isPinLayoutValid(layout)).toBe(true)
    layout.pins[4].pin_id = layout.pins[3].pin_id
    expect(isPinLayoutValid(layout)).toBe(false)
    expect(() => generatePins(10, 200, [0,0], 1, 1, 0, 'normal')).toThrow()
  })
  it('does not commit edits on Cancel and emits one complete edit on Apply', async () => {
    const layout = createPinLayout(); layout.pins = generatePins(1,2,[100,100],50,50,0,'normal')
    wrapper = mount(PinLayoutEditor, {attachTo:document.body, props:{modelValue:layout}, global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.pin-edit').trigger('click')
    const change = async (value:string) => {
      const input = document.body.querySelector<HTMLInputElement>('input[aria-label="X 1"]')!
      input.value = value; input.dispatchEvent(new Event('input',{bubbles:true})); await nextTick()
    }
    await change('120')
    expect(layout.pins[0].center[0]).toBe(100)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    wrapper.getComponent(ConfirmDialog).vm.$emit('cancel'); await nextTick()
    await wrapper.get('.pin-edit').trigger('click')
    expect(document.body.querySelector<HTMLInputElement>('input[aria-label="X 1"]')!.value).toBe('100')
    await change('130')
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm'); await nextTick()
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect((wrapper.emitted('update:modelValue')![0][0] as typeof layout).pins[0].center[0]).toBe(130)
  })
})

describe('sampling diagnostic display',()=>{
  it('renders finite profiles and rejects malformed/mismatched samples without stale charts',async()=>{
    wrapper=mount(SamplingDiagnostic,{props:{diagnostic:{pin_id:'P1',state:'found',distance_px:[-1,0,1],intensity:[0,1,0],gradient:[.1,0,-.1],gradient_threshold:.03,observed_pairs:[[0,-.5,.5]],inlier_pairs:[[0,-.5,.5]],coverage:1,residual_px:0}},global:{plugins:[i18n]}})
    expect(wrapper.findAll('polyline')).toHaveLength(2)
    expect(wrapper.findAll('tbody tr')).toHaveLength(1)
    await wrapper.setProps({diagnostic:{pin_id:'P1',state:'not_found',distance_px:[-1,0,1],intensity:[0,1],gradient:[0,0,0]}})
    expect(wrapper.findAll('polyline')).toHaveLength(0)
  })
})

describe('measurement editor', () => {
  it('builds both production recipes and never bridges a designed empty neighbor',()=>{
    const layout=createPinLayout();layout.pins=generatePins(1,10,[100,100],50,50,0,'normal')
    const all=()=>layout.pins.map(p=>p.pin_id)
    expect(buildMeasurementBatch(layout,all(),[...batchKinds])).toHaveLength(39)
    layout.pins=generatePins(2,8,[100,100],50,50,25,'normal')
    expect(buildMeasurementBatch(layout,all(),[...batchKinds])).toHaveLength(62)
    layout.pins[3]!.expected_present=false
    const items=buildMeasurementBatch(layout,all(),[...batchKinds])
    expect(items.some(i=>i.pin_a==='R1P04'||i.pin_b==='R1P04')).toBe(false)
    expect(items.some(i=>i.kind==='pitch'&&i.pin_a==='R1P03'&&i.pin_b==='R1P05')).toBe(false)
    expect(invalidMeasurementReferences([{...items[0]!,pin_a:'removed'}],layout)).toEqual([items[0]!.item_id])
    expect(invalidMeasurementReferences([{...items[0]!,kind:'length',pin_b:items[0]!.pin_a,feature_a:'R1P01:tip',feature_b:'R1P01:root'}],layout)).toHaveLength(1)
  })
  it('uses the explicitly connected reference and writes line coordinates only to its draft',async()=>{
    const pinia=createPinia();useProjectStore(pinia).selectedProjectId='project'
    const layout=createPinLayout();layout.reference_sha256='a'.repeat(64);layout.pins=generatePins(1,2,[100,100],50,50,0,'normal')
    resources.list.mockResolvedValue([{reference:{sha256:layout.reference_sha256},content:{template:{reference_id:'reference',image_width:300,image_height:200}}}])
    resources.image.mockResolvedValue(new Blob(['image'],{type:'image/png'}))
    const revoke=vi.fn();vi.stubGlobal('URL',class extends URL {static createObjectURL(){return 'blob:reference'}static revokeObjectURL=revoke})
    const item={item_id:'width',kind:'width',pin_a:'R1P01',section:100}
    const source={nodeId:'pins',nodeTypeId:'custom.connector.pin-array-locate',parameters:{layout}}
    wrapper=mount(MeasurementEditor,{props:{modelValue:[item],inputSources:{pins:[source],features:[source]} as never},global:{plugins:[pinia,i18n]}})
    await wrapper.get('.measurement-edit').trigger('click');await flushPromises()
    expect(resources.image).toHaveBeenCalledTimes(1)
    const viewer=wrapper.getComponent(ImageViewer)
    expect(viewer.props('image')?.overlays).toHaveLength(2)
    const onApplied=vi.fn();viewer.vm.$emit('apply-interaction',{lineXyxy:[10,20,10,100],onApplied});await nextTick()
    expect(onApplied).toHaveBeenCalledWith(true)
    expect(item.section).toBe(100)
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm');await nextTick()
    expect(wrapper.emitted('update:modelValue')![0][0]).toMatchObject([{direction:[0,1],section:-10}])
    expect(revoke).toHaveBeenCalledWith('blob:reference')
  })
  it('keeps edits transactional and prevents a duplicate measurement ID', async () => {
    const items = [{item_id:'width',kind:'width',pin_a:'R1P01',section:100}]
    wrapper = mount(MeasurementEditor, {attachTo:document.body,props:{modelValue:items},global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.measurement-edit').trigger('click')
    const input=document.body.querySelector<HTMLInputElement>('input[aria-label="ID 1"]')!
    input.value='changed'; input.dispatchEvent(new Event('input',{bubbles:true})); await nextTick()
    expect(items[0].item_id).toBe('width')
    wrapper.getComponent(ConfirmDialog).vm.$emit('cancel'); await nextTick()
    await wrapper.get('.measurement-edit').trigger('click')
    expect(document.body.querySelector<HTMLInputElement>('input[aria-label="ID 1"]')!.value).toBe('width')
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm'); await nextTick()
    expect(wrapper.emitted('update:modelValue')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')![0][0]).toMatchObject([{item_id:'width',direction:[1,0]}])
  })
  it('rejects incomplete length definitions rather than silently measuring centers', async () => {
    wrapper = mount(MeasurementEditor,{attachTo:document.body,props:{modelValue:[{item_id:'length',kind:'length',pin_a:'P1',pin_b:'P1'}]},global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.measurement-edit').trigger('click')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(true)
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm'); await nextTick()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })
})

describe('calibration editor', () => {
  it('requires four homography control points and preserves the original on Cancel', async () => {
    const points = [{image:[10,10],world:[0,0]}, {image:[90,10],world:[1,0]}, {image:[90,90],world:[1,1]}]
    wrapper = mount(CalibrationPointsEditor,{attachTo:document.body,props:{modelValue:points,parameters:{image_width:100,image_height:100,model:'homography'},parameterName:'control_points'},global:{plugins:[createPinia(),i18n]}})
    await wrapper.get('.calibration-edit').trigger('click')
    expect(wrapper.getComponent(ConfirmDialog).props('confirmDisabled')).toBe(true)
    expect(wrapper.getComponent(ImageViewer).props('dialogLayer')).toBe(true)
    wrapper.getComponent(ConfirmDialog).vm.$emit('cancel');await nextTick()
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(points).toHaveLength(3)
  })
})
