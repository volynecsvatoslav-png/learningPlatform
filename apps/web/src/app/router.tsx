import { createBrowserRouter } from 'react-router-dom'
import { LandingPage } from './landing-page'
import { VendorPage } from './vendor-page'

export const router = createBrowserRouter([
  { path: '/vendor/*', element: <VendorPage /> },
  {
    path: '*',
    element: <LandingPage />,
  },
])
