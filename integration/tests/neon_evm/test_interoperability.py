import eth_abi
import pytest
import struct

from eth_utils import abi
from solana.keypair import Keypair
from solana.publickey import PublicKey

from integration.tests.neon_evm.solana_utils import  \
    EvmLoader, execute_trx_from_instruction_with_solana_call, execute_trx_from_instruction
from integration.tests.neon_evm.types.types import Contract, Caller
from integration.tests.neon_evm.utils.constants import TAG_FINALIZED_STATE
from integration.tests.neon_evm.utils.contract import make_contract_call_trx, deploy_contract
from integration.tests.neon_evm.utils.ethereum import make_eth_transaction
from integration.tests.neon_evm.utils.transaction_checks import check_holder_account_tag, \
    check_transaction_logs_have_text
from utils.helpers import bytes32_to_solana_pubkey, solana_pubkey_to_bytes32
from solana.transaction import AccountMeta, TransactionInstruction

from solana.system_program import transfer as solana_transfer, TransferParams

def find_contract_payer(evm_loader_id, eth_address):
    return PublicKey.find_program_address([b'\3', b'PAYER', eth_address], evm_loader_id)[0]

def unique(source):
    res = []
    [res.append(x) for x in source if x not in res]
    return res

class TestInteroperability:

    @pytest.fixture(scope="function")
    def solana_caller(self, evm_loader: EvmLoader, operator_keypair: Keypair, session_user: Caller,
                      treasury_pool) -> Contract:
        return deploy_contract(operator_keypair, session_user, "precompiled/CallSolanaCaller",
                               evm_loader, treasury_pool)

    def test_get_solana_address_by_neon_address(self, sender_with_tokens, solana_caller,
                                                neon_api_client):
        args = eth_abi.encode(['address'], [sender_with_tokens.eth_address.hex()])
        sol_addr = neon_api_client.call_contract_get_function(sender_with_tokens, solana_caller,
                                                              "getNeonAddress(address)", args)
        assert sender_with_tokens.solana_account_address == bytes32_to_solana_pubkey(sol_addr)

    def test_get_payer(self, sender_with_tokens, solana_caller, neon_api_client):
        payer = neon_api_client.call_contract_get_function(sender_with_tokens, solana_caller,
                                                           "getPayer()")
        assert bytes32_to_solana_pubkey(payer) != ""



    def test_execute_compute_budget(self, sender_with_tokens, solana_caller,
                                    neon_api_client, holder_acc, operator_keypair,
                                    evm_loader, treasury_pool, sol_client):
        program_id = 'ComputeBudget111111111111111111111111111111'
        is_signer = True
        is_writable = False
        DEFAULT_UNITS = 500 * 1000
        data = bytes.fromhex("02") + DEFAULT_UNITS.to_bytes(4, "little")
        program_id_bytes = solana_pubkey_to_bytes32(PublicKey(program_id))
        account_bytes = solana_pubkey_to_bytes32(sender_with_tokens.solana_account_address)
        acc_len = 1

        serialized_instructions = (
            bytes(PublicKey(program_id)) +
            acc_len.to_bytes(8, "little") + 

            # There are some limitations to use signers inside the program calls.
            # Generally you can use contract Solana PDA as signer (getNeonAddress(contract))
            # or special ext authority.
            # You can use external signer, but it should sign the transaction (and there is a problem
            # to emulate such transaction!).
            # For payment purposes it will be possible to use getPayer() account (feature is not implemented yet).
            #
            # But for ComputeBudget there is work without signer contract inside the account list.
            bytes(sender_with_tokens.balance_account_address) + (0).to_bytes(1, "little") + (0).to_bytes(1, "little") +
            len(data).to_bytes(8, "little") + data
        )

        print("serialised instructions", serialized_instructions.hex().encode('utf-8'))

        signed_tx = make_contract_call_trx(sender_with_tokens, solana_caller, "execute(uint64,bytes)",
                                           [0, serialized_instructions])
        
        func_name = abi.function_signature_to_4byte_selector('execute(uint64,bytes)')
        data = func_name + eth_abi.encode(['uint64', 'bytes'], [0, serialized_instructions])

        result = neon_api_client.emulate(sender_with_tokens.eth_address.hex(),
                                         contract=solana_caller.eth_address.hex(), data=data)
        # it works
        # result = neon_api_client.emulate(sender_with_tokens.eth_address.hex(),
        #                                  contract="0xFF00000000000000000000000000000000000006", data=data)
        print("emulation response:", result)

        resp = execute_trx_from_instruction_with_solana_call(operator_keypair, evm_loader, treasury_pool.account,
                                                              treasury_pool.buffer,
                                                              signed_tx,
                                                              [sender_with_tokens.balance_account_address,
                                                               PublicKey("83fAnx3LLG612mHbEh4HzXEpYwvSB5fqpwUS3sZkRuUB"),
                                                               PublicKey("ComputeBudget111111111111111111111111111111"),

                                                               solana_caller.balance_account_address,
                                                               solana_caller.solana_address],
                                                              operator_keypair)

        check_transaction_logs_have_text(resp.value, "exit_status=0x11")


        check_transaction_logs_have_text(resp.value.transaction.transaction.signatures[0], "exit_status=0x11")



    def test_execute_transfer(self, sender_with_tokens, solana_caller,
                                    neon_api_client, operator_keypair,
                                    evm_loader, treasury_pool):

        instruction = solana_transfer(TransferParams(
            from_pubkey=find_contract_payer(evm_loader.loader_id, solana_caller.eth_address),
            to_pubkey=PublicKey('DwLW2XwPd1demetQVrKMaHjb4eiZpwHHxPQNAXWa8Xb6'),
            lamports=1234511,
        ))
        self._execute_instruction(instruction, 1234511, sender_with_tokens, solana_caller,
                             neon_api_client, operator_keypair, evm_loader, treasury_pool)


    def _execute_instruction(self, instruction, required_lamports, sender_with_tokens, solana_caller,
                             neon_api_client, operator_keypair, evm_loader, treasury_pool):
        serialized_instructions = (
            bytes(instruction.program_id) +
            len(instruction.keys).to_bytes(8, "little") +
            b"".join(
                bytes(acc.pubkey) + (acc.is_signer).to_bytes(1, "little") + (acc.is_writable).to_bytes(1, "little")
                for acc in instruction.keys
            ) +
            len(instruction.data).to_bytes(8, "little") +
            instruction.data
        )
        print("serialised instructions", serialized_instructions.hex().encode('utf-8'))

        additional_keys = unique(
            [
                sender_with_tokens.balance_account_address,
                solana_caller.balance_account_address,
                solana_caller.solana_address,
                find_contract_payer(evm_loader.loader_id, solana_caller.eth_address),
                PublicKey('11111111111111111111111111111111'),
                PublicKey("83fAnx3LLG612mHbEh4HzXEpYwvSB5fqpwUS3sZkRuUB"),   # contract account for 0xFF00...0006
                instruction.program_id,
            ] + [acc.pubkey for acc in instruction.keys]
        )

        signed_tx = make_contract_call_trx(sender_with_tokens, solana_caller, "execute(uint64,bytes)",
                                           [required_lamports, serialized_instructions])
        
        func_name = abi.function_signature_to_4byte_selector('execute(uint64,bytes)')
        data = func_name + eth_abi.encode(['uint64', 'bytes'], [required_lamports, serialized_instructions])

        result = neon_api_client.emulate(sender_with_tokens.eth_address.hex(),
                                         contract=solana_caller.eth_address.hex(), data=data)
        # it works
        # result = neon_api_client.emulate(sender_with_tokens.eth_address.hex(),
        #                                  contract="0xFF00000000000000000000000000000000000006", data=data)
        print("emulation response:", result)

        resp = execute_trx_from_instruction_with_solana_call(operator_keypair, evm_loader, treasury_pool.account,
                                                              treasury_pool.buffer,
                                                              signed_tx,
                                                              additional_keys,
                                                              operator_keypair)

        check_transaction_logs_have_text(resp.value, "exit_status=0x11")



    def test_execute_call_memo(self, sender_with_tokens, neon_api_client, operator_keypair,
                               evm_loader, treasury_pool, sol_client):
        contract = deploy_contract(operator_keypair, sender_with_tokens, "precompiled/call_solana_test",
                                   evm_loader, treasury_pool, contract_name='Test')

        data = abi.function_signature_to_4byte_selector('call_memo()')

        signed_tx = make_eth_transaction(contract.eth_address, data, sender_with_tokens)
        result = neon_api_client.emulate(sender_with_tokens.eth_address.hex(),
                                         contract=contract.eth_address.hex(), data=data)
        print("emulation response:", result)

        resp = execute_trx_from_instruction_with_solana_call(operator_keypair, evm_loader,
                                                             treasury_pool.account,
                                                              treasury_pool.buffer,
                                                              signed_tx,
                                                              [sender_with_tokens.balance_account_address,
                                                               PublicKey("83fAnx3LLG612mHbEh4HzXEpYwvSB5fqpwUS3sZkRuUB"),
                                                               PublicKey("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"),
                                                               contract.balance_account_address,
                                                               contract.solana_address],
                                                              operator_keypair)
        check_transaction_logs_have_text(resp.value.transaction.transaction.signatures[0], "exit_status=0x11")
