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
