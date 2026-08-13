import { createBrowserRouter } from 'react-router-dom'
import { LandingPage } from './landing-page'
import { VendorPage } from './vendor-page'
import { LearnerPage } from './learner-page'
import { VendorPasswordResetPage } from './vendor-password-reset-page'

export const router = createBrowserRouter([
  { path: '/vendor/reset/:uid/:token', element: <VendorPasswordResetPage /> },
  { path: '/vendor/*', element: <VendorPage /> },
  { path: '/app/*', element: <LearnerPage /> },
  {
    path: '*',
    element: <LandingPage />,
  },
])
