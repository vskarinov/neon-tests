import pytest

from eth_utils import abi
from solana.keypair import Keypair
from solana.rpc.commitment import Confirmed

from solana.transaction import TransactionInstruction, AccountMeta

from integration.tests.neon_evm.solana_utils import (
    EvmLoader,
    execute_trx_from_instruction_with_solana_call,
    solana_client,
)
from integration.tests.neon_evm.types.types import Caller
from integration.tests.neon_evm.utils.call_solana import SolanaCaller
from integration.tests.neon_evm.utils.constants import (
    COMPUTE_BUDGET_ID,
    MEMO_PROGRAM_ID,
    SOLANA_CALL_PRECOMPILED_ID,
    NEON_TOKEN_MINT_ID,
    COUNTER_ID,
)
from integration.tests.neon_evm.utils.contract import deploy_contract
from integration.tests.neon_evm.utils.ethereum import make_eth_transaction
from integration.tests.neon_evm.utils.instructions import make_CreateAssociatedTokenIdempotent
from integration.tests.neon_evm.utils.transaction_checks import check_transaction_logs_have_text

from utils.instructions import DEFAULT_UNITS
from utils.metaplex import ASSOCIATED_TOKEN_ACCOUNT_PROGRAM_ID


class TestInteroperability:
    @pytest.fixture(scope="function")
    def solana_caller(
        self, evm_loader: EvmLoader, operator_keypair: Keypair, session_user: Caller, treasury_pool, holder_acc
    ) -> SolanaCaller:
        return SolanaCaller(operator_keypair, session_user, evm_loader, treasury_pool, holder_acc)

    def test_get_solana_address_by_neon_address(self, sender_with_tokens, solana_caller):
        sol_addr = solana_caller.get_solana_address_by_neon_address(sender_with_tokens.eth_address.hex())
        assert sol_addr == sender_with_tokens.solana_account_address

    def test_get_payer(self, solana_caller):
        assert solana_caller.get_payer() != ""

    def test_create_resource(self, sender_with_tokens, solana_caller):
        salt = b"123"
        resource_address = solana_caller.get_resource_address(salt, sender_with_tokens)
        print("resource_address", resource_address)
        solana_caller.create_resource(sender_with_tokens, salt, 8, 1000000000, MEMO_PROGRAM_ID)
        acc_info = solana_client.get_account_info(resource_address, commitment=Confirmed)
        assert acc_info.value is not None

    def test_execute_from_instruction_for_compute_budget(self, sender_with_tokens, solana_caller):
        instruction = TransactionInstruction(
            program_id=COMPUTE_BUDGET_ID,
            keys=[AccountMeta(sender_with_tokens.solana_account_address, is_signer=False, is_writable=False)],
            data=bytes.fromhex("02") + DEFAULT_UNITS.to_bytes(4, "little"),
        )
        resp = solana_caller.execute(COMPUTE_BUDGET_ID, instruction, sender=sender_with_tokens)
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

    def test_execute_from_account_create_acc(self, sender_with_tokens, solana_caller):
        payer = solana_caller.get_payer()
        instruction = make_CreateAssociatedTokenIdempotent(
            payer, sender_with_tokens.solana_account_address, NEON_TOKEN_MINT_ID
        )
        resp = solana_caller.batch_execute(
            [(ASSOCIATED_TOKEN_ACCOUNT_PROGRAM_ID, 2039280, instruction)], sender_with_tokens
        )
        check_transaction_logs_have_text(resp.value, "exit_status=0x11")
