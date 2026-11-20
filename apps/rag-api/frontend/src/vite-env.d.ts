/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "mock" builds the in-memory API; anything else builds the HTTP client. */
  readonly VITE_API?: string;
}
