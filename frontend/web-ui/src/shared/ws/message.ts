import { translate } from '@/platform/i18n'

export function getWebSocketCloseMessage(reason: string | null): string {
  if (!reason) {
    return translate('ws.disconnected')
  }
  if (reason.includes('permission_denied')) {
    return translate('ws.permissionDenied')
  }
  if (reason.includes('authentication_required')) {
    return translate('ws.authenticationRequired')
  }
  if (reason.includes('subscriber_queue_overflowed')) {
    return translate('ws.queueOverflowed')
  }
  return reason
}