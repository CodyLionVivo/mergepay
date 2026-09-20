#![cfg(test)]

extern crate std;

use crate::{BountyStatus, MergePayEscrow, MergePayEscrowClient};

use soroban_sdk::{testutils::Address as _, token, Address, BytesN, Env};

#[test]
fn happy_path_locks_and_releases_reward() {
    let env = Env::default();

    env.mock_all_auths();

    let token_admin = Address::generate(&env);
    let client_address = Address::generate(&env);
    let developer_address = Address::generate(&env);
    let verifier_address = Address::generate(&env);

    // Token de prueba local.
    // En Testnet posteriormente utilizaremos el SAC del XLM nativo.
    let stellar_asset = env.register_stellar_asset_contract_v2(token_admin.clone());

    let token_address = stellar_asset.address();

    let token_admin_client = token::StellarAssetClient::new(&env, &token_address);

    let token_client = token::Client::new(&env, &token_address);

    // 10 unidades con 7 decimales.
    let amount: i128 = 100_000_000;

    token_admin_client.mint(&client_address, &amount);

    let contract_address = env.register(
        MergePayEscrow,
        (verifier_address.clone(), token_address.clone()),
    );

    let escrow = MergePayEscrowClient::new(&env, &contract_address);

    let criteria_hash = BytesN::from_array(&env, &[1u8; 32]);

    let evidence_hash = BytesN::from_array(&env, &[2u8; 32]);

    let deadline: u64 = 1_000;

    // ─────────────────────────────────────────
    // 1. Cliente tiene la recompensa.
    // ─────────────────────────────────────────

    assert_eq!(token_client.balance(&client_address), amount,);

    assert_eq!(token_client.balance(&contract_address), 0,);

    // ─────────────────────────────────────────
    // 2. Cliente crea y financia bounty.
    // ─────────────────────────────────────────

    escrow.create_bounty(&1u64, &client_address, &amount, &criteria_hash, &deadline);

    assert_eq!(token_client.balance(&client_address), 0,);

    assert_eq!(token_client.balance(&contract_address), amount,);

    let open_bounty = escrow.get_bounty(&1u64);

    assert_eq!(open_bounty.status, BountyStatus::Open,);

    assert_eq!(open_bounty.developer, None,);

    // ─────────────────────────────────────────
    // 3. Developer acepta.
    // ─────────────────────────────────────────

    escrow.accept_bounty(&1u64, &developer_address);

    let assigned_bounty = escrow.get_bounty(&1u64);

    assert_eq!(assigned_bounty.status, BountyStatus::Assigned,);

    assert_eq!(assigned_bounty.developer, Some(developer_address.clone()),);

    // ─────────────────────────────────────────
    // 4. Verifier autoriza payout.
    // ─────────────────────────────────────────

    escrow.release_bounty(&1u64, &evidence_hash);

    // ─────────────────────────────────────────
    // 5. Developer recibió recompensa.
    // ─────────────────────────────────────────

    assert_eq!(token_client.balance(&contract_address), 0,);

    assert_eq!(token_client.balance(&developer_address), amount,);

    let paid_bounty = escrow.get_bounty(&1u64);

    assert_eq!(paid_bounty.status, BountyStatus::Paid,);

    assert_eq!(paid_bounty.evidence_hash, Some(evidence_hash),);
}
