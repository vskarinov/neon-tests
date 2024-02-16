import typing as tp

from eth_keys import keys as eth_keys
from solana.keypair import Keypair
from solana.publickey import PublicKey
import solana.system_program as sp
from solana.transaction import AccountMeta, TransactionInstruction, Transaction

from utils.helpers import solana_pubkey_to_bytes32
from .constants import EVM_LOADER
from solana.system_program import SYS_PROGRAM_ID
from solana.sysvar import SYSVAR_RENT_PUBKEY
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID, TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address

from ..types.types import TreasuryPool

DEFAULT_UNITS = 1_400_000
DEFAULT_HEAP_FRAME = 256 * 1024
DEFAULT_ADDITIONAL_FEE = 0
COMPUTE_BUDGET_ID: PublicKey = PublicKey("ComputeBudget111111111111111111111111111111")


class ComputeBudget:
    @staticmethod
    def request_units(operator, units, additional_fee):
        return TransactionInstruction(
            program_id=COMPUTE_BUDGET_ID,
            keys=[AccountMeta(PublicKey(operator.public_key), is_signer=True, is_writable=False)],
            data=bytes.fromhex("02") + units.to_bytes(4, "little"),  #  + additional_fee.to_bytes(4, "little")
        )

    @staticmethod
    def request_heap_frame(operator, heap_frame):
        return TransactionInstruction(
            program_id=COMPUTE_BUDGET_ID,
            keys=[AccountMeta(PublicKey(operator.public_key), is_signer=True, is_writable=False)],
            data=bytes.fromhex("01") + heap_frame.to_bytes(4, "little"),
        )


