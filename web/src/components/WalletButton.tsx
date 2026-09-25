import { t, useI18n } from '../i18n'
import { AlertTriangle, Loader, Wallet } from 'lucide-react'
import { abbreviateAddress, useWallet } from '../stellar/walletContext'
import './WalletButton.css'

/**
 * Estado de la wallet en el header. Un solo boton, sin menu: conectar,
 * reintentar o, ya conectado, mostrar la address y la red.
 */
export function WalletButton() {
  useI18n()
  const { status, address, error, connect, refresh } = useWallet()

  if (status === 'connected' && address !== null) {
    return (
      <p className="wallet-chip" title={address}>
        <Wallet size={14} aria-hidden="true" />
        <span className="wallet-chip__address">{abbreviateAddress(address)}</span>
        <span className="wallet-chip__network">Testnet</span>
      </p>
    )
  }

  if (status === 'wrong-network') {
    return (
      <button
        type="button"
        className="wallet-button wallet-button--warning"
        onClick={() => void refresh()}
        title={t("Switch Freighter to Testnet, then click to check again.")}
      >
        <AlertTriangle size={14} aria-hidden="true" />{t("Wrong network")}</button>
    )
  }

  if (status === 'connecting') {
    return (
      <button type="button" className="wallet-button" disabled>
        <Loader size={14} aria-hidden="true" />{t("Connecting...")}</button>
    )
  }

  if (status === 'unavailable') {
    return (
      <button
        type="button"
        className="wallet-button"
        onClick={() => void refresh()}
        title={t("Install the Freighter extension, then click to check again.")}
      >
        <Wallet size={14} aria-hidden="true" />{t("Freighter not found")}</button>
    )
  }

  return (
    <button
      type="button"
      className={status === 'error' ? 'wallet-button wallet-button--danger' : 'wallet-button'}
      onClick={() => void connect()}
      title={error ? t(error) : undefined}
    >
      <Wallet size={14} aria-hidden="true" />{t("Connect wallet")}</button>
  )
}
