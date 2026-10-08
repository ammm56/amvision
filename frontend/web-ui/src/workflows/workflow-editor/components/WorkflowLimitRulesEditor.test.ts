import {mount} from '@vue/test-utils'
import {describe,it,expect} from 'vitest'
import {createI18n} from 'vue-i18n'
import Editor from './WorkflowLimitRulesEditor.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {limitRuleError,normalizeLimitRule} from '../parameters/limit-rules'
describe('generic tolerance table',()=>{
  it('accepts zero, negative and one-sided closed bounds and rejects invalid types and open zero-width intervals',()=>{
    const rule=normalizeLimitRule({item_id:'temperature',unit:'celsius',lower:-20,upper:0})
    expect(limitRuleError(rule)).toBeNull()
    expect(limitRuleError({...rule,lower:null})).toBeNull()
    expect(limitRuleError({...rule,upper:-20})).toBeNull()
    expect(limitRuleError({...rule,upper:-20,include_upper:false})).toBe('interval')
    expect(limitRuleError({...rule,lower:null,upper:null})).toBe('bound')
    expect(limitRuleError({...rule,enabled:'false' as never})).toBe('boolean')
    expect(limitRuleError({...rule,lower:NaN})).toBe('number')
    expect(limitRuleError(normalizeLimitRule({lower:0}))).toBe('identity')
    expect(limitRuleError({...rule,item_id:undefined as never})).toBe('identity')
    expect(limitRuleError(normalizeLimitRule(null))).toBe('identity')
  })
  it('preserves original precision, cancels edits and blocks invalid rows',async()=>{
    const rule=normalizeLimitRule({item_id:'weight',unit:'gram',lower:0,upper:.6900000000000001})
    const wrapper=mount(Editor,{props:{modelValue:[rule]},global:{plugins:[createI18n({legacy:false,locale:'zh-CN',messages:{}})]}})
    await wrapper.get('button').trigger('click')
    const dialog=wrapper.getComponent(ConfirmDialog)
    expect(dialog.props('confirmDisabled')).toBe(false)
    const numbers=dialog.findAll('input[type=number]')
    expect((numbers[1]!.element as HTMLInputElement).value).toBe(String(rule.upper))
    await numbers[0]!.setValue('2')
    expect(dialog.props('confirmDisabled')).toBe(true)
    expect(rule.lower).toBe(0)
    dialog.vm.$emit('confirm')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    dialog.vm.$emit('cancel');await wrapper.vm.$nextTick()
    await wrapper.get('button').trigger('click')
    wrapper.getComponent(ConfirmDialog).vm.$emit('confirm');await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')![0]![0]).toEqual([rule])
    wrapper.unmount()
  })
})
