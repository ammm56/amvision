import type { RouteRecordRaw } from 'vue-router'

import InferenceDebugPage from './pages/InferenceDebugPage.vue'

export const inferenceRoutes: RouteRecordRaw[] = [
  {
    path: '/inference',
    component: InferenceDebugPage,
    meta: { requiredScopes: ['models:read'] },
  },
]