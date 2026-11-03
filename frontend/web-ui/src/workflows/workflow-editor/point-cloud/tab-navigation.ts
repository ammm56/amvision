/** 页签只改变本地呈现；方向键同步焦点，不触发测量。 */
export function navigateTab(event: KeyboardEvent, ids: string[], current: string, select: (id: string) => void) {
  const index = ids.indexOf(current)
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? ids.length - 1
    : event.key === 'ArrowRight' ? (index + 1) % ids.length
    : event.key === 'ArrowLeft' ? (index + ids.length - 1) % ids.length : -1
  if (next < 0 || !ids[next]) return
  event.preventDefault()
  select(ids[next])
  const tabs = (event.currentTarget as HTMLElement).parentElement?.querySelectorAll<HTMLButtonElement>('[role=tab]')
  tabs?.[next]?.focus()
}
