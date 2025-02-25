import allure
import pytest

from utils.helpers import generate_text
from utils.consts import ZERO_ADDRESS
from utils.accounts import EthAccounts
from utils.web3client import NeonChainWeb3Client


@allure.feature("Opcodes verifications")
@allure.story("Recursion contract deploy (create2 opcode)")
@pytest.mark.usefixtures("accounts", "web3_client")
class TestContractRecursion:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts

    def test_deploy_with_recursion(self, recursion_factory):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        instruction_tx = recursion_factory.functions.deployFirstContract().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1
        assert recursion_factory.functions.getFirstDeployedContractCount().call() == 3

        event_logs = recursion_factory.events.FirstContractDeployed().process_receipt(receipt)
        for event_log in event_logs:
            assert event_log["args"]["addr"] != ZERO_ADDRESS

    def test_deploy_with_recursion_via_create2(self, recursion_factory):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        salt = generate_text(min_len=5, max_len=7)
        instruction_tx = recursion_factory.functions.deploySecondContractViaCreate2(salt).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1

        event_logs = recursion_factory.events.SecondContractDeployed().process_receipt(receipt)
        addresses = [event_log["args"]["addr"] for event_log in event_logs]
        assert len(addresses) == 2
        assert ZERO_ADDRESS in addresses

    def test_deploy_with_recursion_via_create(self, recursion_factory):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        instruction_tx = recursion_factory.functions.deployFirstContractViaCreate().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1

        event_logs = recursion_factory.events.FirstContractDeployed().process_receipt(receipt)
        addresses = [event_log["args"]["addr"] for event_log in event_logs]
        assert len(addresses) == 3
        assert ZERO_ADDRESS not in addresses

    def test_deploy_to_the_same_address_via_create2_one_trx(self, recursion_factory):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        salt = generate_text(min_len=5, max_len=7)
        instruction_tx = recursion_factory.functions.deployViaCreate2Twice(salt).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1
        assert recursion_factory.functions.getThirdDeployedContractCount().call() == 2

        event_logs = recursion_factory.events.ThirdContractDeployed().process_receipt(receipt)
        addresses = [event_log["args"]["addr"] for event_log in event_logs]
        assert ZERO_ADDRESS in addresses

    def test_recursion_in_function_calls(self):
        sender_account = self.accounts[0]

        contract_caller2, _ = self.web3_client.deploy_and_get_contract(
            "common/Recursion", "0.8.10", sender_account, contract_name="RecursionCaller2"
        )
        depth = 5
        contract_caller1, _ = self.web3_client.deploy_and_get_contract(
            "common/Recursion",
            "0.8.10",
            sender_account,
            contract_name="RecursionCaller1",
            constructor_args=[depth, contract_caller2.address, False],
        )
        tx = self.web3_client.make_raw_tx(sender_account)
        instruction_tx = contract_caller1.functions.callContract2().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1
        event_logs = contract_caller1.events.SecondContractCalled().process_receipt(receipt)
        assert len(event_logs) == depth
        results = [event_log["args"]["result"] for event_log in event_logs]
        assert False not in results

    def test_recursion_in_constructor_calls(self):
        sender_account = self.accounts[0]
        contract_caller2, _ = self.web3_client.deploy_and_get_contract(
            "common/Recursion", "0.8.10", sender_account, contract_name="RecursionCaller2"
        )
        contract_caller1, _ = self.web3_client.deploy_and_get_contract(
            "common/Recursion",
            "0.8.10",
            sender_account,
            contract_name="RecursionCaller1",
            constructor_args=[5, contract_caller2.address, True],
        )

        assert contract_caller1.functions.depth().call() == 0
