import json
import subprocess
import time
from hashlib import sha256
from typing import Union

import spl.token.instructions
from eth_keys import keys as eth_keys
import solana.system_program as sp

from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.transaction import AccountMeta, TransactionInstruction, Transaction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address, ApproveParams, MintToParams

from utils.evm_loader import EvmLoader, CHAIN_ID
from utils.instructions import make_DepositV03, make_CreateAssociatedTokenIdempotent
from .utils.constants import EVM_LOADER, SOLANA_URL, NEON_TOKEN_MINT_ID, TREASURY_POOL_SEED


from .types.types import Caller

solana_client = Client(SOLANA_URL, commitment=Confirmed)


# number of evm steps per transaction
EVM_STEPS = 500


def create_treasury_pool_address(pool_index, evm_loader=EVM_LOADER):
    return PublicKey.find_program_address(
        [bytes(TREASURY_POOL_SEED, "utf8"), pool_index.to_bytes(4, "little")], PublicKey(evm_loader)
    )[0]


def wait_for_account_to_exists(http_client: Client, account: PublicKey, timeout=30, sleep_time=0.4):
    elapsed_time = 0
    while elapsed_time < timeout:
        resp = http_client.get_account_info(account, commitment=Confirmed)
        if resp.value is not None:
            return

        time.sleep(sleep_time)
        elapsed_time += sleep_time

    raise RuntimeError(f"Account {account} not exists after {timeout} seconds")


def account_with_seed(base, seed, program) -> PublicKey:
    return PublicKey(sha256(bytes(base) + bytes(seed, "utf8") + bytes(program)).digest())


def create_account(solana_client, payer, size, owner, account=None, lamports=None):
    account = account or Keypair.generate()
    lamports = lamports or solana_client.get_minimum_balance_for_rent_exemption(size).value
    trx = Transaction()
    trx.fee_payer = payer.public_key
    instr = sp.create_account(sp.CreateAccountParams(payer.public_key, account.public_key, lamports, size, owner))
    solana_client.send_tx(trx.add(instr), payer, account)
    return account


def create_account_with_seed(funding, base, seed, lamports, space, program=PublicKey(EVM_LOADER)):
    created = account_with_seed(base, seed, program)
    print(f"Created: {created}")
    return sp.create_account_with_seed(
        sp.CreateAccountWithSeedParams(
            from_pubkey=funding,
            new_account_pubkey=created,
            base_pubkey=base,
            seed=seed,
            lamports=lamports,
            space=space,
            program_id=program,
        )
    )


def create_holder_account(account, operator, seed):
    return TransactionInstruction(
        keys=[
            AccountMeta(pubkey=account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=operator, is_signer=True, is_writable=False),
        ],
        program_id=PublicKey(EVM_LOADER),
        data=bytes.fromhex("24") + len(seed).to_bytes(8, "little") + seed,
    )


class neon_cli:
    def __init__(self, verbose_flags=""):
        self.verbose_flags = verbose_flags

    def call(self, arguments):
        cmd = "neon-cli {} --loglevel debug --commitment=processed --url {} {}".format(
            self.verbose_flags, SOLANA_URL, arguments
        )
        proc_result = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, universal_newlines=True)
        result = json.loads(proc_result.stdout)
        if result["result"] == "error":
            error = result["error"]
            raise Exception(f"ERR: neon-cli error {error}")

        proc_result.check_returncode()
        return result["value"]


# TODO: move to solana_client
def get_solana_balance(account):
    return solana_client.get_balance(account, commitment=Confirmed).value


def make_new_user(evm_loader: EvmLoader, sender: Keypair) -> Caller:
    key = Keypair.generate()
    if get_solana_balance(key.public_key) == 0:
        solana_client.request_airdrop(key.public_key, 1000 * 10**9, commitment=Confirmed)
        wait_for_account_to_exists(solana_client, key.public_key)
    print(get_solana_balance(key.public_key))
    caller_ether = eth_keys.PrivateKey(key.secret_key[:32]).public_key.to_canonical_address()
    caller_solana = evm_loader.ether2program(caller_ether)[0]
    caller_balance = evm_loader.ether2balance(caller_ether)
    caller_token = get_associated_token_address(caller_balance, NEON_TOKEN_MINT_ID)

    if get_solana_balance(caller_balance) == 0:
        print(f"Create Neon account {caller_ether} for user {caller_balance}")
        evm_loader.create_balance_account(caller_ether, sender)

    print("Account solana address:", key.public_key)
    print(
        f"Account ether address: {caller_ether.hex()}",
    )
    print(f"Account solana address: {caller_balance}")
    return Caller(key, PublicKey(caller_solana), caller_balance, caller_ether, caller_token)


def deposit_neon(evm_loader: EvmLoader, operator_keypair: Keypair, ether_address: Union[str, bytes], amount: int):
    balance_pubkey = evm_loader.ether2balance(ether_address)
    contract_pubkey = PublicKey(evm_loader.ether2program(ether_address)[0])

    evm_token_authority = PublicKey.find_program_address([b"Deposit"], evm_loader.loader_id)[0]
    evm_pool_key = get_associated_token_address(evm_token_authority, NEON_TOKEN_MINT_ID)

    token_pubkey = get_associated_token_address(operator_keypair.public_key, NEON_TOKEN_MINT_ID)

    with open("evm_loader-keypair.json", "r") as key:
        secret_key = json.load(key)[:32]
        mint_authority = Keypair.from_secret_key(secret_key)

    trx = Transaction()
    trx.add(
        make_CreateAssociatedTokenIdempotent(
            operator_keypair.public_key, operator_keypair.public_key, NEON_TOKEN_MINT_ID
        ),
        spl.token.instructions.mint_to(
            MintToParams(
                spl.token.constants.TOKEN_PROGRAM_ID,
                NEON_TOKEN_MINT_ID,
                token_pubkey,
                mint_authority.public_key,
                amount,
            )
        ),
        spl.token.instructions.approve(
            ApproveParams(
                spl.token.constants.TOKEN_PROGRAM_ID,
                token_pubkey,
                balance_pubkey,
                operator_keypair.public_key,
                amount,
            )
        ),
        make_DepositV03(
            evm_loader.ether2bytes(ether_address),
            CHAIN_ID,
            balance_pubkey,
            contract_pubkey,
            NEON_TOKEN_MINT_ID,
            token_pubkey,
            evm_pool_key,
            spl.token.constants.TOKEN_PROGRAM_ID,
            operator_keypair.public_key,
            evm_loader.loader_id,
        ),
    )

    receipt = evm_loader.sol_client.send_tx(trx, operator_keypair, mint_authority)

    return receipt
