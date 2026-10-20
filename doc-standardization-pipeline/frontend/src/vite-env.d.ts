/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 'true' serves every screen from mockData.ts; 'false' calls the real backend. */
  readonly VITE_USE_MOCK: string;
  /** Base URL of the backend, e.g. http://localhost:8080 */
  readonly VITE_API_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
