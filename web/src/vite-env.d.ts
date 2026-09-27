/// <reference types="vite/client" />

// Le scrive la build dell'immagine web (vedi web/Dockerfile): da quale commit
// viene l'interfaccia aperta nel browser. Con `npm run dev` mancano.
interface ImportMetaEnv {
  readonly VITE_COMMIT?: string;
  readonly VITE_DATA_COMMIT?: string;
  readonly VITE_COSTRUITA?: string;
}
