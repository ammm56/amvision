export function getWebSocketCloseMessage(reason: string | null): string {
  if (!reason) {
    return '连接已断开'
  }
  if (reason.includes('permission_denied')) {
    return '当前用户没有订阅该资源流的权限'
  }
  if (reason.includes('authentication_required')) {
    return '当前会话已失效'
  }
  if (reason.includes('subscriber_queue_overflowed')) {
    return '事件消费落后，正在重新同步快照'
  }
  return reason
}