#![cfg(test)]

extern crate std;

use crate::{BountyStatus, Error, MergePayEscrow, MergePayEscrowClient};

use soroban_sdk::{
    testutils::{Address as _, Ledger as _},
    token, Address, BytesN, Env,
};

// 10 unidades con 7 decimales.
const AMOUNT: i128 = 100_000_000;

const DEADLINE: u64 = 1_000;

const BOUNTY_ID: u64 = 1;

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

// ─────────────────────────────────────────
// Andamiaje compartido por los tests de reglas.
//
// El cliente arranca con exactamente AMOUNT, de modo que los asserts de
// balance detectan cualquier cobro doble o pago fantasma.
// ─────────────────────────────────────────

struct Setup {
    env: Env,
    token_address: Address,
    contract_address: Address,
    client_address: Address,
    developer_address: Address,
}

fn setup() -> Setup {
    let env = Env::default();

    env.mock_all_auths();

    let token_admin = Address::generate(&env);
    let client_address = Address::generate(&env);
    let developer_address = Address::generate(&env);
    let verifier_address = Address::generate(&env);

    let stellar_asset = env.register_stellar_asset_contract_v2(token_admin.clone());

    let token_address = stellar_asset.address();

    token::StellarAssetClient::new(&env, &token_address).mint(&client_address, &AMOUNT);

    let contract_address = env.register(
        MergePayEscrow,
        (verifier_address.clone(), token_address.clone()),
    );

    Setup {
        env,
        token_address,
        contract_address,
        client_address,
        developer_address,
    }
}

impl Setup {
    fn escrow(&self) -> MergePayEscrowClient<'_> {
        MergePayEscrowClient::new(&self.env, &self.contract_address)
    }

    fn token(&self) -> token::Client<'_> {
        token::Client::new(&self.env, &self.token_address)
    }

    fn criteria_hash(&self) -> BytesN<32> {
        BytesN::from_array(&self.env, &[1u8; 32])
    }

    fn evidence_hash(&self) -> BytesN<32> {
        BytesN::from_array(&self.env, &[2u8; 32])
    }

    fn set_timestamp(&self, timestamp: u64) {
        self.env.ledger().set_timestamp(timestamp);
    }

    /// Crea y financia el bounty estandar usado por el resto de los tests.
    fn fund_bounty(&self) {
        self.escrow().create_bounty(
            &BOUNTY_ID,
            &self.client_address,
            &AMOUNT,
            &self.criteria_hash(),
            &DEADLINE,
        );
    }

    fn assert_balances(&self, escrow: i128, client: i128, developer: i128) {
        let token = self.token();

        assert_eq!(token.balance(&self.contract_address), escrow, "escrow");

        assert_eq!(token.balance(&self.client_address), client, "client");

        assert_eq!(
            token.balance(&self.developer_address),
            developer,
            "developer"
        );
    }
}

// ─────────────────────────────────────────
// A. create_bounty rechaza amount = 0.
// ─────────────────────────────────────────

#[test]
fn create_bounty_rejects_zero_amount() {
    let setup = setup();

    assert_eq!(
        setup.escrow().try_create_bounty(
            &BOUNTY_ID,
            &setup.client_address,
            &0,
            &setup.criteria_hash(),
            &DEADLINE,
        ),
        Err(Ok(Error::InvalidAmount)),
    );

    // Nada se movio: el cliente conserva su saldo.
    setup.assert_balances(0, AMOUNT, 0);

    assert_eq!(
        setup.escrow().try_get_bounty(&BOUNTY_ID),
        Err(Ok(Error::BountyNotFound)),
    );
}

// ─────────────────────────────────────────
// B. create_bounty rechaza amount negativo.
// ─────────────────────────────────────────

#[test]
fn create_bounty_rejects_negative_amount() {
    let setup = setup();

    assert_eq!(
        setup.escrow().try_create_bounty(
            &BOUNTY_ID,
            &setup.client_address,
            &-1,
            &setup.criteria_hash(),
            &DEADLINE,
        ),
        Err(Ok(Error::InvalidAmount)),
    );

    setup.assert_balances(0, AMOUNT, 0);
}

// ─────────────────────────────────────────
// C. No se puede crear dos veces el mismo id.
// ─────────────────────────────────────────

#[test]
fn create_bounty_rejects_duplicate_id() {
    let setup = setup();

    setup.fund_bounty();

    setup.assert_balances(AMOUNT, 0, 0);

    assert_eq!(
        setup.escrow().try_create_bounty(
            &BOUNTY_ID,
            &setup.client_address,
            &AMOUNT,
            &setup.criteria_hash(),
            &DEADLINE,
        ),
        Err(Ok(Error::BountyAlreadyExists)),
    );

    // El rechazo ocurre antes del transfer: no hay cobro doble.
    setup.assert_balances(AMOUNT, 0, 0);
}

// ─────────────────────────────────────────
// D. No se puede aceptar un bounty dos veces.
// ─────────────────────────────────────────

