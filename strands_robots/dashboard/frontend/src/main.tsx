import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { initScheme } from './lib/scheme'
import './styles.css'

function mount() {
  // The remembered colour scheme goes on <html> before React paints, so a dark
  // choice never flashes the paper page first.
  initScheme()

  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode><App /></React.StrictMode>,
  )
}

// Fork patch: preview builds only (VITE_DEMO=1, `npm run build:preview`): sample robots and no server, so a
// reviewer can open the page anywhere. The flag is replaced at build time, so a normal build drops
// the demo module entirely.
if (import.meta.env.VITE_DEMO === '1') import('./demo').then(m => { m.installDemo(); mount() })
else mount()

// Fork patch: preview builds only (VITE_FEEDBACK=1): a feedback button that files GitHub issues through
// the Pages Function in functions/feedback-api/. A normal build drops it like the demo module.
if (import.meta.env.VITE_FEEDBACK === '1') import('./feedback').then(m => m.installFeedback())
