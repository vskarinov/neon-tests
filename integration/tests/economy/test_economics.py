import json
import os
import random
from decimal import Decimal

import allure
import pytest
import rlp
import web3
from _pytest.config import Config
from solana.keypair import Keypair as SolanaAccount
from solana.publickey import PublicKey
from solana.rpc.types import Commitment, TxOpts
from solana.transaction import Transaction
from spl.token.instructions import (
    create_associated_token_account,
    get_associated_token_address,
)

from utils.consts import LAMPORT_PER_SOL, Time
from utils.erc20 import ERC20
from utils.helpers import wait_condition, gen_hash_of_block
from .const import INSUFFICIENT_FUNDS_ERROR, GAS_LIMIT_ERROR, BIG_STRING, TX_COST
from .steps import (
    wait_for_block,
    assert_profit,
    get_gas_used_percent,
    check_alt_on,
    check_alt_off,
    get_sol_trx_with_alt,
)

from ..basic.helpers.chains import make_nonce_the_biggest_for_chain


@pytest.fixture(scope="class", autouse=True)
def heat_stand(web3_client, faucet):
    """After redeploy stand, first 10-20 requests spend more sols than expected."""
    if "CI" not in os.environ:
        return
    acc = web3_client.eth.account.create()
    faucet.request_neon(acc.address, 100)
    for _ in range(20):
        web3_client.send_neon(acc, web3_client.eth.account.create(), 1)