#[test]
fn accept_bounty_rejects_second_developer() {
    let setup = setup();

    setup.fund_bounty();

    setup
        .escrow()
        .accept_bounty(&BOUNTY_ID, &setup.developer_address);

    let second_developer = Address::generate(&setup.env);

    assert_eq!(
        setup
            .escrow()
            .try_accept_bounty(&BOUNTY_ID, &second_developer),
        Err(Ok(Error::InvalidStatus)),
    );

    // El primer developer sigue siendo el asignado.
    assert_eq!(
        setup.escrow().get_bounty(&BOUNTY_ID).developer,
        Some(setup.developer_address.clone()),
    );

    setup.assert_balances(AMOUNT, 0, 0);
}

// ─────────────────────────────────────────
// E. No se puede aceptar despues del deadline.
// ─────────────────────────────────────────

#[test]
fn accept_bounty_rejected_after_deadline() {
    let setup = setup();

    setup.fund_bounty();

    setup.set_timestamp(DEADLINE + 1);

    assert_eq!(
        setup
            .escrow()
            .try_accept_bounty(&BOUNTY_ID, &setup.developer_address),
        Err(Ok(Error::DeadlinePassed)),
    );

    let bounty = setup.escrow().get_bounty(&BOUNTY_ID);

    assert_eq!(bounty.status, BountyStatus::Open);

    assert_eq!(bounty.developer, None);

    setup.assert_balances(AMOUNT, 0, 0);
}

// ─────────────────────────────────────────
// F. No se puede release sin developer asignado.
// ─────────────────────────────────────────

#[test]
fn release_bounty_rejected_without_developer() {
    let setup = setup();

    setup.fund_bounty();

    assert_eq!(
        setup
            .escrow()
            .try_release_bounty(&BOUNTY_ID, &setup.evidence_hash()),
        Err(Ok(Error::InvalidStatus)),
    );

    // Los fondos siguen bloqueados en el contrato.
    setup.assert_balances(AMOUNT, 0, 0);

    assert_eq!(setup.escrow().get_bounty(&BOUNTY_ID).evidence_hash, None);
}

// ─────────────────────────────────────────
// G. No se puede release dos veces.
//
// De paso cubre el limite temporal: en el timestamp exacto del deadline el
// release todavia es valido.
// ─────────────────────────────────────────

#[test]
fn release_bounty_rejects_second_payout() {
    let setup = setup();

    setup.fund_bounty();

    setup
        .escrow()
        .accept_bounty(&BOUNTY_ID, &setup.developer_address);

    setup.set_timestamp(DEADLINE);

    setup
        .escrow()
        .release_bounty(&BOUNTY_ID, &setup.evidence_hash());

    setup.assert_balances(0, 0, AMOUNT);

    assert_eq!(
        setup
            .escrow()
            .try_release_bounty(&BOUNTY_ID, &setup.evidence_hash()),
        Err(Ok(Error::InvalidStatus)),
    );

    // El developer no cobro dos veces.
    setup.assert_balances(0, 0, AMOUNT);
}

// ─────────────────────────────────────────
// H. No se puede release despues del deadline.
//
// El accept ocurre en el timestamp exacto del deadline, que sigue siendo
// valido; el release un segundo despues ya no lo es.
// ─────────────────────────────────────────

#[test]
fn release_bounty_rejected_after_deadline() {
    let setup = setup();

    setup.fund_bounty();

    setup.set_timestamp(DEADLINE);

    setup
        .escrow()
        .accept_bounty(&BOUNTY_ID, &setup.developer_address);

    setup.set_timestamp(DEADLINE + 1);

    assert_eq!(
        setup
            .escrow()
            .try_release_bounty(&BOUNTY_ID, &setup.evidence_hash()),
        Err(Ok(Error::DeadlinePassed)),
    );

    assert_eq!(
        setup.escrow().get_bounty(&BOUNTY_ID).status,
        BountyStatus::Assigned,
    );

    setup.assert_balances(AMOUNT, 0, 0);
}

// ─────────────────────────────────────────
// I. cancel_open_bounty devuelve la recompensa completa al cliente.
// ─────────────────────────────────────────

#[test]
fn cancel_open_bounty_returns_full_reward() {
    let setup = setup();

    setup.fund_bounty();

    setup.assert_balances(AMOUNT, 0, 0);

    setup.escrow().cancel_open_bounty(&BOUNTY_ID);

    setup.assert_balances(0, AMOUNT, 0);

    let bounty = setup.escrow().get_bounty(&BOUNTY_ID);

    assert_eq!(bounty.status, BountyStatus::Cancelled);

    assert_eq!(bounty.developer, None);

    assert_eq!(bounty.evidence_hash, None);

    assert_eq!(bounty.criteria_hash, setup.criteria_hash());
}

// ─────────────────────────────────────────
// J. No se puede cancelar un bounty ya Assigned.
// ─────────────────────────────────────────