class TransactionWithComputeBudget(Transaction):
    def __init__(
        self,
        operator: Keypair,
        units=DEFAULT_UNITS,
        additional_fee=DEFAULT_ADDITIONAL_FEE,
        heap_frame=DEFAULT_HEAP_FRAME,
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        if units:
            self.add(ComputeBudget.request_units(operator, units, additional_fee))
        if heap_frame:
            self.add(ComputeBudget.request_heap_frame(operator, heap_frame))


def write_holder_layout(hash: bytes, offset: int, data: bytes):
    assert len(hash) == 32
    return bytes([0x26]) + hash + offset.to_bytes(8, byteorder="little") + data


def make_WriteHolder(operator: PublicKey, holder_account: PublicKey, hash: bytes, offset: int, payload: bytes):
    d = write_holder_layout(hash, offset, payload)

    return TransactionInstruction(
        program_id=PublicKey(EVM_LOADER),
        data=d,
        keys=[
            AccountMeta(pubkey=holder_account, is_signer=False, is_writable=True),
            AccountMeta(pubkey=operator, is_signer=True, is_writable=False),
        ],
    )


def make_ExecuteTrxFromInstruction(
    operator: Keypair,
    evm_loader: "EvmLoader",
    treasury_address: PublicKey,
    treasury_buffer: bytes,
    message: bytes,
    additional_accounts: tp.List[PublicKey],
    system_program=sp.SYS_PROGRAM_ID,
    tag=0x32,
):
    data = bytes([tag]) + treasury_buffer + message
    operator_ether = eth_keys.PrivateKey(operator.secret_key[:32]).public_key.to_canonical_address()
    print("make_ExecuteTrxFromInstruction accounts")
    print("Operator: ", operator.public_key)
    print("Treasury: ", treasury_address)
    print("Operator ether: ", operator_ether.hex())
    print("Operator eth solana: ", evm_loader.ether2balance(operator_ether))
    accounts = [
        AccountMeta(pubkey=operator.public_key, is_signer=True, is_writable=True),
        AccountMeta(pubkey=treasury_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=PublicKey(evm_loader.ether2balance(operator_ether)), is_signer=False, is_writable=True),
        AccountMeta(system_program, is_signer=False, is_writable=True),
    ]
    for acc in additional_accounts:
        print("Additional acc ", acc)
        accounts.append(
            AccountMeta(acc, is_signer=False, is_writable=True),
        )

    return TransactionInstruction(program_id=PublicKey(EVM_LOADER), data=data, keys=accounts)


def make_ExecuteTrxFromAccount(
    operator: Keypair,
    evm_loader: "EvmLoader",
    holder_address: PublicKey,
    treasury_address: PublicKey,
    treasury_buffer: bytes,
    additional_accounts: tp.List[PublicKey],
    additional_signers: tp.List[Keypair] = None,
    system_program=sp.SYS_PROGRAM_ID,
    tag=0x33,
):
    data = bytes([tag]) + treasury_buffer
    operator_ether = eth_keys.PrivateKey(operator.secret_key[:32]).public_key.to_canonical_address()
    print("make_ExecuteTrxFromInstruction accounts")
    print("Operator: ", operator.public_key)
    print("Treasury: ", treasury_address)
    print("Operator ether: ", operator_ether.hex())
    print("Operator eth solana: ", evm_loader.ether2balance(operator_ether))
    accounts = [
        AccountMeta(pubkey=holder_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=operator.public_key, is_signer=True, is_writable=True),
        AccountMeta(pubkey=treasury_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=PublicKey(evm_loader.ether2balance(operator_ether)), is_signer=False, is_writable=True),
        AccountMeta(system_program, is_signer=False, is_writable=True),
    ]
    for acc in additional_accounts:
        print("Additional acc ", acc)
        accounts.append(
            AccountMeta(acc, is_signer=False, is_writable=True),
        )
    if additional_signers:
        for acc in additional_signers:
            print("Additional acc ", acc.public_key)
            accounts.append(
                AccountMeta(acc.public_key, is_signer=True, is_writable=True),
            )
    return TransactionInstruction(program_id=PublicKey(EVM_LOADER), data=data, keys=accounts)


def make_ExecuteTrxFromAccountDataIterativeOrContinue(
    index: int,
    step_count: int,
    operator: Keypair,
    evm_loader: "EvmLoader",
    holder_address: PublicKey,
    treasury: TreasuryPool,
    additional_accounts: tp.List[PublicKey],
    sys_program_id=sp.SYS_PROGRAM_ID,
    tag=0x35,
):
    # 0x35 - TransactionStepFromAccount
    # 0x36 - TransactionStepFromAccountNoChainId
    data = tag.to_bytes(1, "little") + treasury.buffer + step_count.to_bytes(4, "little") + index.to_bytes(4, "little")
    operator_ether = eth_keys.PrivateKey(operator.secret_key[:32]).public_key.to_canonical_address()
    print("make_ExecuteTrxFromAccountDataIterativeOrContinue accounts")
    print("Holder: ", holder_address)
    print("Operator: ", operator.public_key)
    print("Treasury: ", treasury.account)
    print("Operator ether: ", operator_ether.hex())
    print("Operator eth solana: ", evm_loader.ether2balance(operator_ether))
    accounts = [
        AccountMeta(pubkey=holder_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=operator.public_key, is_signer=True, is_writable=True),
        AccountMeta(pubkey=treasury.account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=PublicKey(evm_loader.ether2balance(operator_ether)), is_signer=False, is_writable=True),
        AccountMeta(sys_program_id, is_signer=False, is_writable=True),
    ]

    for acc in additional_accounts:
        print("Additional acc ", acc)
        accounts.append(
            AccountMeta(acc, is_signer=False, is_writable=True),
        )

    return TransactionInstruction(program_id=PublicKey(EVM_LOADER), data=data, keys=accounts)


def make_PartialCallOrContinueFromRawEthereumTX(
    index: int,
    step_count: int,
    instruction: bytes,
    operator: Keypair,
    evm_loader: "EvmLoader",
    storage_address: PublicKey,
    treasury: TreasuryPool,
    additional_accounts: tp.List[PublicKey],
    system_program=sp.SYS_PROGRAM_ID,
    tag=0x34, #TransactionStepFromInstruction
):
    data = bytes([tag]) + treasury.buffer + step_count.to_bytes(4, "little") + index.to_bytes(4, "little") + instruction
    operator_ether = eth_keys.PrivateKey(operator.secret_key[:32]).public_key.to_canonical_address()

    accounts = [
        AccountMeta(pubkey=storage_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=operator.public_key, is_signer=True, is_writable=True),
        AccountMeta(pubkey=treasury.account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=evm_loader.ether2balance(operator_ether), is_signer=False, is_writable=True),
        AccountMeta(system_program, is_signer=False, is_writable=True),
    ]
    for acc in additional_accounts:
        accounts.append(
            AccountMeta(acc, is_signer=False, is_writable=True),
        )

    return TransactionInstruction(program_id=PublicKey(EVM_LOADER), data=data, keys=accounts)


def make_Cancel(
    evm_loader: "EvmLoader",
    storage_address: PublicKey,
    operator: Keypair,
    hash: bytes,
    additional_accounts: tp.List[PublicKey],
):
    data = bytes([0x37]) + hash
    operator_ether = eth_keys.PrivateKey(operator.secret_key[:32]).public_key.to_canonical_address()

    accounts = [
        AccountMeta(pubkey=storage_address, is_signer=False, is_writable=True),
        AccountMeta(pubkey=operator.public_key, is_signer=True, is_writable=True),
        AccountMeta(pubkey=evm_loader.ether2balance(operator_ether), is_signer=False, is_writable=True),
    ]

    for acc in additional_accounts:
        accounts.append(
            AccountMeta(acc, is_signer=False, is_writable=True),
        )

    return TransactionInstruction(program_id=PublicKey(EVM_LOADER), data=data, keys=accounts)


def make_DepositV03(
    ether_address: bytes,
    chain_id: int,
    balance_account: PublicKey,
    contract_account: PublicKey,
    mint: PublicKey,
    source: PublicKey,
    pool: PublicKey,
    token_program: PublicKey,
    operator_pubkey: PublicKey,
) -> TransactionInstruction:
    data = bytes([0x31]) + ether_address + chain_id.to_bytes(8, "little")

    accounts = [
        AccountMeta(pubkey=mint, is_signer=False, is_writable=True),
        AccountMeta(pubkey=source, is_signer=False, is_writable=True),
        AccountMeta(pubkey=pool, is_signer=False, is_writable=True),
        AccountMeta(pubkey=balance_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=contract_account, is_signer=False, is_writable=True),
        AccountMeta(pubkey=token_program, is_signer=False, is_writable=False),
        AccountMeta(pubkey=operator_pubkey, is_signer=True, is_writable=True),
        AccountMeta(pubkey=sp.SYS_PROGRAM_ID, is_signer=False, is_writable=False),
    ]

    return TransactionInstruction(program_id=PublicKey(EVM_LOADER), data=data, keys=accounts)


def make_CreateAssociatedTokenIdempotent(payer: PublicKey, owner: PublicKey, mint: PublicKey) -> TransactionInstruction:
    """Creates a transaction instruction to create an associated token account.

    Returns:
        The instruction to create the associated token account.
    """
    associated_token_address = get_associated_token_address(owner, mint)
    return TransactionInstruction(
        data=bytes([1]),
        keys=[
            AccountMeta(pubkey=payer, is_signer=True, is_writable=True),
            AccountMeta(pubkey=associated_token_address, is_signer=False, is_writable=True),
            AccountMeta(pubkey=owner, is_signer=False, is_writable=False),
            AccountMeta(pubkey=mint, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYS_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(pubkey=SYSVAR_RENT_PUBKEY, is_signer=False, is_writable=False),
        ],
        program_id=ASSOCIATED_TOKEN_PROGRAM_ID,
    )


def serialize_instruction(program_id, instruction) -> bytes:
    program_id_bytes = solana_pubkey_to_bytes32(PublicKey(program_id))
    serialized = program_id_bytes + len(instruction.keys).to_bytes(8, "little")

    for key in instruction.keys:
        serialized += bytes(key.pubkey)
        serialized += key.is_signer.to_bytes(1, "little")
        serialized += key.is_writable.to_bytes(1, "little")

    serialized += len(instruction.data).to_bytes(8, "little") + instruction.data
    return serialized
