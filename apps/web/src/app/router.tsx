import { createBrowserRouter } from 'react-router-dom'
import { LandingPage } from './landing-page'

export const router = createBrowserRouter([
  {
    path: '*',
    element: <LandingPage />,
  },
])
