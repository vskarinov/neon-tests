import eth_abi
import pytest

from eth_utils import abi, keccak
from solana.keypair import Keypair

from solana.transaction import TransactionInstruction, AccountMeta
from spl.token.constants import ASSOCIATED_TOKEN_PROGRAM_ID, TOKEN_PROGRAM_ID

from integration.tests.neon_evm.solana_utils import (
    EvmLoader,
    execute_trx_from_instruction_with_solana_call,
    execute_trx_from_account_with_solana_call,
    write_transaction_to_holder_account,
)
from integration.tests.neon_evm.types.types import Contract, Caller
from integration.tests.neon_evm.utils.constants import (
    COMPUTE_BUDGET_ID,
    MEMO_PROGRAM_ID,
    SOLANA_CALL_PRECOMPILED_ID,
    NEON_TOKEN_MINT_ID,
)
from integration.tests.neon_evm.utils.contract import make_contract_call_trx, deploy_contract
from integration.tests.neon_evm.utils.ethereum import make_eth_transaction
from integration.tests.neon_evm.utils.instructions import serialize_instruction, make_CreateAssociatedTokenIdempotent
from integration.tests.neon_evm.utils.transaction_checks import check_transaction_logs_have_text

from utils.helpers import bytes32_to_solana_pubkey
from utils.instructions import DEFAULT_UNITS
from utils.metaplex import ASSOCIATED_TOKEN_ACCOUNT_PROGRAM_ID


class TestInteroperability:
    @pytest.fixture(scope="function")
    def solana_caller(
        self, evm_loader: EvmLoader, operator_keypair: Keypair, session_user: Caller, treasury_pool
    ) -> Contract:
        return deploy_contract(
            operator_keypair, session_user, "precompiled/CallSolanaCaller", evm_loader, treasury_pool
        )

    def test_get_solana_address_by_neon_address(self, sender_with_tokens, solana_caller, neon_api_client):
        args = eth_abi.encode(["address"], [sender_with_tokens.eth_address.hex()])
        sol_addr = neon_api_client.call_contract_get_function(
            sender_with_tokens, solana_caller, "getNeonAddress(address)", args
        )
        assert sender_with_tokens.solana_account_address == bytes32_to_solana_pubkey(sol_addr)

    def test_get_payer(self, sender_with_tokens, solana_caller, neon_api_client):
        payer = neon_api_client.call_contract_get_function(sender_with_tokens, solana_caller, "getPayer()")
        assert bytes32_to_solana_pubkey(payer) != ""

    def test_execute_from_instruction_for_compute_budget(
        self,
        sender_with_tokens,
        solana_caller,
        neon_api_client,
        operator_keypair,
        evm_loader,
        treasury_pool,
        sol_client,
    ):
        instruction = TransactionInstruction(
            program_id=COMPUTE_BUDGET_ID,
            keys=[AccountMeta(sender_with_tokens.solana_account_address, is_signer=False, is_writable=False)],
            data=bytes.fromhex("02") + DEFAULT_UNITS.to_bytes(4, "little"),
        )
        serialized_instructions = serialize_instruction(COMPUTE_BUDGET_ID, instruction)
        signed_tx = make_contract_call_trx(
            sender_with_tokens, solana_caller, "execute(uint64,bytes)", [500000, serialized_instructions]
        )

        resp = execute_trx_from_instruction_with_solana_call(
            operator_keypair,
            evm_loader,
            treasury_pool.account,
            treasury_pool.buffer,
            signed_tx,
            [
                sender_with_tokens.balance_account_address,
                sender_with_tokens.solana_account_address,
                SOLANA_CALL_PRECOMPILED_ID,
                COMPUTE_BUDGET_ID,
                solana_caller.balance_account_address,
                solana_caller.solana_address,
            ],
            operator_keypair,
        )
        check_transaction_logs_have_text(resp.value, "exit_status=0x11")

    def test_execute_from_instruction_for_call_memo(
        self, sender_with_tokens, neon_api_client, operator_keypair, evm_loader, treasury_pool, sol_client
    ):
        contract = deploy_contract(
            operator_keypair,
            sender_with_tokens,
            "precompiled/call_solana_test",
            evm_loader,
            treasury_pool,
            contract_name="Test",
        )

        data = abi.function_signature_to_4byte_selector("call_memo()")
        signed_tx = make_eth_transaction(contract.eth_address, data, sender_with_tokens)

        resp = execute_trx_from_instruction_with_solana_call(
            operator_keypair,
            evm_loader,
            treasury_pool.account,
            treasury_pool.buffer,
            signed_tx,
            [
                sender_with_tokens.balance_account_address,
                SOLANA_CALL_PRECOMPILED_ID,
                MEMO_PROGRAM_ID,
                contract.balance_account_address,
                contract.solana_address,
            ],
            operator_keypair,
        )

        check_transaction_logs_have_text(resp.value, "exit_status=0x11")

    def test_execute_from_account_for_create_acc(
        self,
        sender_with_tokens,
        solana_caller,
        neon_api_client,
        holder_acc,
        operator_keypair,
        evm_loader,
        treasury_pool,
        sol_client,
    ):
        payer_bytes32 = neon_api_client.call_contract_get_function(sender_with_tokens, solana_caller, "getPayer()")
        payer = bytes32_to_solana_pubkey(payer_bytes32)
        instruction = make_CreateAssociatedTokenIdempotent(
            payer, sender_with_tokens.solana_account_address, NEON_TOKEN_MINT_ID
        )
        serialized_instruction = serialize_instruction(ASSOCIATED_TOKEN_PROGRAM_ID, instruction)

        execute_params = [(2039280, serialized_instruction)]
        calldata = keccak(text="batchExecute((uint64,bytes)[])")[:4] + eth_abi.encode(
            ["(uint64,bytes)[]"],
            [execute_params],
        )

        signed_tx = make_eth_transaction(solana_caller.eth_address, calldata, sender_with_tokens)

        write_transaction_to_holder_account(signed_tx, holder_acc, operator_keypair)

        accounts = [
            sender_with_tokens.balance_account_address,
            sender_with_tokens.solana_account_address,
            solana_caller.balance_account_address,
            solana_caller.solana_address,
            SOLANA_CALL_PRECOMPILED_ID,
            ASSOCIATED_TOKEN_ACCOUNT_PROGRAM_ID,
        ] + [acc.pubkey for acc in instruction.keys]
        resp = execute_trx_from_account_with_solana_call(
            operator_keypair,
            evm_loader,
            holder_acc,
            treasury_pool.account,
            treasury_pool.buffer,
            accounts,
            operator_keypair,
        )

        check_transaction_logs_have_text(resp.value, "exit_status=0x11")
