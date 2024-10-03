import time

import pytest

from utils.accounts import EthAccounts
from utils.helpers import gen_hash_of_block
from utils.web3client import NeonChainWeb3Client


@pytest.mark.usefixtures("accounts", "web3_client")
class TestSendTrx:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts

    def test_contract_deploy_and_simple_call(self):
        sender_account = self.accounts[0]
        print("Sender balance:", self.web3_client.get_balance(sender_account))
        #time.sleep(5)
        erc173, _ = self.web3_client.deploy_and_get_contract("EIPs/ERC173", "0.8.10", sender_account)
        new_owner = self.accounts.create_account()
        print("Sender address:", sender_account.address)
        print("New owner address:", new_owner.address)
        tx = self.web3_client.make_raw_tx(sender_account)
        #time.sleep(5)
        instruction_tx = erc173.functions.transferOwnership(new_owner.address).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1
        #time.sleep(5)
        assert erc173.functions.owner().call() == new_owner.address

        event_logs = erc173.events.OwnershipTransferred().process_receipt(receipt)
        assert len(event_logs) == 1
        assert event_logs[0].args["previousOwner"] == sender_account.address
        assert event_logs[0].args["newOwner"] == new_owner.address
        assert event_logs[0].event == "OwnershipTransferred"

    def test_iterative_trx_with_alt(self):
        sender = self.accounts[0]
        time.sleep(5)
        contract, _ = self.web3_client.deploy_and_get_contract(
            contract="common/Common", version="0.8.12", contract_name="MappingActions", account=sender
        )

        tx = self.web3_client.make_raw_tx(sender.address)

        instruction_tx = contract.functions.replaceValues(10).build_transaction(tx)
        time.sleep(5)
        receipt = self.web3_client.send_transaction(sender, instruction_tx)
        assert receipt["status"] == 1

    def test_iterative_trx_erc721(self):
        acc = self.accounts[0]
        contract, contract_deploy_tx = self.web3_client.deploy_and_get_contract(
            "EIPs/ERC721/MultipleActions", "0.8.10", acc, contract_name="MultipleActionsERC721"
        )
        time.sleep(5)
        contract_balance_before = contract.functions.contractBalance().call()
        user_balance_before = contract.functions.balance(acc.address).call()

        tx = self.web3_client.make_raw_tx(acc)
        seed_1 = self.web3_client.text_to_bytes32(gen_hash_of_block(10))
        seed_2 = self.web3_client.text_to_bytes32(gen_hash_of_block(10))
        uri_1 = 'uri_1'
        uri_2 = 'uri_2'
        instruction_tx = contract.functions.mintMintTransferTransfer(
            seed_1, uri_1, seed_2, uri_2, acc.address, acc.address
        ).build_transaction(tx)
        self.web3_client.send_transaction(acc, instruction_tx)

        contract_balance = contract.functions.contractBalance().call()
        user_balance = contract.functions.balance(acc.address).call()

        assert user_balance == user_balance_before + 2, "User balance is not correct"
        assert contract_balance == contract_balance_before, "Contract balance is not correct"

    def test_iterative_trx_loop(self):
        acc = self.accounts[0]
        time.sleep(5)
        contract, _ = self.web3_client.deploy_and_get_contract("common/Counter", "0.8.10", account=acc)
        tx = self.web3_client.make_raw_tx(acc)
        time.sleep(5)
        instruction_tx = contract.functions.moreInstruction(0, 100).build_transaction(tx)  # 1086 steps in evm
        receipt = self.web3_client.send_transaction(acc, instruction_tx)
        assert receipt["status"] == 1
