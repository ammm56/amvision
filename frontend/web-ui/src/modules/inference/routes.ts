import type { RouteRecordRaw } from 'vue-router'

const InferenceDebugPage = () => import('./pages/InferenceDebugPage.vue')

export const inferenceRoutes: RouteRecordRaw[] = [
  {
    path: '/inference',
    component: InferenceDebugPage,
    meta: { requiredScopes: ['models:read'] },
  },
]
