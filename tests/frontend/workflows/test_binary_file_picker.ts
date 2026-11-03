import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import FilePicker from '@/shared/ui/components/FilePicker.vue'

function picker(accept: string) {
  return mount(FilePicker, {
    props: { label: 'Input', accept },
    global: { plugins: [createI18n({ legacy: false, locale: 'en-US', missingWarn: false, fallbackWarn: false })] },
  })
}

describe('binary file selection', () => {
  it.each(['cloud.ply', 'cloud.pcd', 'cloud.xyz'])('accepts unclassified %s consistently with the upload MIME', async name => {
    const wrapper = picker('application/octet-stream')
    try {
      const file = new File(['data'], name)
      const input = wrapper.get('input[type=file]')
      expect(input.attributes('accept')).toBe('')
      Object.defineProperty(input.element, 'files', { value: [file] })
      await input.trigger('change')
      expect(wrapper.emitted('update:modelValue')).toEqual([[file]])
      expect(wrapper.emitted('change')).toEqual([[file]])
    } finally { wrapper.unmount() }
  })

  it.each([
    ['application/octet-stream', 'image/png', 'cloud.png', false],
    ['image/*', '', 'cloud.ply', false],
    ['image/*', 'image/png', 'cloud.png', true],
    ['.ply', '', 'cloud.PLY', true],
    ['.pcd', '', 'cloud.ply', false],
  ] as const)('keeps explicit filter %s for %s / %s', async (accept, type, name, allowed) => {
    const wrapper = picker(accept)
    try {
      const file = new File(['data'], name, { type })
      await wrapper.trigger('drop', { dataTransfer: { files: [file] } })
      expect(Boolean(wrapper.emitted('change'))).toBe(allowed)
    } finally { wrapper.unmount() }
  })
})
