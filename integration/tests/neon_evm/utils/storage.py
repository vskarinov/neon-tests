from hashlib import sha256
from random import randrange

from solana.publickey import PublicKey
from solana.keypair import Keypair

from solana.transaction import Transaction, TransactionInstruction, AccountMeta

from utils.evm_loader import EvmLoader
from ..solana_utils import get_solana_balance, create_account_with_seed, create_holder_account


def create_holder(signer: Keypair, evm_loader:EvmLoader, seed: str = None, size: int = None, fund: int = None,
                  storage: PublicKey = None, ) -> PublicKey:
    if size is None:
        size = 128 * 1024
    if fund is None:
        fund = 10 ** 9
    if seed is None:
        seed = str(randrange(1000000))
    if storage is None:
        storage = PublicKey(
            sha256(bytes(signer.public_key) + bytes(seed, 'utf8') + bytes(evm_loader.loader_id)).digest())

    print(f"Create holder account with seed: {seed}")

    if get_solana_balance(storage) == 0:
        trx = Transaction()
        trx.add(
            create_account_with_seed(signer.public_key, signer.public_key, seed, fund, size),
            create_holder_account(storage, signer.public_key, bytes(seed, 'utf8'))
        )
        evm_loader.sol_client.send_tx(trx, signer)
    print(f"Created holder account: {storage}")
    return storage


def delete_holder(del_key: PublicKey, acc: Keypair, signer: Keypair, evm_loader: EvmLoader):
    trx = Transaction()

    trx.add(TransactionInstruction(
        program_id=evm_loader.loader_id,
        data=bytes.fromhex("25"),
        keys=[
            AccountMeta(pubkey=del_key, is_signer=False, is_writable=True),
            AccountMeta(pubkey=acc.public_key, is_signer=(signer == acc), is_writable=True),
        ]))
    return evm_loader.sol_client.send_tx(trx, signer)
