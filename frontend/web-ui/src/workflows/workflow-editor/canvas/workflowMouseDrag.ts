/** 判断鼠标左键在移动事件发生时是否仍处于按下状态。 */
export function isPrimaryMouseButtonPressed(event: MouseEvent): boolean {
  return (event.buttons & 1) === 1
}
