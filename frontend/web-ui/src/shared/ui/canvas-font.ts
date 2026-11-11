/** Canvas 不继承 DOM 字体，使用工作站主题的字体栈。 */
export function workbenchFontFamily(): string {
  return getComputedStyle(document.documentElement).getPropertyValue('--am-font-sans').trim() || 'sans-serif'
}

/** 字体按字形分包，在测量和绘制标签前加载所需字符。 */
export async function loadCanvasFont(text: string): Promise<void> {
  if (text && document.fonts) {
    try {
      await document.fonts.load(`14px ${workbenchFontFamily()}`, text)
    } catch {
      // 字体资产不可用时仍用字体栈中的本机字体绘制。
    }
  }
}
