/**
 * Que puede hacer la sesion actual en una task concreta.
 *
 * No hay roles globales: la misma wallet es client en una task y developer en
 * otra. Esto es solo para la UI; la autoridad final es el backend.
 */

import type { AuthContextValue } from './authContext'
import type { Bounty } from '../types/bounty'

export interface AccessIssue {
  message: string
  hint?: string
}

const NOT_SIGNED_IN_HINT =
  'MergePay needs a wallet signature to know who is acting on this task.'

/** La sesion abierta, solo si coincide con la wallet conectada en Freighter. */
function activeWallet(auth: AuthContextValue, connectedWallet: string | null): string | null {
  if (auth.status !== 'authenticated' || auth.wallet === null) {
    return null
  }

  return auth.wallet === connectedWallet ? auth.wallet : null
}

export function fundingIssue(
  auth: AuthContextValue,
  connectedWallet: string | null,
  bounty: Bounty,
): AccessIssue | null {
  const wallet = activeWallet(auth, connectedWallet)

  if (wallet === null) {
    if (auth.status === 'authenticated') {
      return { message: 'Switch to the client wallet for this task.' }
    }

    return {
      message: 'Sign in with the client wallet to secure this reward.',
      hint: NOT_SIGNED_IN_HINT,
    }
  }

  // Un DRAFT heredado sin client todavia lo reclama quien financie on-chain.
  if (bounty.client_wallet !== null && bounty.client_wallet !== wallet) {
    return { message: 'Switch to the client wallet for this task.' }
  }

  return null
}

export function assignmentIssue(
  auth: AuthContextValue,
  connectedWallet: string | null,
  bounty: Bounty,
): AccessIssue | null {
  const wallet = activeWallet(auth, connectedWallet)

  if (wallet === null) {
    if (auth.status === 'authenticated') {
      return { message: 'Switch to the wallet you signed in with to accept this task.' }
    }

    return {
      message: 'Sign in with your developer wallet to accept this task.',
      hint: NOT_SIGNED_IN_HINT,
    }
  }

  if (bounty.client_wallet === wallet) {
    return {
      message: 'You are signed in as the client for this task.',
      hint: 'Switch to a developer wallet to accept it.',
    }
  }

  return null
}

export function submissionIssue(
  auth: AuthContextValue,
  connectedWallet: string | null,
  bounty: Bounty,
): AccessIssue | null {
  const wallet = activeWallet(auth, connectedWallet)

  if (wallet === null) {
    if (auth.status === 'authenticated') {
      return { message: 'Switch to the assigned developer wallet to submit this work.' }
    }

    return {
      message: 'Sign in with the assigned developer wallet to submit this work.',
      hint: NOT_SIGNED_IN_HINT,
    }
  }

  if (bounty.developer_wallet !== wallet) {
    return { message: 'Switch to the assigned developer wallet to submit this work.' }
  }

  return null
}

/** Client y developer pueden pedir verificacion; nadie mas. */
export function verificationIssue(
  auth: AuthContextValue,
  bounty: Bounty,
): AccessIssue | null {
  if (auth.status !== 'authenticated' || auth.wallet === null) {
    return {
      message: 'Sign in as a task participant to run verification.',
      hint: NOT_SIGNED_IN_HINT,
    }
  }

  if (auth.wallet !== bounty.client_wallet && auth.wallet !== bounty.developer_wallet) {
    return {
      message: 'Only the client or assigned developer can run verification.',
    }
  }

  return null
}
