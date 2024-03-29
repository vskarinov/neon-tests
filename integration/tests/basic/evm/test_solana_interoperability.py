import allure
import pytest
from solana.publickey import PublicKey
from solana.transaction import TransactionInstruction, AccountMeta

from utils.accounts import EthAccounts
from utils.helpers import solana_pubkey_to_bytes32
from utils.web3client import NeonChainWeb3Client


def serialize_instruction(program_id, instruction) -> bytes:
    program_id_bytes = solana_pubkey_to_bytes32(PublicKey(program_id))
    serialized = program_id_bytes + len(instruction.keys).to_bytes(8, "little")

    for key in instruction.keys:
        serialized += bytes(key.pubkey)
        serialized += key.is_signer.to_bytes(1, "little")
        serialized += key.is_writable.to_bytes(1, "little")

    serialized += len(instruction.data).to_bytes(8, "little") + instruction.data
    return serialized


@allure.feature("")
@allure.story("")
@pytest.mark.usefixtures("accounts", "web3_client", "sol_client_session")
class TestSolanaInteroperability:
    accounts: EthAccounts
    web3_client: NeonChainWeb3Client

    @pytest.fixture(scope="class")
    def call_solana_caller(self):
        contract, _ = self.web3_client.deploy_and_get_contract(
            "precompiled/CallSolanaCaller.sol",
            "0.8.10",
            self.accounts[0]
        )
        return contract

    def create_resource(self, contract, salt, sender, owner):
        tx = self.web3_client.make_raw_tx(sender.address)
        salt = self.web3_client.text_to_bytes32(salt)
        instruction_tx = contract.functions.createResource(salt, 8, 100000, bytes(owner)).build_transaction(tx)
        self.web3_client.send_transaction(sender, instruction_tx)

        return contract.functions.getResourceAddress(salt).call()

    def test_counter(self, call_solana_caller):
        sender = self.accounts[0]
        COUNTER_ID = PublicKey("4RJAXLPq1HrXWP4zFrMhvB5drrzqrRFwaRVNUnALcaeh")

        resource_addr = self.create_resource(call_solana_caller, "1", sender, COUNTER_ID)
        lamports = 0

        instruction = TransactionInstruction(
            program_id=COUNTER_ID,
            keys=[AccountMeta(resource_addr, is_signer=False, is_writable=True), ],
            data=bytes([0x1])
        )
        serialized = serialize_instruction(COUNTER_ID, instruction)

        tx = self.web3_client.make_raw_tx(sender.address)
        instruction_tx = call_solana_caller.functions.execute(lamports, serialized).build_transaction(tx)
        resp = self.web3_client.send_transaction(sender, instruction_tx)
        assert resp["status"] == 1

    def test_compute_budget(self, call_solana_caller):
        sender = self.accounts[0]
        solana_acc = call_solana_caller.functions.getNeonAddress(sender.address).call()
        COMPUTE_BUDGET_ID = PublicKey("ComputeBudget111111111111111111111111111111")

        DEFAULT_UNITS = 1_400_000
        lamports = 0
        instruction = TransactionInstruction(
            program_id=COMPUTE_BUDGET_ID,
            keys=[AccountMeta(solana_acc, is_signer=False, is_writable=False)],
            data=bytes.fromhex("02") + DEFAULT_UNITS.to_bytes(4, "little"),
        )

        serialized = serialize_instruction(COMPUTE_BUDGET_ID, instruction)

        tx = self.web3_client.make_raw_tx(sender.address)
        instruction_tx = call_solana_caller.functions.execute(lamports, serialized).build_transaction(tx)
        resp = self.web3_client.send_transaction(sender, instruction_tx)
        assert resp["status"] == 1
