/**
 * The reviewer feedback widget: a floating button that files a GitHub issue, with a screenshot and
 * the spot pointed at, through the Pages Function in functions/feedback-api/.
 *
 * Built only when VITE_FEEDBACK=1 (every Cloudflare Pages build, see vite.config.ts). main.tsx imports
 * this module behind that flag, so the dashboard the Python package ships carries none of it.
 *
 * It mounts in its own root beside the app's, so it never re-renders or restyles the dashboard, and
 * the screenshot leaves it out.
 */
import ReactDOM from 'react-dom/client'
import Feedback from './Feedback'
import './feedback.css'

export function installFeedback(): void {
  const host = document.createElement('div')
  host.id = 'feedback-widget'
  document.body.append(host)
  ReactDOM.createRoot(host).render(<Feedback root={host} />)
}
