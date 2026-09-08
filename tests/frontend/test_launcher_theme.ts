import { afterEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { installLauncherThemeSync } from '../../frontend/web-ui/src/app/launcher-theme'
import { usePreferencesStore } from '../../frontend/web-ui/src/app/stores/preferences.store'

describe('launcher theme contract', () => {
  afterEach(() => localStorage.clear())
  it('updates store, DOM and persisted preference through the existing action', () => {
    setActivePinia(createPinia())
    const preferences = usePreferencesStore()
    const dispose = installLauncherThemeSync(preferences)
    for (const theme of ['dark', 'light']) {
      window.dispatchEvent(new CustomEvent('amvision:launcher-theme-v1', { detail: { theme } }))
      expect(preferences.theme).toBe(theme)
      expect(document.documentElement.dataset.theme).toBe(theme)
      expect(localStorage.getItem('amvision.web-ui.theme')).toBe(theme)
    }
    window.dispatchEvent(new CustomEvent('amvision:launcher-theme-v1', { detail: { theme: 'invalid' } }))
    expect(preferences.theme).toBe('light')
    dispose()
    window.dispatchEvent(new CustomEvent('amvision:launcher-theme-v1', { detail: { theme: 'dark' } }))
    expect(preferences.theme).toBe('light')
  })
})
