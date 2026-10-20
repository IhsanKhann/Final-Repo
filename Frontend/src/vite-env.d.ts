/// <reference types="vite/client" />

// Without this, `import.meta.env` is untyped and `tsc --noEmit` fails with
// TS2339 "Property 'env' does not exist on type 'ImportMeta'" in client.ts,
// endpoints.ts and AppShell.tsx. `vite build` succeeds regardless because it
// transforms rather than typechecks, so the breakage only shows up in
// `npm run build` (which is `tsc && vite build`) and in CI.

interface ImportMetaEnv {
  /** Unused since the mock path was deleted; kept so the type matches any stale .env. */
  readonly VITE_USE_MOCK: string;
  /** Base URL of the FastAPI backend, e.g. http://localhost:8000 */
  readonly VITE_API_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
