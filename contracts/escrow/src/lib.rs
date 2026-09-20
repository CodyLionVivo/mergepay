#![no_std]

use soroban_sdk::{
    contract, contracterror, contractimpl, contracttype, token, Address, BytesN, Env,
};

#[cfg(test)]
mod test;

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BountyStatus {
    Open,
    Assigned,
    Paid,
}

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Bounty {
    pub client: Address,
    pub developer: Option<Address>,
    pub amount: i128,
    pub criteria_hash: BytesN<32>,
    pub evidence_hash: Option<BytesN<32>>,
    pub deadline: u64,
    pub status: BountyStatus,
}

#[contracttype]
#[derive(Clone)]
enum DataKey {
    Verifier,
    Token,
    Bounty(u64),
}

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    InvalidAmount = 1,
    BountyAlreadyExists = 2,
    BountyNotFound = 3,
    InvalidStatus = 4,
    DeadlinePassed = 5,
}

#[contract]
pub struct MergePayEscrow;

#[contractimpl]
impl MergePayEscrow {
    pub fn __constructor(env: Env, verifier: Address, token: Address) {
        env.storage().instance().set(&DataKey::Verifier, &verifier);

        env.storage().instance().set(&DataKey::Token, &token);
    }

    pub fn create_bounty(
        env: Env,
        id: u64,
        client: Address,
        amount: i128,
        criteria_hash: BytesN<32>,
        deadline: u64,
    ) -> Result<(), Error> {
        client.require_auth();

        if amount <= 0 {
            return Err(Error::InvalidAmount);
        }

        if deadline <= env.ledger().timestamp() {
            return Err(Error::DeadlinePassed);
        }

        let key = DataKey::Bounty(id);

        if env.storage().persistent().has(&key) {
            return Err(Error::BountyAlreadyExists);
        }

        let token_address: Address = env.storage().instance().get(&DataKey::Token).unwrap();

        let token_client = token::Client::new(&env, &token_address);

        token_client.transfer(&client, &env.current_contract_address(), &amount);

        let bounty = Bounty {
            client,
            developer: None,
            amount,
            criteria_hash,
            evidence_hash: None,
            deadline,
            status: BountyStatus::Open,
        };

        env.storage().persistent().set(&key, &bounty);

        Ok(())
    }

    pub fn accept_bounty(env: Env, id: u64, developer: Address) -> Result<(), Error> {
        developer.require_auth();

        let key = DataKey::Bounty(id);

        let mut bounty: Bounty = env
            .storage()
            .persistent()
            .get(&key)
            .ok_or(Error::BountyNotFound)?;

        if bounty.status != BountyStatus::Open {
            return Err(Error::InvalidStatus);
        }

        if env.ledger().timestamp() > bounty.deadline {
            return Err(Error::DeadlinePassed);
        }

        bounty.developer = Some(developer);
        bounty.status = BountyStatus::Assigned;

        env.storage().persistent().set(&key, &bounty);

        Ok(())
    }

    pub fn release_bounty(env: Env, id: u64, evidence_hash: BytesN<32>) -> Result<(), Error> {
        let verifier: Address = env.storage().instance().get(&DataKey::Verifier).unwrap();

        verifier.require_auth();

        let key = DataKey::Bounty(id);

        let mut bounty: Bounty = env
            .storage()
            .persistent()
            .get(&key)
            .ok_or(Error::BountyNotFound)?;

        if bounty.status != BountyStatus::Assigned {
            return Err(Error::InvalidStatus);
        }

        if env.ledger().timestamp() > bounty.deadline {
            return Err(Error::DeadlinePassed);
        }

        let developer = bounty.developer.clone().ok_or(Error::InvalidStatus)?;

        let token_address: Address = env.storage().instance().get(&DataKey::Token).unwrap();

        let token_client = token::Client::new(&env, &token_address);

        token_client.transfer(&env.current_contract_address(), &developer, &bounty.amount);

        bounty.evidence_hash = Some(evidence_hash);
        bounty.status = BountyStatus::Paid;

        env.storage().persistent().set(&key, &bounty);

        Ok(())
    }

    pub fn get_bounty(env: Env, id: u64) -> Result<Bounty, Error> {
        env.storage()
            .persistent()
            .get(&DataKey::Bounty(id))
            .ok_or(Error::BountyNotFound)
    }
}
