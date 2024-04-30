import pytest
import allure
import web3

from utils.web3client import NeonChainWeb3Client
from utils.accounts import EthAccounts


@allure.story("Expected proxy errors during contract calls")
@pytest.mark.usefixtures("accounts", "web3_client")
class TestExpectedErrors:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts

    def test_bump_allocator_out_of_memory_expected_error(self):
        sender_account = self.accounts[0]
        contract, _ = self.web3_client.deploy_and_get_contract(
            "common/ExpectedErrorsChecker", "0.8.12", sender_account, contract_name="A"
        )

        tx = self.web3_client.make_raw_tx(sender_account)
        instruction_tx = contract.functions.method1().build_transaction(tx)
        try:
            resp = self.web3_client.send_transaction(sender_account, instruction_tx)
            assert resp["status"] == 0
        except ValueError as exc:
            assert "Error: memory allocation failed, out of memory." in exc.args[0]["message"]

    def test_send_non_neon_token_without_chain_id(self, account_with_all_tokens, web3_client_sol, sol_price, operator):
        # for transactions with non neon token and without chain_id NeonEVM should raise wrong chain id error
        # checks eip1820
        acc2 = web3_client_sol.create_account()

        instruction_tx = web3_client_sol.make_raw_tx(
            account_with_all_tokens.address, acc2.address, web3.Web3.to_wei(0.1, "ether"), estimate_gas=True
        )
        instruction_tx.pop("chainId")

        try:
            web3_client_sol.send_transaction(account_with_all_tokens, instruction_tx)
        except ValueError as e:
            assert "wrong chain id" in str(e.args)
            return