@allure.story("Operator economy")
class TestEconomics:
    @pytest.mark.only_stands
    def test_account_creation(self, client_and_price, operator):
        """Verify account creation spend SOL"""
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        neon_balance_before = operator.get_token_balance(w3_client)
        acc = w3_client.eth.account.create()
        assert w3_client.get_balance(acc.address) == Decimal(0)
        sol_balance_after = operator.get_solana_balance()
        neon_balance_after = operator.get_token_balance(w3_client)
        assert neon_balance_after == neon_balance_before
        assert sol_balance_after == sol_balance_before

    def test_send_neon_to_non_existent_account(self, account_with_all_tokens, client_and_price, sol_price, operator):
        """Verify how many cost transfer of native chain token to new user"""
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)
        transfer_value = 50000000
        acc2 = w3_client.create_account()
        receipt = w3_client.send_tokens(account_with_all_tokens, acc2, transfer_value)
        assert w3_client.get_balance(acc2) == transfer_value

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        sol_diff = sol_balance_before - sol_balance_after

        assert sol_balance_before > sol_balance_after, "Operator SOL balance incorrect"
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(sol_diff, sol_price, token_diff, token_price, w3_client.native_token_name)
        get_gas_used_percent(w3_client, receipt)

    def test_send_tokens_to_exist_account(self, account_with_all_tokens, client_and_price, sol_price, operator):
        """Verify how many cost token send to use who was already initialized"""
        w3_client, token_price = client_and_price
        acc2 = w3_client.create_account()
        transfer_value = 5000
        w3_client.send_tokens(account_with_all_tokens, acc2, transfer_value // 2)

        assert w3_client.get_balance(acc2) == transfer_value // 2

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)
        receipt = w3_client.send_tokens(account_with_all_tokens, acc2, transfer_value // 2)

        assert w3_client.get_balance(acc2) == transfer_value

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        sol_diff = sol_balance_before - sol_balance_after
        get_gas_used_percent(w3_client, receipt)

        assert sol_balance_before > sol_balance_after, "Operator balance after send tx doesn't changed"
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(sol_diff, sol_price, token_diff, token_price, w3_client.native_token_name)

    def test_send_neon_token_without_chain_id(
        self, account_with_all_tokens, web3_client, sol_price, operator, neon_price
    ):
        # for neon token transactions without chain_id NeonEVM execute it inside NEON network
        # checks eip1820
        acc2 = web3_client.create_account()
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(web3_client)

        instruction_tx = web3_client.make_raw_tx(
            account_with_all_tokens.address, acc2.address, web3.Web3.to_wei(0.1, "ether"), estimate_gas=True
        )
        instruction_tx.pop("chainId")

        web3_client.send_transaction(account_with_all_tokens, instruction_tx)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(web3_client)
        sol_diff = sol_balance_before - sol_balance_after

        token_diff = web3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(sol_diff, sol_price, token_diff, neon_price, web3_client.native_token_name)

    def test_send_when_not_enough_tokens_to_gas(self, client_and_price, account_with_all_tokens, operator):
        w3_client, token_price = client_and_price
        acc2 = w3_client.create_account()

        assert w3_client.get_balance(acc2) == 0
        transfer_amount = 5000
        w3_client.send_tokens(account_with_all_tokens, acc2, transfer_amount)
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        acc3 = w3_client.create_account()

        with pytest.raises(ValueError, match=INSUFFICIENT_FUNDS_ERROR) as e:
            w3_client.send_tokens(acc2, acc3, transfer_amount)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before == sol_balance_after
        assert token_balance_before == token_balance_after

    def test_erc20wrapper_transfer(self, erc20_wrapper, client_and_price, sol_price, operator, accounts):
        sender_account = accounts[0]
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)
        assert erc20_wrapper.contract.functions.balanceOf(sender_account.address).call() == 0
        transfer_tx = erc20_wrapper.transfer(erc20_wrapper.account, sender_account, 25)

        assert erc20_wrapper.contract.functions.balanceOf(sender_account.address).call() == 25
        wait_condition(lambda: sol_balance_before > operator.get_solana_balance())
        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        sol_diff = sol_balance_before - sol_balance_after

        assert sol_balance_before > sol_balance_after
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)

        assert_profit(sol_diff, sol_price, token_diff, token_price, w3_client.native_token_name)

        get_gas_used_percent(w3_client, transfer_tx)

    def test_erc721_mint(self, erc721, client_and_price, account_with_all_tokens, sol_price, operator):
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)
        seed = w3_client.text_to_bytes32(gen_hash_of_block(8))

        erc721.mint(seed, account_with_all_tokens.address, "uri")

        wait_condition(lambda: sol_balance_before > operator.get_solana_balance())
        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        sol_diff = sol_balance_before - sol_balance_after

        assert sol_balance_before > sol_balance_after
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(sol_diff, sol_price, token_diff, token_price, w3_client.native_token_name)

    def test_withdraw_neon_unexisting_ata(
        self, pytestconfig: Config, neon_price, sol_price, sol_client, operator, web3_client, accounts
    ):
        sender_account = accounts[0]
        sol_user = SolanaAccount()
        sol_client.request_airdrop(sol_user.public_key, 5 * LAMPORT_PER_SOL)

        sol_balance_before = operator.get_solana_balance()
        neon_balance_before = operator.get_token_balance(web3_client)

        user_neon_balance_before = web3_client.get_balance(sender_account)
        move_amount = web3_client._web3.to_wei(5, "ether")

        contract, _ = web3_client.deploy_and_get_contract("precompiled/NeonToken", "0.8.10", account=sender_account)

        tx = self.web3_client.make_raw_tx(sender_account, amount=move_amount)

        instruction_tx = contract.functions.withdraw(bytes(sol_user.public_key)).build_transaction(tx)

        receipt = web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1

        assert (user_neon_balance_before - web3_client.get_balance(sender_account)) > 5

        balance = sol_client.get_account_info_json_parsed(sol_user.public_key, commitment=Commitment("confirmed"))
        assert int(balance.value.lamports) == int(move_amount / 1_000_000_000)

        sol_balance_after = operator.get_solana_balance()
        neon_balance_after = operator.get_token_balance(web3_client)

        assert sol_balance_before > sol_balance_after
        assert neon_balance_after > neon_balance_before

        neon_diff = web3_client.to_main_currency(neon_balance_after - neon_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after,
            sol_price,
            neon_diff,
            neon_price,
            web3_client.native_token_name,
        )

        get_gas_used_percent(web3_client, receipt)

    def test_withdraw_neon_existing_ata(
        self,
        pytestconfig,
        neon_mint,
        neon_price,
        sol_price,
        sol_client,
        operator,
        web3_client,
        accounts,
        withdraw_contract,
    ):
        sender_account = accounts[0]
        sol_user = SolanaAccount()
        sol_client.request_airdrop(sol_user.public_key, 5 * LAMPORT_PER_SOL)

        wait_condition(lambda: sol_client.get_balance(sol_user.public_key) != 0)

        trx = Transaction()
        trx.add(create_associated_token_account(sol_user.public_key, sol_user.public_key, neon_mint))

        sol_client.send_tx_and_check_status_ok(trx, sol_user)

        dest_token_acc = get_associated_token_address(sol_user.public_key, neon_mint)

        sol_balance_before = operator.get_solana_balance()
        neon_balance_before = operator.get_token_balance(web3_client)

        user_neon_balance_before = web3_client.get_balance(sender_account)
        move_amount = web3_client._web3.to_wei(5, "ether")

        tx = web3_client.make_raw_tx(sender_account, amount=move_amount)
        instruction_tx = withdraw_contract.functions.withdraw(bytes(sol_user.public_key)).build_transaction(tx)

        receipt = web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1

        assert (user_neon_balance_before - web3_client.get_balance(sender_account)) > 5

        balances = json.loads(sol_client.get_token_account_balance(dest_token_acc, Commitment("confirmed")).to_json())
        assert int(balances["result"]["value"]["amount"]) == int(move_amount / 1_000_000_000)

        sol_balance_after = operator.get_solana_balance()
        neon_balance_after = operator.get_token_balance(web3_client)

        assert sol_balance_before > sol_balance_after
        assert neon_balance_after > neon_balance_before

        neon_diff = web3_client.to_main_currency(neon_balance_after - neon_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after,
            sol_price,
            neon_diff,
            neon_price,
            web3_client.native_token_name,
        )
        get_gas_used_percent(web3_client, receipt)

    def test_erc20_transfer(
        self, client_and_price, account_with_all_tokens, web3_client_sol, web3_client, sol_price, operator, faucet
    ):
        """Verify ERC20 token send"""
        w3_client, token_price = client_and_price
        make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
        contract = ERC20(w3_client, faucet, owner=account_with_all_tokens)

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        acc2 = w3_client.create_account()

        transfer_tx = contract.transfer(account_with_all_tokens, acc2, 25)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        sol_diff = sol_balance_before - sol_balance_after

        assert sol_balance_before > sol_balance_after
        assert token_balance_after > token_balance_before

        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(sol_diff, sol_price, token_diff, token_price, w3_client.native_token_name)
        get_gas_used_percent(w3_client, transfer_tx)

    def test_deploy_small_contract_less_100tx(
        self, account_with_all_tokens, client_and_price, web3_client_sol, web3_client, sol_price, operator
    ):
        """Verify we are bill minimum for 100 instruction"""
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
        contract, _ = w3_client.deploy_and_get_contract("common/Counter", "0.8.10", account=account_with_all_tokens)

        sol_balance_after_deploy = operator.get_solana_balance()
        token_balance_after_deploy = operator.get_token_balance(w3_client)
        tx = w3_client.make_raw_tx(account_with_all_tokens.address)

        inc_tx = contract.functions.inc().build_transaction(tx)

        assert contract.functions.get().call() == 0
        receipt = w3_client.send_transaction(account_with_all_tokens, inc_tx)
        assert contract.functions.get().call() == 1

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after_deploy > sol_balance_after
        assert token_balance_after > token_balance_after_deploy > token_balance_before
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, receipt)

    def test_deploy_to_lost_contract_account(self, account_with_all_tokens, client_and_price, sol_price, operator):
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        acc2 = w3_client.create_account()
        w3_client.send_tokens(account_with_all_tokens, acc2, 1)

        with pytest.raises(ValueError, match=INSUFFICIENT_FUNDS_ERROR):
            w3_client.deploy_and_get_contract("common/Counter", "0.8.10", account=acc2)
        w3_client.send_tokens(account_with_all_tokens, acc2, int(w3_client.get_balance(account_with_all_tokens) // 10))
        contract, contract_deploy_tx = w3_client.deploy_and_get_contract("common/Counter", "0.8.10", account=acc2)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after
        assert token_balance_after > token_balance_before

        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, contract_deploy_tx)

    def test_contract_get_is_free(self, counter_contract, client_and_price, account_with_all_tokens, operator):
        """Verify that get contract calls is free"""
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        user_balance_before = w3_client.get_balance(account_with_all_tokens)
        assert counter_contract.functions.get().call() == 0

        assert w3_client.get_balance(account_with_all_tokens) == user_balance_before

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        assert sol_balance_before == sol_balance_after
        assert token_balance_before == token_balance_after

    @pytest.mark.xfail(reason="https://neonlabs.atlassian.net/browse/NDEV-699")
    def test_cost_resize_account(self, neon_price, sol_price, operator, web3_client, accounts):
        """Verify how much cost account resize"""
        sender_account = accounts[0]
        sol_balance_before = operator.get_solana_balance()
        neon_balance_before = operator.get_token_balance(web3_client)

        contract, contract_deploy_tx = web3_client.deploy_and_get_contract(
            "common/IncreaseStorage", "0.8.10", account=sender_account
        )

        sol_balance_before_increase = operator.get_solana_balance()
        neon_balance_before_increase = operator.get_token_balance(web3_client)

        tx = web3_client.make_raw_tx(sender_account)
        inc_tx = contract.functions.inc().build_transaction(tx)

        instruction_receipt = web3_client.send_transaction(sender_account, inc_tx)

        sol_balance_after = operator.get_solana_balance()
        neon_balance_after = operator.get_token_balance(web3_client)

        assert sol_balance_before > sol_balance_before_increase > sol_balance_after, "SOL Balance not changed"
        assert neon_balance_after > neon_balance_before_increase > neon_balance_before, "NEON Balance incorrect"
        neon_diff = web3_client.to_main_currency(neon_balance_after - neon_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after,
            sol_price,
            neon_diff,
            neon_price,
            web3_client.native_token_name,
        )
        get_gas_used_percent(web3_client, instruction_receipt)

    def test_contract_interact_1000_steps(
        self, counter_contract, client_and_price, account_with_all_tokens, sol_price, operator
    ):
        """Deploy a contract with more 500 instructions"""
        w3_client, token_price = client_and_price

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)
        tx = w3_client.make_raw_tx(account_with_all_tokens.address)

        instruction_tx = counter_contract.functions.moreInstruction(0, 100).build_transaction(tx)  # 1086 steps in evm
        instruction_receipt = w3_client.send_transaction(account_with_all_tokens, instruction_tx)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after, "SOL Balance not changed"
        assert token_balance_after > token_balance_before, "TOKEN Balance incorrect"
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, instruction_receipt)

    def test_contract_interact_500000_steps(
        self, counter_contract, client_and_price, account_with_all_tokens, sol_price, operator
    ):
        """Deploy a contract with more 500000 bpf"""
        w3_client, token_price = client_and_price

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)
        tx = w3_client.make_raw_tx(account_with_all_tokens.address)

        instruction_tx = counter_contract.functions.moreInstruction(0, 3000).build_transaction(tx)

        instruction_receipt = w3_client.send_transaction(account_with_all_tokens, instruction_tx)

        wait_condition(lambda: sol_balance_before > operator.get_solana_balance())

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after, "SOL Balance not changed"
        assert token_balance_after > token_balance_before, "TOKEN Balance incorrect"

        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, instruction_receipt)

    def test_send_transaction_with_gas_limit_reached(
        self, counter_contract, client_and_price, account_with_all_tokens, operator
    ):
        """Transaction with small amount of gas"""
        w3_client, token_price = client_and_price

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        tx = w3_client.make_raw_tx(account_with_all_tokens.address, gas=1000)
        instruction_tx = counter_contract.functions.moreInstruction(0, 100).build_transaction(tx)

        with pytest.raises(ValueError, match=GAS_LIMIT_ERROR):
            w3_client.send_transaction(account_with_all_tokens, instruction_tx)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_after == sol_balance_before, "SOL Balance changes"
        assert token_balance_after == token_balance_before, "TOKEN Balance incorrect"

    def test_send_transaction_with_insufficient_funds(
        self, counter_contract, client_and_price, account_with_all_tokens, operator
    ):
        """Transaction with insufficient funds on balance"""
        w3_client, token_price = client_and_price
        acc2 = w3_client.create_account()
        w3_client.send_tokens(account_with_all_tokens, acc2, 100)

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        tx = w3_client.make_raw_tx(acc2.address)

        instruction_tx = counter_contract.functions.moreInstruction(0, 1500).build_transaction(tx)
        with pytest.raises(ValueError, match=INSUFFICIENT_FUNDS_ERROR):
            w3_client.send_transaction(acc2, instruction_tx)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before == sol_balance_after, "SOL Balance changed"
        assert token_balance_after == token_balance_before, "TOKEN Balance incorrect"

    def test_tx_interact_more_1kb(
        self, counter_contract, client_and_price, account_with_all_tokens, sol_price, operator
    ):
        """Send to contract a big text (tx more than 1 kb)"""
        w3_client, token_price = client_and_price
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        tx = w3_client.make_raw_tx(account_with_all_tokens.address)

        instruction_tx = counter_contract.functions.bigString(BIG_STRING).build_transaction(tx)

        instruction_receipt = w3_client.send_transaction(account_with_all_tokens, instruction_tx)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after, "SOL Balance not changed"
        assert token_balance_after > token_balance_before, "TOKEN Balance incorrect"

        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, instruction_receipt)

    def test_deploy_contract_more_1kb(
        self, client_and_price, account_with_all_tokens, web3_client, web3_client_sol, sol_price, operator
    ):
        w3_client, token_price = client_and_price

        make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        contract, contract_deploy_tx = w3_client.deploy_and_get_contract(
            "common/Fat", "0.8.10", account=account_with_all_tokens
        )

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after
        assert token_balance_after > token_balance_before

        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, contract_deploy_tx)

    def test_deploy_contract_to_payed(
        self, client_and_price, account_with_all_tokens, web3_client, web3_client_sol, sol_price, operator, accounts
    ):
        sender_account = accounts[0]
        w3_client, token_price = client_and_price
        make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
        nonce = w3_client.eth.get_transaction_count(account_with_all_tokens.address)
        contract_address = w3_client.keccak(rlp.encode((bytes.fromhex(sender_account.address[2:]), nonce)))[-20:]

        w3_client.send_tokens(account_with_all_tokens, w3_client.to_checksum_address(contract_address.hex()), 5000)

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        contract, contract_deploy_tx = w3_client.deploy_and_get_contract(
            "common/Counter", "0.8.10", account=account_with_all_tokens
        )

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after, "SOL Balance not changed"
        assert token_balance_after > token_balance_before, "TOKEN Balance incorrect"
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, contract_deploy_tx)

    def test_deploy_contract_to_exist_unpayed(
        self, client_and_price, account_with_all_tokens, web3_client, web3_client_sol, sol_price, operator
    ):
        w3_client, token_price = client_and_price

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
        nonce = w3_client.eth.get_transaction_count(account_with_all_tokens.address)
        contract_address = w3_client.to_checksum_address(
            w3_client.keccak(rlp.encode((bytes.fromhex(account_with_all_tokens.address[2:]), nonce)))[-20:].hex()
        )
        with pytest.raises(ValueError, match=GAS_LIMIT_ERROR):
            w3_client.send_tokens(account_with_all_tokens, contract_address, 100, gas=1)

        _, contract_deploy_tx = w3_client.deploy_and_get_contract(
            "common/Counter", "0.8.10", account=account_with_all_tokens
        )

        sol_balance_after_deploy = operator.get_solana_balance()
        token_balance_after_deploy = operator.get_token_balance(w3_client)

        assert sol_balance_before > sol_balance_after_deploy
        assert token_balance_after_deploy > token_balance_before
        token_diff = w3_client.to_main_currency(token_balance_after_deploy - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after_deploy,
            sol_price,
            token_diff,
            token_price,
            w3_client.native_token_name,
        )
        get_gas_used_percent(w3_client, contract_deploy_tx)

    @pytest.mark.slow
    @pytest.mark.timeout(16 * Time.MINUTE)
    def test_deploy_contract_alt_on(
        self, sol_client, neon_price, sol_price, operator, web3_client, accounts, alt_contract
    ):
        """Trigger transaction than requires more than 30 accounts"""
        sender_account = accounts[0]
        accounts_quantity = 45
        sol_balance_before = operator.get_solana_balance()
        neon_balance_before = operator.get_token_balance(web3_client)
        tx = web3_client.make_raw_tx(sender_account)

        instr = alt_contract.functions.fill(accounts_quantity).build_transaction(tx)
        receipt = web3_client.send_transaction(sender_account, instr)

        sol_trx_with_alt = get_sol_trx_with_alt(web3_client, sol_client, receipt)
        assert sol_trx_with_alt is not None, "There are no lookup table for alt transaction"

        alt_address = sol_trx_with_alt.value.transaction.transaction.message.address_table_lookups[0].account_key
        wait_condition(
            lambda: not sol_client.account_exists(alt_address),
            timeout_sec=10 * Time.MINUTE,
            delay=3,
        )

        sol_balance_after = operator.get_solana_balance()
        neon_balance_after = operator.get_token_balance(web3_client)

        assert sol_balance_before > sol_balance_after
        assert neon_balance_after > neon_balance_before
        neon_diff = web3_client.to_main_currency(neon_balance_after - neon_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after,
            sol_price,
            neon_diff,
            neon_price,
            web3_client.native_token_name,
        )

        get_gas_used_percent(web3_client, receipt)

    def test_deploy_contract_alt_off(
        self, sol_client, accounts, web3_client, sol_price, neon_price, operator, alt_contract
    ):
        """Trigger transaction than requires less than 30 accounts"""
        accounts_quantity = 10
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(web3_client)

        tx = web3_client.make_raw_tx(accounts[0].address)

        instr = alt_contract.functions.fill(accounts_quantity).build_transaction(tx)
        receipt = web3_client.send_transaction(accounts[0], instr)
        block = int(receipt["blockNumber"])

        response = wait_for_block(sol_client, block)
        check_alt_off(response)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(web3_client)

        assert sol_balance_before > sol_balance_after
        assert token_balance_after > token_balance_before
        token_diff = web3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after,
            sol_price,
            token_diff,
            neon_price,
            web3_client.native_token_name,
        )
        get_gas_used_percent(web3_client, receipt)

    def test_deploy_big_contract_with_structures(self, client_and_price, account_with_all_tokens, sol_price, operator):
        w3_client, token_price = client_and_price

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        contract, receipt = w3_client.deploy_and_get_contract("EIPs/ERC3475", "0.8.10", account_with_all_tokens)

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
        get_gas_used_percent(w3_client, receipt)

    @pytest.mark.timeout(30 * Time.MINUTE)
    @pytest.mark.slow
    @pytest.mark.parametrize("value", [20, 30])
    def test_call_contract_with_mapping_updating(
        self,
        client_and_price,
        account_with_all_tokens,
        sol_price,
        web3_client,
        web3_client_sol,
        sol_client,
        value,
        operator,
        mapping_actions_contract
    ):
        w3_client, token_price = client_and_price

        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(w3_client)

        tx = w3_client.make_raw_tx(account_with_all_tokens.address)

        instruction_tx = mapping_actions_contract.functions.replaceValues(value).build_transaction(tx)
        receipt = w3_client.send_transaction(account_with_all_tokens, instruction_tx)
        assert receipt["status"] == 1
        wait_condition(lambda: sol_balance_before != operator.get_solana_balance())

        sol_trx_with_alt = get_sol_trx_with_alt(web3_client, sol_client, receipt)
        if sol_trx_with_alt is not None:
            alt_address = sol_trx_with_alt.value.transaction.transaction.message.address_table_lookups[0].account_key
            wait_condition(
                lambda: not sol_client.account_exists(alt_address),
                timeout_sec=11 * Time.MINUTE,
                delay=3,
            )

        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(w3_client)
        token_diff = w3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(
            sol_balance_before - sol_balance_after, sol_price, token_diff, token_price, w3_client.native_token_name
        )
