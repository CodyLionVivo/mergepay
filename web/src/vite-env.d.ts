/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_STELLAR_RPC_URL?: string
  readonly VITE_STELLAR_NETWORK?: string
  readonly VITE_STELLAR_NETWORK_PASSPHRASE?: string
  readonly VITE_STELLAR_CONTRACT_ID?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
