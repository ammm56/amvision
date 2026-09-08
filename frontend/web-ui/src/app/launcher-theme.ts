import type { ThemeMode } from './stores/preferences.store'

/** 桌面外壳仅传递外观，不暴露本机命令或其他业务能力。 */
export function installLauncherThemeSync(preferences: { setTheme(theme: ThemeMode): void }): () => void {
  const apply = (event: Event): void => {
    const theme: unknown = (event as CustomEvent<{ theme?: unknown }>).detail?.theme
    if (theme === 'light' || theme === 'dark') preferences.setTheme(theme)
  }
  window.addEventListener('amvision:launcher-theme-v1', apply)
  return () => window.removeEventListener('amvision:launcher-theme-v1', apply)
}
