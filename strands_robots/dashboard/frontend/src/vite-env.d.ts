/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** '1' in a preview build: src/demo stands in for the server (see main.tsx). */
  readonly VITE_DEMO?: string
}
