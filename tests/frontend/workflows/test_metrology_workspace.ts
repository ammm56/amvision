import {afterEach,beforeEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {defineComponent,h,onUnmounted} from 'vue'
import MetrologyWorkspace from '../../../custom_nodes/metrology3d_nodes/frontend/MetrologyWorkspace.vue'
let resize:()=>void=()=>{}
let frames:Map<number,FrameRequestCallback>,sequence=0
beforeEach(()=>{
  frames=new Map();sequence=0
  vi.stubGlobal('requestAnimationFrame',vi.fn((callback:FrameRequestCallback)=>{frames.set(++sequence,callback);return sequence}))
  vi.stubGlobal('cancelAnimationFrame',vi.fn((id:number)=>frames.delete(id)))
})
function frame(){const queued=[...frames.values()];frames.clear();for(const callback of queued)callback(0)}
vi.stubGlobal('ResizeObserver',class{constructor(callback:()=>void){resize=callback}observe(){}disconnect(){}})
afterEach(()=>vi.restoreAllMocks())
it('keeps one view and parameter DOM across compact tabs, keyboard and width changes',async()=>{
  let width=390
  vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockImplementation(()=>({width,height:600}) as DOMRect)
  const setup=vi.fn(),dispose=vi.fn()
  const View=defineComponent({props:['presentation'],setup(props){setup();onUnmounted(dispose);return()=>h('div',{'data-view':''},props.presentation)}})
  const w=mount(MetrologyWorkspace,{attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]},slots:{parameters:'<input aria-label="Draft value" value="unchanged">',advanced:'<input aria-label="Quality value" value="original">',view:props=>h(View,props)}})
  try{
    await flushPromises()
    const view=w.get('[data-view]').element,input=w.get('[aria-label="Draft value"]').element
    const tabs=w.findAll('[role=tab]');expect(tabs.map(t=>t.text())).toEqual(['Parameters','3D','Evidence'])
    expect(w.get('.workspace-view').isVisible()).toBe(false)
    await tabs[0]!.trigger('keydown',{key:'ArrowRight'});expect(tabs[1]!.attributes('aria-selected')).toBe('true');expect(document.activeElement).toBe(tabs[1]!.element)
    await tabs[1]!.trigger('keydown',{key:'End'});expect(tabs[2]!.attributes('aria-selected')).toBe('true')
    expect(w.get('.workspace-parameters').isVisible()).toBe(false)
    width=1100;resize();resize();await flushPromises();expect(w.find('[role=tab]').exists()).toBe(true);expect(frames.size).toBe(1)
    frame();await flushPromises();expect(w.find('[role=tab]').exists()).toBe(false);expect(w.get('.workspace-parameters').isVisible()).toBe(true)
    width=390;resize();frame();await flushPromises();expect(w.findAll('[role=tab]')[2]!.attributes('aria-selected')).toBe('true')
    expect(w.get('[data-view]').element).toBe(view);expect(w.get('[aria-label="Draft value"]').element).toBe(input);expect(setup).toHaveBeenCalledOnce();expect(dispose).not.toHaveBeenCalled()
    expect(w.emitted('update:modelValue')).toBeUndefined()
  }finally{w.unmount()}
  expect(dispose).toHaveBeenCalledOnce()
})
it('uses compact controls in a short workstation viewport and removes its resize listener',async()=>{
  let height=600
  vi.spyOn(document.documentElement,'clientHeight','get').mockImplementation(()=>height)
  vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({width:1100,height:300} as DOMRect)
  const remove=vi.spyOn(window,'removeEventListener')
  const w=mount(MetrologyWorkspace,{global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await flushPromises();expect(w.findAll('[role=tab]')).toHaveLength(3)
  height=900;window.dispatchEvent(new Event('resize'));frame();await flushPromises();expect(w.find('[role=tab]').exists()).toBe(false)
  resize();expect(frames.size).toBe(1)
  const late=[...frames.values()][0]!
  w.unmount();expect(remove).toHaveBeenCalledWith('resize',expect.any(Function));expect(frames.size).toBe(0)
  late(0);resize();expect(frames.size).toBe(0)
})
