import time

import pytest

from utils.accounts import EthAccounts
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
