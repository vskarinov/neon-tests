import os
import typing
from hashlib import sha256
from typing import Union, Tuple

from base58 import b58encode
from eth_keys import keys as eth_keys
from eth_account.datastructures import SignedTransaction
from solana.keypair import Keypair
from solana.publickey import PublicKey
import solana.system_program as sp
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solana.transaction import AccountMeta, Transaction, TransactionInstruction
from solders.rpc.responses import SendTransactionResp, GetTransactionResp

from integration.tests.neon_evm.utils.constants import ACCOUNT_SEED_VERSION
from utils.instructions import TransactionWithComputeBudget, make_ExecuteTrxFromInstruction, make_WriteHolder, \
    make_ExecuteTrxFromAccount, make_PartialCallOrContinueFromRawEthereumTX, \
    make_ExecuteTrxFromAccountDataIterativeOrContinue
from utils.layouts import BALANCE_ACCOUNT_LAYOUT, CONTRACT_ACCOUNT_LAYOUT, STORAGE_CELL_LAYOUT

EVM_STEPS = 500
CHAIN_ID = int(os.environ.get("NEON_CHAIN_ID", 111))

class EvmLoader:
    def __init__(self, program_id, sol_client):
        EvmLoader.loader_id = PublicKey(program_id)
        self.loader_id = EvmLoader.loader_id
        self.sol_client = sol_client

    def create_balance_account(self, ether: Union[str, bytes], sender, chain_id=CHAIN_ID) -> PublicKey:
        account_pubkey = self.ether2balance(ether, chain_id)
        contract_pubkey = PublicKey(self.ether2program(ether)[0])
        print('createBalanceAccount: {} => {}'.format(ether, account_pubkey))

        #TODO: move to instructions
        data = bytes([0x30]) + self.ether2bytes(ether) + chain_id.to_bytes(8, 'little')
        trx = Transaction()
        trx.add(TransactionInstruction(
            program_id=self.loader_id,
            data=data,
            keys=[
                AccountMeta(pubkey=sender.public_key, is_signer=True, is_writable=True),
                AccountMeta(pubkey=sp.SYS_PROGRAM_ID, is_signer=False, is_writable=False),
                AccountMeta(pubkey=account_pubkey, is_signer=False, is_writable=True),
                AccountMeta(pubkey=contract_pubkey, is_signer=False, is_writable=True),
            ]))

        self.sol_client.send_tx(trx, sender)
        return account_pubkey


    def ether2program(self, ether: Union[str, bytes]) -> Tuple[str, int]:
        items = PublicKey.find_program_address([ACCOUNT_SEED_VERSION, self.ether2bytes(ether)], self.loader_id)
        return str(items[0]), items[1]

    def ether2balance(self, address: Union[str, bytes], chain_id=CHAIN_ID) -> PublicKey:
        address_bytes = self.ether2bytes(address)
        chain_id_bytes = chain_id.to_bytes(32, 'big')
        return PublicKey.find_program_address(
            [ACCOUNT_SEED_VERSION, address_bytes, chain_id_bytes],
            self.loader_id
        )[0]

    @staticmethod
    def ether2bytes(ether: Union[str, bytes]):
        if isinstance(ether, str):
            if ether.startswith('0x'):
                return bytes.fromhex(ether[2:])
            return bytes.fromhex(ether)
        return ether



    @staticmethod
    def ether2hex(ether: Union[str, bytes]):
        if isinstance(ether, str):
            if ether.startswith('0x'):
                return ether[2:]
            return ether
        return ether.hex()

    def account_with_seed(self, base, seed) -> PublicKey:
        return PublicKey(sha256(bytes(base) + bytes(seed, 'utf8') + bytes(self.loader_id)).digest())

    def ether2seed(self, ether: Union[str, bytes], solana_pubkey: PublicKey) -> Tuple[PublicKey, int]:
        seed = b58encode(ACCOUNT_SEED_VERSION + self.ether2bytes(ether)).decode('utf8')
        acc = self.account_with_seed(solana_pubkey, seed)
        print('ether2program: {} {} => {}'.format(self.ether2hex(ether), 255, acc))
        return acc, 255


    def get_neon_nonce(self, account: Union[str, bytes], chain_id=CHAIN_ID) -> int:
        solana_address = self.ether2balance(account, chain_id)

        info: bytes = self.get_solana_account_data(solana_address, BALANCE_ACCOUNT_LAYOUT.sizeof())
        layout = BALANCE_ACCOUNT_LAYOUT.parse(info)

        return layout.trx_count

    def get_solana_account_data(self, account: Union[str, PublicKey, Keypair],
                                expected_length: int) -> bytes:
        if isinstance(account, Keypair):
            account = account.public_key
        info = self.sol_client.get_account_info(account, commitment=Confirmed)
        info = info.value
        if info is None:
            raise Exception("Can't get information about {}".format(account))
        if len(info.data) < expected_length:
            print("len(data)({}) < expected_length({})".format(len(info.data), expected_length))
            raise Exception("Wrong data length for account data {}".format(account))
        return info.data

    def get_neon_balance(self, account: Union[str, bytes], chain_id=CHAIN_ID) -> int:
        balance_address = self.ether2balance(account, chain_id)

        info: bytes = self.get_solana_account_data(balance_address, BALANCE_ACCOUNT_LAYOUT.sizeof())
        layout = BALANCE_ACCOUNT_LAYOUT.parse(info)

        return int.from_bytes(layout.balance, byteorder="little")


    def get_contract_account_revision(self, address):
        account_data = self.get_solana_account_data(address, CONTRACT_ACCOUNT_LAYOUT.sizeof())
        return CONTRACT_ACCOUNT_LAYOUT.parse(account_data).revision

    def get_data_account_revision(self, address):
        account_data = self.get_solana_account_data(address, STORAGE_CELL_LAYOUT.sizeof())
        return STORAGE_CELL_LAYOUT.parse(account_data).revision


    def write_transaction_to_holder_account(self,
            signed_tx: SignedTransaction,
            holder_account: PublicKey,
            operator: Keypair,
    ):
        # Write transaction to transaction holder account
        offset = 0
        receipts = []
        rest = signed_tx.rawTransaction
        while len(rest):
            (part, rest) = (rest[:920], rest[920:])
            trx = Transaction()
            trx.add(make_WriteHolder(operator.public_key, self.loader_id, holder_account, signed_tx.hash, offset, part))
            receipts.append(
                self.sol_client.send_transaction(
                    trx,
                    operator,
                    opts=TxOpts(skip_confirmation=True, preflight_commitment=Confirmed),
                )
            )
            offset += len(part)

        for rcpt in receipts:
            self.sol_client.confirm_transaction(rcpt.value, commitment=Confirmed)

    def get_operator_balance_pubkey(self, operator: Keypair):
        operator_ether = eth_keys.PrivateKey(operator.secret_key[:32]).public_key.to_canonical_address()
        return self.ether2balance(operator_ether)
    def execute_trx_from_instruction(self, operator: Keypair, treasury_address: PublicKey,
                                     treasury_buffer: bytes,
                                     instruction: SignedTransaction,
                                     additional_accounts, signer: Keypair = None,
                                     system_program=sp.SYS_PROGRAM_ID) -> SendTransactionResp:
        signer = operator if signer is None else signer
        trx = TransactionWithComputeBudget(operator)
        operator_balance = self.get_operator_balance_pubkey(operator)

        trx.add(make_ExecuteTrxFromInstruction(operator, operator_balance, self.loader_id, treasury_address,
                                               treasury_buffer, instruction.rawTransaction, additional_accounts,
                                               system_program))

        return self.sol_client.send_tx(trx, signer)


    def execute_trx_from_instruction_with_solana_call(self, operator: Keypair, treasury_address: PublicKey,
                                                      treasury_buffer: bytes,
                                                      instruction: SignedTransaction,
                                                      additional_accounts, signer: Keypair = None,
                                                      system_program=sp.SYS_PROGRAM_ID) -> SendTransactionResp:
        signer = operator if signer is None else signer
        operator_balance_pubkey = self.get_operator_balance_pubkey(operator)
        trx = TransactionWithComputeBudget(operator)
        trx.add(make_ExecuteTrxFromInstruction(operator, operator_balance_pubkey, self.loader_id, treasury_address,
                                               treasury_buffer, instruction.rawTransaction, additional_accounts,
                                               system_program, tag=0x38))
        return self.sol_client.send_tx(trx, signer)


    def execute_trx_from_account_with_solana_call(self, operator: Keypair, holder_address,
                                                  treasury_address: PublicKey, treasury_buffer: bytes,
                                                  additional_accounts, signer: Keypair = None, additional_signers: typing.List[Keypair] = None,
                                                  system_program=sp.SYS_PROGRAM_ID) -> SendTransactionResp:
        signer = operator if signer is None else signer
        operator_balance_pubkey = self.get_operator_balance_pubkey(operator)
        trx = TransactionWithComputeBudget(operator)
        trx.add(make_ExecuteTrxFromAccount(operator, operator_balance_pubkey, self.loader_id, holder_address, treasury_address,
                                           treasury_buffer, additional_accounts, additional_signers,
                                           system_program, tag=0x39))

        signers = [signer, *additional_signers] if additional_signers else [signer]
        return self.sol_client.send_tx(trx, *signers)


    def send_transaction_step_from_instruction(self, operator: Keypair, operator_balance_pubkey, treasury, storage_account,
                                               instruction: SignedTransaction,
                                               additional_accounts, steps_count, signer: Keypair,
                                               system_program=sp.SYS_PROGRAM_ID, index=0, tag=0x34) -> GetTransactionResp:
        trx = TransactionWithComputeBudget(operator)

        trx.add(
            make_PartialCallOrContinueFromRawEthereumTX(
                index, steps_count, instruction.rawTransaction,
                operator, operator_balance_pubkey, self.loader_id, storage_account, treasury,
                additional_accounts, system_program, tag
            )
        )

        return self.sol_client.send_tx(trx, signer)


    def execute_transaction_steps_from_instruction(self, operator: Keypair, treasury, storage_account,
                                                   instruction: SignedTransaction,
                                                   additional_accounts,
                                                   signer: Keypair = None) -> GetTransactionResp:
        signer = operator if signer is None else signer
        operator_balance_pubkey = self.get_operator_balance_pubkey(operator)
        index = 0
        done = False
        while not done:
            receipt = self.send_transaction_step_from_instruction(operator, operator_balance_pubkey, treasury, storage_account, instruction,
                                                              additional_accounts, EVM_STEPS, signer, index=index)
            index += 1

            if receipt.value.transaction.meta.err:
                raise AssertionError(f"Transaction failed with error: {receipt.value.transaction.meta.err}")
            for log in receipt.value.transaction.meta.log_messages:
                if "exit_status" in log:
                    done = True
                    break
                if "ExitError" in log:
                    raise AssertionError(f"EVM Return error in logs: {receipt}")

        return receipt


    def send_transaction_step_from_account(self, operator: Keypair, operator_balance_pubkey, treasury, storage_account,
                                           additional_accounts, steps_count, signer: Keypair,
                                           system_program=sp.SYS_PROGRAM_ID,
                                           tag=0x35, index=0) -> GetTransactionResp:
        trx = TransactionWithComputeBudget(operator)
        trx.add(
            make_ExecuteTrxFromAccountDataIterativeOrContinue(
                index, steps_count,
                operator, operator_balance_pubkey, self.loader_id, storage_account, treasury,
                additional_accounts, system_program, tag
            )
        )
        return self.sol_client.send_tx(trx, signer)


    def execute_transaction_steps_from_account(self, operator: Keypair, treasury, storage_account,
                                               additional_accounts,
                                               signer: Keypair = None) -> GetTransactionResp:
        signer = operator if signer is None else signer
        operator_balance_pubkey = self.get_operator_balance_pubkey(operator)

        index = 0
        done = False

        while not done:
            receipt = self.send_transaction_step_from_account(operator, operator_balance_pubkey, treasury, storage_account,
                                                         additional_accounts, EVM_STEPS, signer, index=index)
            index += 1

            if receipt.value.transaction.meta.err:
                raise AssertionError(f"Can't deploy contract: {receipt.value.transaction.meta.err}")
            for log in receipt.value.transaction.meta.log_messages:
                if "exit_status" in log:
                    done = True
                    break
                if "ExitError" in log:
                    raise AssertionError(f"EVM Return error in logs: {receipt}")

        return receipt


    def execute_transaction_steps_from_account_no_chain_id(self, operator: Keypair, treasury,
                                                           storage_account,
                                                           additional_accounts,
                                                           signer: Keypair = None) -> GetTransactionResp:
        signer = operator if signer is None else signer
        operator_balance_pubkey = self.get_operator_balance_pubkey(operator)
        index = 0
        done = False
        while not done:
            receipt = self.send_transaction_step_from_account(operator, operator_balance_pubkey, treasury, storage_account,
                                                         additional_accounts, EVM_STEPS, signer, tag=0x36, index=index)
            index += 1

            if receipt.value.transaction.meta.err:
                raise AssertionError(f"Can't deploy contract: {receipt.value.transaction.meta.err}")
            for log in receipt.value.transaction.meta.log_messages:
                if "exit_status" in log:
                    done = True
                    break
                if "ExitError" in log:
                    raise AssertionError(f"EVM Return error in logs: {receipt}")

        return receipt
