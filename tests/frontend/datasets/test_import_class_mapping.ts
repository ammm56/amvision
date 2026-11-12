import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { defineComponent, ref } from 'vue'
import { expect, it } from 'vitest'
import ImportClassMapping, { type ImportMapRow } from '../../../frontend/web-ui/src/modules/datasets/components/ImportClassMapping.vue'

function editor(format: string, initial: ImportMapRow[], complete: boolean) {
  const rows = ref(initial)
  const wrapper = mount(defineComponent({
    components: { ImportClassMapping },
    setup: () => ({ rows, format, complete }),
    template: '<ImportClassMapping v-model="rows" :format="format" :allow-supplement="!complete" />',
  }), { global: { plugins: [createI18n({ legacy: false, locale: 'zh' })] } })
  const button = (name: string) => wrapper.findAll('button').find(item => item.text() === name)!
  const enter = async (source: string, target: string) => {
    if (wrapper.find('button[aria-expanded=false]').exists()) await button('添加映射').trigger('click')
    else await button('补录源类别').trigger('click')
    const inputs = wrapper.findAll('label input')
    await inputs[0].setValue(source)
    await inputs[1].setValue(target)
    await button('确定').trigger('click')
  }
  return { rows, wrapper, enter, button }
}
it('默认隐藏映射表，点击一次展示全部源类别，收起和展开保留修改', async () => {
  const { rows, wrapper, button } = editor('coco', [
    { source: '7', id: '7', name: 'bolt', target: 'bolt', count: 12 },
    { source: '8', id: '8', name: 'nut', target: 'nut', count: 5 },
  ], true)
  expect(wrapper.find('table').exists()).toBe(false)
  await button('添加映射').trigger('click')
  expect(wrapper.findAll('tbody tr')).toHaveLength(2)
  await wrapper.get('input[aria-label="目标类别 · bolt"]').setValue('螺栓')
  await button('收起').trigger('click')
  expect(wrapper.find('table').exists()).toBe(false)
  await button('添加映射').trigger('click')
  expect(rows.value.map(row => [row.source, row.target])).toEqual([['7','螺栓'],['8','nut']])
  await wrapper.get('button[aria-label="移除映射 · 7"]').trigger('click')
  expect(rows.value[0].target).toBe('bolt')
  wrapper.unmount()
})
it('预览未读全时可以补录源名称，重复键不覆盖，删除只移除手动行', async () => {
  const { rows, wrapper, enter, button } = editor('voc', [], false)
  await enter(' scratch ', '划痕')
  expect(rows.value[0]).toMatchObject({ source: 'scratch', target: '划痕', count: null, manual: true })
  await enter('scratch','其他')
  expect(wrapper.get('[role=alert]').text()).toContain('已有映射')
  expect(rows.value[0].target).toBe('划痕')
  await button('取消').trigger('click')
  await wrapper.get('button[aria-label="移除映射 · scratch"]').trigger('click')
  expect(rows.value).toHaveLength(0)
  wrapper.unmount()
})
