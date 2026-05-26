import type { RouteRecordRaw } from 'vue-router'

const TriggerSourcePage = () => import('./pages/TriggerSourcePage.vue')

export const integrationRoutes: RouteRecordRaw[] = [
  {
    path: '/integrations/trigger-sources',
    component: TriggerSourcePage,
    meta: { requiredScopes: ['workflows:read'] },
  },
]
