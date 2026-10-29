/**
 * The dashboard's brand in one place: names, links and browser chrome colours.
 * A rebrand edits this directory and nothing else:
 *
 * - brand.ts (this file): product and company names, the wordmark link, the
 *   home-screen label and the browser theme colours. index.html reads these at
 *   build time through the `brandHtml` plugin in vite.config.ts.
 * - brand.css: the accent colours for both schemes and the two font families.
 *   styles.css builds every semantic token (--accent, --ok, --focus) from them.
 * - BrandMark.tsx: the wordmark drawing in the header and on the passkey gate.
 *
 * The favicon and home-screen icon are files, not values: replace
 * public/icon.svg and public/apple-touch-icon.png (same names), then rebuild.
 *
 * Plain data, no imports: vite.config.ts loads this file under Node.
 */
export const BRAND = {
  /** Product name: the tab title and the identity line on the passkey gate. */
  name: 'Strands Robots',
  /** Label under the icon when the page is added to a phone's home screen. */
  shortName: 'Robots',
  /** The page's meta description. */
  description: 'Fleet cockpit for the strands-robots mesh',
  /** Who the wordmark names: its accessible label and tooltip. */
  company: 'Strands Agents',
  /** Where the wordmark links. */
  homeUrl: 'https://strandsagents.com/',
  /** The mono project label beside the wordmark. */
  project: '/robots',
  /** Browser chrome colour per scheme; match each scheme's page (--bg). */
  themeColor: { paper: '#ffffff', dark: '#000000' },
} as const
