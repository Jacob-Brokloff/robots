/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** '1' in a preview build: src/demo stands in for the server (see main.tsx). */
  readonly VITE_DEMO?: string
  /** '1' in a preview build: the reviewer feedback widget (src/feedback). */
  readonly VITE_FEEDBACK?: string
  /** The Pages branch and commit the preview was built from, sent with each feedback issue. */
  readonly VITE_PAGES_BRANCH?: string
  readonly VITE_PAGES_COMMIT?: string
}
