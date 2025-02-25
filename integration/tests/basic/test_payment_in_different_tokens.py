import random

import allure
import pytest
import web3

from integration.tests.basic.helpers.chains import make_nonce_the_biggest_for_chain
from utils.web3client import NeonChainWeb3Client
from utils.accounts import EthAccounts
from utils.solana_client import SolanaClient


@allure.feature("Multiply token")
@allure.story("Payments in different tokens")
@pytest.mark.usefixtures("accounts", "web3_client", "sol_client")
class TestMultiplyChains:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts
    sol_client: SolanaClient

    @pytest.fixture(scope="class")
    def bob(self, class_account_sol_chain):
        return class_account_sol_chain

    @pytest.fixture(scope="class")
    def alice(self, sol_client, account_with_all_tokens):
        return account_with_all_tokens

    @pytest.fixture(scope="function")
    def check_neon_balance_does_not_changed(self, alice, bob, web3_client):
        alice_balance_before = web3_client.get_balance(alice)
        bob_balance_before = web3_client.get_balance(bob)
        yield
        alice_balance_after = web3_client.get_balance(alice)
        bob_balance_after = web3_client.get_balance(bob)
        assert alice_balance_after == alice_balance_before
        assert bob_balance_after == bob_balance_before

    @pytest.mark.multipletokens
    def test_user_to_user_trx(self, web3_client_sol, alice, bob, check_neon_balance_does_not_changed):
        bob_sol_balance_before = web3_client_sol.get_balance(bob)
        alice_sol_balance_before = web3_client_sol.get_balance(alice)
        value = 1000
        receipt = web3_client_sol.send_tokens(bob, alice, value)
        assert receipt["status"] == 1
        bob_sol_balance_after = web3_client_sol.get_balance(bob)
        alice_sol_balance_after = web3_client_sol.get_balance(alice)
        assert alice_sol_balance_after == alice_sol_balance_before + value
        assert bob_sol_balance_after < bob_sol_balance_before - value

    @pytest.mark.multipletokens
    def test_user_to_contract_and_contract_to_user_trx(
        self, web3_client_sol, bob, check_neon_balance_does_not_changed, wsol
    ):
        bob_sol_balance_before = web3_client_sol.get_balance(bob)
        contract_sol_balance_initial = web3_client_sol.get_balance(wsol.address)
        amount = 0.001
        value = web3_client_sol.to_atomic_currency(amount)
        tx = web3_client_sol.make_raw_tx(bob.address, amount=value)
        instruction_tx = wsol.functions.deposit().build_transaction(tx)
        receipt = web3_client_sol.send_transaction(bob, instruction_tx)
        assert receipt["status"] == 1
        bob_sol_balance_after_deposit = web3_client_sol.get_balance(bob)
        contract_sol_balance_after_deposit = web3_client_sol.get_balance(wsol.address)
        assert contract_sol_balance_after_deposit == contract_sol_balance_initial + web3_client_sol.to_atomic_currency(
            amount
        )
        assert bob_sol_balance_after_deposit < bob_sol_balance_before - value

        tx = web3_client_sol.make_raw_tx(bob.address)
        instruction_tx = wsol.functions.withdraw(value).build_transaction(tx)
        receipt = web3_client_sol.send_transaction(bob, instruction_tx)
        assert receipt["status"] == 1
        bob_sol_balance_after_withdraw = web3_client_sol.get_balance(bob)
        contract_sol_balance_after_withdraw = web3_client_sol.get_balance(wsol.address)
        assert contract_sol_balance_after_withdraw == contract_sol_balance_initial
        assert bob_sol_balance_after_withdraw < bob_sol_balance_after_deposit + value

    @pytest.mark.multipletokens
    def test_contract_to_contract_trx(self, web3_client_sol, bob):
        # contract to new contract
        amount = 0.0001
        value = web3_client_sol.to_atomic_currency(amount)
        bob_sol_balance_before = web3_client_sol.get_balance(bob)
        wsol_contract_caller, resp = web3_client_sol.deploy_and_get_contract(
            contract="common/WNativeChainToken",
            version="0.8.12",
            contract_name="WNativeChainTokenCaller",
            account=bob,
            value=value,
        )
        print(wsol_contract_caller.address)
        print(web3_client_sol.get_nonce(wsol_contract_caller.address))
        wrapper_address = wsol_contract_caller.events.Log().process_receipt(resp)[0].args["addr"]
        assert web3_client_sol.get_balance(wrapper_address) == value

        # contract to existing contract
        tx = web3_client_sol.make_raw_tx(bob.address, amount=value)
        instruction_tx = wsol_contract_caller.functions.deposit().build_transaction(tx)
        receipt = web3_client_sol.send_transaction(bob, instruction_tx)
        assert receipt["status"] == 1
        bob_sol_balance_after = web3_client_sol.get_balance(bob)

        assert web3_client_sol.get_balance(wrapper_address) == value * 2
        assert bob_sol_balance_after < bob_sol_balance_before - value * 2

    @pytest.mark.multipletokens
    def test_user_to_contract_wrong_chain_id_trx(
        self, web3_client_sol, bob, check_neon_balance_does_not_changed, event_caller_contract
    ):
        tx = self.web3_client.make_raw_tx(bob.address)
        instruction_tx = event_caller_contract.functions.unnamedArg("hello").build_transaction(tx)
        with pytest.raises(ValueError, match="wrong chain id"):
            web3_client_sol.send_transaction(bob, instruction_tx)

    @pytest.mark.multipletokens
    def test_deploy_contract(self, web3_client_sol, alice, check_neon_balance_does_not_changed):
        sol_balance_before = web3_client_sol.get_balance(alice)
        contract, _ = web3_client_sol.deploy_and_get_contract(
            contract="common/Common",
            version="0.8.12",
            contract_name="Common",
            account=alice,
        )
        sol_balance_after = web3_client_sol.get_balance(alice)
        assert sol_balance_after < sol_balance_before

    @pytest.mark.skip(reason="NDEV-2828")
    @pytest.mark.multipletokens
    def test_eip1820_sol_network(self, alice, bob, web3_client_sol):
        neon_balance_before = self.web3_client.get_balance(alice)
        sol_balance_before = web3_client_sol.get_balance(alice)
        instruction_tx = self.web3_client.make_raw_tx(alice.address, bob.address, 1000000, estimate_gas=True)
        instruction_tx.pop("chainId")
        receipt = web3_client_sol.send_transaction(alice, instruction_tx)
        assert receipt["status"] == 1
        assert neon_balance_before > self.web3_client.get_balance(alice)
        assert sol_balance_before == web3_client_sol.get_balance(alice)

    @pytest.mark.multipletokens
    def test_deploy_contract_with_sending_tokens(self, web3_client_sol, alice, check_neon_balance_does_not_changed):
        sol_alice_balance_before = web3_client_sol.get_balance(alice)
        value = 1000
        contract, receipt = web3_client_sol.deploy_and_get_contract(
            contract="common/WNativeChainToken",
            version="0.8.12",
            contract_name="WNativeChainToken",
            account=alice,
            value=value,
        )
        assert receipt["status"] == 1
        sol_alice_balance_after = web3_client_sol.get_balance(alice)
        contract_balance = web3_client_sol.get_balance(contract.address)
        assert contract_balance == value
        assert sol_alice_balance_after < sol_alice_balance_before - value

    @pytest.mark.multipletokens
    def test_deploy_contract_by_one_user_to_different_chains(
        self, web3_client_sol, solana_account, web3_client, pytestconfig, alice
    ):
        def deploy_contract(w3_client):
            _, rcpt = w3_client.deploy_and_get_contract(
                contract="common/Common", version="0.8.12", contract_name="Common", account=alice
            )
            return rcpt

        make_nonce_the_biggest_for_chain(alice, web3_client_sol, [web3_client])
        deploy_contract(web3_client_sol)

        with pytest.raises(web3.exceptions.ContractLogicError, match="Attempt to deploy to existing account"):
            deploy_contract(web3_client)

        make_nonce_the_biggest_for_chain(alice, web3_client, [web3_client_sol])
        receipt = deploy_contract(web3_client)
        assert receipt["status"] == 1

    @pytest.mark.multipletokens
    def test_interact_with_contract_from_another_chain(
        self, web3_client_sol, bob, check_neon_balance_does_not_changed, common_contract
    ):
        tx = web3_client_sol.make_raw_tx(bob.address)
        common_contract_sol_chain = web3_client_sol.get_deployed_contract(common_contract.address, "common/Common")
        number = random.randint(0, 1000000)
        instruction_tx = common_contract_sol_chain.functions.setNumber(number).build_transaction(tx)

        web3_client_sol.send_transaction(bob, instruction_tx)
        assert common_contract_sol_chain.functions.getNumber().call() == number
        assert common_contract.functions.getNumber().call() == number

    @pytest.mark.multipletokens
    def test_transfer_neons_in_sol_chain(self, web3_client_sol, web3_client, bob, alice, wneon):
        amount = 1
        value = self.web3_client._web3.to_wei(amount, "ether")
        tx = web3_client.make_raw_tx(bob.address, amount=value)

        instruction_tx = wneon.functions.deposit().build_transaction(tx)
        self.web3_client.send_transaction(bob, instruction_tx)

        wneon_sol_chain = web3_client_sol.get_deployed_contract(wneon.address, "common/WNeon", "WNEON", "0.4.26")

        tx = web3_client_sol.make_raw_tx(bob.address)

        neon_balance_before = web3_client.get_balance(alice.address)
        instruction_tx = wneon_sol_chain.functions.transfer(alice.address, value).build_transaction(tx)
        receipt = web3_client_sol.send_transaction(bob, instruction_tx)
        assert receipt["status"] == 1

        tx = web3_client_sol.make_raw_tx(alice.address)
        instruction_tx = wneon_sol_chain.functions.withdraw(value).build_transaction(tx)
        receipt = web3_client_sol.send_transaction(alice, instruction_tx)
        assert receipt["status"] == 1

        assert web3_client.get_balance(alice.address) == neon_balance_before + web3_client.to_atomic_currency(amount)

    @pytest.mark.multipletokens
    def test_transfer_sol_in_neon_chain(self, web3_client_sol, web3_client, bob, alice, wsol):
        amount = 0.001
        value = web3_client_sol.to_atomic_currency(amount)

        tx = web3_client_sol.make_raw_tx(bob.address, amount=value)

        instruction_tx = wsol.functions.deposit().build_transaction(tx)
        web3_client_sol.send_transaction(bob, instruction_tx)

        wsol_neon_chain = web3_client.get_deployed_contract(wsol.address, "common/WNativeChainToken")

        tx = self.web3_client.make_raw_tx(bob.address)
        sol_balance_before = web3_client_sol.get_balance(alice.address)
        instruction_tx = wsol_neon_chain.functions.transfer(alice.address, value).build_transaction(tx)
        receipt = self.web3_client.send_transaction(bob, instruction_tx)
        assert receipt["status"] == 1

        tx = self.web3_client.make_raw_tx(alice.address)
        instruction_tx = wsol_neon_chain.functions.withdraw(value).build_transaction(tx)
        receipt = self.web3_client.send_transaction(alice, instruction_tx)
        assert receipt["status"] == 1

        assert web3_client_sol.get_balance(alice.address) == sol_balance_before + value

    @pytest.mark.multipletokens
    def test_call_different_chains_contracts_in_one_transaction(
        self,
        alice,
        common_contract,
        web3_client_sol,
        web3_client_usdt,
        web3_client_eth,
        class_account_sol_chain,
    ):
        chains = {
            "neon": {"client": self.web3_client},
            "sol": {"client": web3_client_sol},
            "usdt": {"client": web3_client_usdt},
            "eth": {"client": web3_client_eth},
        }

        make_nonce_the_biggest_for_chain(alice, self.web3_client, [item["client"] for item in chains.values()])

        bunch_contract_neon, _ = self.web3_client.deploy_and_get_contract(
            contract="common/Common", version="0.8.12", contract_name="BunchActions", account=alice
        )
        for chain in chains:
            bunch_contract = chains[chain]["client"].get_deployed_contract(
                bunch_contract_neon.address, "common/Common", contract_name="BunchActions"
            )
            chains[chain]["bunch_contract"] = bunch_contract
            make_nonce_the_biggest_for_chain(
                alice, chains[chain]["client"], [item["client"] for item in chains.values()]
            )

            common_contract, _ = chains[chain]["client"].deploy_and_get_contract(
                contract="common/Common",
                version="0.8.12",
                account=alice,
            )
            chains[chain]["common_contract"] = common_contract

        for chain in chains:
            tx = chains[chain]["client"].make_raw_tx(alice.address)
            numbers = [random.randint(0, 1000000) for _ in range(len(chains))]
            instruction_tx = (
                chains[chain]["bunch_contract"]
                .functions.setNumber([item["common_contract"].address for item in chains.values()], numbers)
                .build_transaction(tx)
            )
            receipt = chains[chain]["client"].send_transaction(alice, instruction_tx)
            assert receipt["status"] == 1

            for i, item in enumerate(chains.values()):
                assert item["common_contract"].functions.getNumber().call() == numbers[i]

    @pytest.mark.multipletokens
    def test_send_non_neon_token_without_chain_id(self, account_with_all_tokens, web3_client_sol, sol_price, operator):
        # for transactions with non neon token and without chain_id NeonEVM should raise wrong chain id error
        # checks eip1820
        acc2 = web3_client_sol.create_account()

        instruction_tx = web3_client_sol.make_raw_tx(
            account_with_all_tokens.address, acc2.address, web3.Web3.to_wei(0.1, "ether"), estimate_gas=True
        )
        instruction_tx.pop("chainId")

        with pytest.raises(
            ValueError,
            match="wrong chain id",
        ):
            web3_client_sol.send_transaction(account_with_all_tokens, instruction_tx)
