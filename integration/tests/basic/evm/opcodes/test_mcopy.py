import allure
import pytest

from utils.accounts import EthAccounts
from utils.web3client import NeonChainWeb3Client


@allure.feature("Opcodes verifications")
@allure.story("EIP-5656: MCOPY - Memory copying instruction")
@pytest.mark.usefixtures("accounts", "web3_client")
class TestMcopyOpCode:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts

    @pytest.fixture(scope="class")
    def mcopy_checker(self, web3_client, faucet, accounts):
        contract, _ = web3_client.deploy_and_get_contract(
            "opcodes/EIP5656MCopy",
            "0.8.25",
            accounts[0],
            contract_name="MemoryCopyExample",
        )
        return contract

    def test_mcopy(self, mcopy_checker):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        result = mcopy_checker.functions.copy(0,1,5).call(tx)
        assert result == b'Hello'
