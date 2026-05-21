import type { RouteRecordRaw } from 'vue-router'

const SettingsDiagnosticsPage = () => import('./pages/SettingsDiagnosticsPage.vue')

export const settingsRoutes: RouteRecordRaw[] = [
  {
    path: '/settings',
    component: SettingsDiagnosticsPage,
    meta: { requiredScopes: ['auth:read'] },
  },
]