#[test]
fn cancel_open_bounty_rejected_once_assigned() {
    let setup = setup();

    setup.fund_bounty();

    setup
        .escrow()
        .accept_bounty(&BOUNTY_ID, &setup.developer_address);

    assert_eq!(
        setup.escrow().try_cancel_open_bounty(&BOUNTY_ID),
        Err(Ok(Error::InvalidStatus)),
    );

    assert_eq!(
        setup.escrow().get_bounty(&BOUNTY_ID).status,
        BountyStatus::Assigned,
    );

    // El cliente no recupero nada.
    setup.assert_balances(AMOUNT, 0, 0);
}

// ─────────────────────────────────────────
// K. refund_expired falla antes y exactamente en el deadline.
// ─────────────────────────────────────────

#[test]
fn refund_expired_rejected_before_and_at_deadline() {
    let setup = setup();

    setup.fund_bounty();

    // Antes del deadline.
    setup.set_timestamp(DEADLINE - 1);

    assert_eq!(
        setup.escrow().try_refund_expired(&BOUNTY_ID),
        Err(Ok(Error::DeadlineNotReached)),
    );

    // En el timestamp exacto del deadline todavia no expiro.
    setup.set_timestamp(DEADLINE);

    assert_eq!(
        setup.escrow().try_refund_expired(&BOUNTY_ID),
        Err(Ok(Error::DeadlineNotReached)),
    );

    assert_eq!(
        setup.escrow().get_bounty(&BOUNTY_ID).status,
        BountyStatus::Open,
    );

    setup.assert_balances(AMOUNT, 0, 0);
}

// ─────────────────────────────────────────
// L. refund_expired funciona pasado el deadline con status Open.
// ─────────────────────────────────────────

#[test]
fn refund_expired_returns_reward_when_open() {
    let setup = setup();

    setup.fund_bounty();

    setup.set_timestamp(DEADLINE + 1);

    setup.escrow().refund_expired(&BOUNTY_ID);

    setup.assert_balances(0, AMOUNT, 0);

    let bounty = setup.escrow().get_bounty(&BOUNTY_ID);

    assert_eq!(bounty.status, BountyStatus::Refunded);

    assert_eq!(bounty.developer, None);

    assert_eq!(bounty.evidence_hash, None);

    assert_eq!(bounty.criteria_hash, setup.criteria_hash());
}

// ─────────────────────────────────────────
// M. refund_expired funciona pasado el deadline con status Assigned.
// ─────────────────────────────────────────

#[test]
fn refund_expired_returns_reward_when_assigned() {
    let setup = setup();

    setup.fund_bounty();

    setup
        .escrow()
        .accept_bounty(&BOUNTY_ID, &setup.developer_address);

    setup.set_timestamp(DEADLINE + 1);

    setup.escrow().refund_expired(&BOUNTY_ID);

    // El developer no cobra: el verifier nunca autorizo el payout.
    setup.assert_balances(0, AMOUNT, 0);

    let bounty = setup.escrow().get_bounty(&BOUNTY_ID);

    assert_eq!(bounty.status, BountyStatus::Refunded);

    // El developer asignado se conserva como registro historico.
    assert_eq!(bounty.developer, Some(setup.developer_address.clone()));

    assert_eq!(bounty.evidence_hash, None);

    assert_eq!(bounty.criteria_hash, setup.criteria_hash());
}

// ─────────────────────────────────────────
// N. No se puede refund un bounty ya pagado.
// ─────────────────────────────────────────

#[test]
fn refund_expired_rejected_when_paid() {
    let setup = setup();

    setup.fund_bounty();

    setup
        .escrow()
        .accept_bounty(&BOUNTY_ID, &setup.developer_address);

    setup
        .escrow()
        .release_bounty(&BOUNTY_ID, &setup.evidence_hash());

    setup.set_timestamp(DEADLINE + 1);

    assert_eq!(
        setup.escrow().try_refund_expired(&BOUNTY_ID),
        Err(Ok(Error::InvalidStatus)),
    );

    let bounty = setup.escrow().get_bounty(&BOUNTY_ID);

    assert_eq!(bounty.status, BountyStatus::Paid);

    // La recompensa sigue en manos del developer.
    setup.assert_balances(0, 0, AMOUNT);
}

// ─────────────────────────────────────────
// O. No se puede refund dos veces.
// ─────────────────────────────────────────

#[test]
fn refund_expired_rejects_second_refund() {
    let setup = setup();

    setup.fund_bounty();

    setup.set_timestamp(DEADLINE + 1);

    setup.escrow().refund_expired(&BOUNTY_ID);

    setup.assert_balances(0, AMOUNT, 0);

    assert_eq!(
        setup.escrow().try_refund_expired(&BOUNTY_ID),
        Err(Ok(Error::InvalidStatus)),
    );

    // El cliente no cobro dos veces.
    setup.assert_balances(0, AMOUNT, 0);

    assert_eq!(
        setup.escrow().get_bounty(&BOUNTY_ID).status,
        BountyStatus::Refunded,
    );
}
