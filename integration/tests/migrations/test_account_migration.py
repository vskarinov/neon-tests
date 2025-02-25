"""Tests to check old accounts continue work after structure changes
Environment variables ACCOUNTS, ERC20_ADDRESS, ERC721_ADDRESS should be set"""
import os
import time

import eth_abi
import pytest
from eth_utils import abi

from web3.logs import DISCARD

from integration.tests.economy.steps import assert_profit
from utils.erc20wrapper import ERC20Wrapper
from utils.erc721ForMetaplex import ERC721ForMetaplex
from utils.helpers import gen_hash_of_block


@pytest.fixture(scope="class")
def accounts(web3_client):
    print("VERSIONS", web3_client.get_neon_versions())

    account_keys = os.environ.get("ACCOUNTS").split(",")
    accounts = []
    for key in account_keys:
        accounts.append(web3_client.eth.account.from_key(key))
    print("Before testing:")
    for acc in accounts:
        print(
            f"Balance for {acc.address}: "
            f"{web3_client.to_atomic_currency(web3_client.get_balance(acc.address))}, "
            f"nonce: {web3_client.eth.get_transaction_count(acc.address)}"
        )

    yield accounts
    print("After testing:")
    time.sleep(3)
    for acc in accounts:
        print(
            f"Balance for {acc.address}: "
            f"{web3_client.to_atomic_currency(web3_client.get_balance(acc.address))}, "
            f"nonce: {web3_client.eth.get_transaction_count(acc.address)}"
        )


@pytest.fixture(scope="class")
def bob(accounts):
    return accounts[0]


@pytest.fixture(scope="class")
def alice(accounts):
    return accounts[1]


@pytest.fixture(scope="class")
def trx_list():
    list = []
    yield list
    print("Trx list:")
    for trx in list:
        print(trx.hex())

@pytest.fixture(scope="class")
def counter(web3_client, accounts):
    contract_address = os.environ.get("COUNTER_ADDRESS")
    if contract_address:
        contract = web3_client.get_deployed_contract(
            contract_address, contract_file="common/Counter"
        )
        print(f"Using Counter deployed earlier at {contract_address}")
    else:
        contract, _ = web3_client.deploy_and_get_contract("common/Counter", "0.8.10", account=accounts[0])
        print(f"Counter deployed at address: {contract.address}")
    return contract

@pytest.fixture(scope="class")
def counter_with_map(web3_client, accounts):
    contract_address = os.environ.get("COUNTER_MAP_ADDRESS")
    if contract_address:
        contract = web3_client.get_deployed_contract(
            contract_address, contract_file="common/Counter", contract_name="CounterWithMap"
        )
        print(f"Using CounterWithMap deployed earlier at {contract_address}")
    else:
        contract, _ = web3_client.deploy_and_get_contract("common/Counter", "0.8.10", contract_name="CounterWithMap", account=accounts[0])
        print(f"CounterWithMap deployed at address: {contract.address}")
    return contract



@pytest.fixture(scope="class")
def erc20(web3_client, faucet, sol_client, solana_account, bob):
    contract_address = os.environ.get("ERC20_ADDRESS")

    if contract_address:
        erc20 = ERC20Wrapper(
            web3_client,
            faucet,
            "Test AAA",
            "AAA",
            sol_client,
            account=bob,
            solana_account=solana_account,
            mintable=True,
            contract_address=contract_address,
        )
        print(f"Using ERC20 deployed earlier at {contract_address}")

    else:
        erc20 = ERC20Wrapper(
            web3_client,
            faucet,
            "Test AAA",
            "AAA",
            sol_client,
            account=bob,
            solana_account=solana_account,
            mintable=True,
        )
        print(f"ERC20 deployed at address: {erc20.contract.address}")
        erc20.mint_tokens(erc20.account, erc20.account.address)
    return erc20


@pytest.fixture(scope="class")
def erc721(web3_client, faucet, bob):
    contract_address = os.environ.get("ERC721_ADDRESS")
    if contract_address:
        erc721 = ERC721ForMetaplex(web3_client, faucet, account=bob, contract_address=contract_address)
        print(f"Using ERC721 deployed earlier at {contract_address}")
    else:
        erc721 = ERC721ForMetaplex(web3_client, faucet, account=bob)
        print(f"ERC721 deployed at address: {erc721.contract.address}")

    return erc721

def check_counter(sender, contract, web3_client, sol_client):

    tx = web3_client.make_raw_tx(sender.address)

    solana_accounts = get_solana_accounts_by_emulation(web3_client, sender, contract.address,
                                           "inc()")
    print_solana_accounts_info(sol_client, solana_accounts,"before inc")

    value_before = contract.functions.get().call({"from": sender.address})
    print("Value before:", value_before)

    tx = contract.functions.inc().build_transaction(tx)
    receipt = web3_client.send_transaction(sender, tx)
    print_solana_accounts_info(sol_client, solana_accounts,"after inc")

    print("Transaction receipt:", receipt)
    value_after = contract.functions.get().call({"from": sender.address})
    print("Value after:", value_after)
    assert value_after == value_before + 1

def get_solana_accounts_by_emulation(web3_client, sender, contract, function_signature, params=None):
    data = abi.function_signature_to_4byte_selector(function_signature)

    if params is not None:
        types = function_signature.split("(")[1].split(")")[0].split(",")
        data += eth_abi.encode(types, params)
    tx = web3_client.make_raw_tx(sender.address, contract, data=data, estimate_gas=True)
    signed_tx = web3_client.eth.account.sign_transaction(
        tx, sender.key)
    result = web3_client.get_neon_emulate(
        str(signed_tx.rawTransaction.hex())[2:])
    print(result)
    return [item["pubkey"] for item in result["result"]["solana_accounts"]]

def print_solana_accounts_info(sol_client, accounts, action):
    print("Solana accounts info", action)
    for acc in accounts:
        print(sol_client.get_account_whole_info(acc))
        print(f"Account {acc}: {sol_client.get_account_whole_info(acc)['result']['value']}")


class TestAccountMigration:
    @pytest.fixture(scope="function")
    def check_operator_balance(
        self, web3_client, sol_client, operator_keypair, solana_account, neon_price, sol_price, request, operator
    ):
        print("test case name:", request.node.name)
        sol_balance_before = operator.get_solana_balance()
        token_balance_before = operator.get_token_balance(web3_client)

        yield
        sol_balance_after = operator.get_solana_balance()
        token_balance_after = operator.get_token_balance(web3_client)
        sol_diff = sol_balance_before - sol_balance_after

        assert sol_balance_before > sol_balance_after
        assert token_balance_after > token_balance_before

        token_diff = web3_client.to_main_currency(token_balance_after - token_balance_before)
        assert_profit(sol_diff, sol_price, token_diff, neon_price, web3_client.native_token_name)


    def test_transfers(self, alice, bob, accounts, web3_client, trx_list, check_operator_balance):
        web3_client.send_neon(alice, bob, 5)
        for i in range(5):
            receipt = web3_client.send_neon(alice, accounts[i + 1], 5)
            trx_list.append(receipt["transactionHash"])
            assert receipt["status"] == 1
            receipt = web3_client.send_neon(bob, accounts[i + 2], 1)
            trx_list.append(receipt["transactionHash"])
            assert receipt["status"] == 1

    def test_contract_deploy_economics(self, alice, bob, web3_client, check_operator_balance):
        web3_client.deploy_and_get_contract("common/EventCaller", "0.8.12", bob)

    def test_contract_deploy_and_interact(self, web3_client, accounts, trx_list, check_operator_balance):
        acc1 = accounts[7]
        acc2 = accounts[8]
        contract_a, receipt = web3_client.deploy_and_get_contract(
            "common/NestedCallsChecker", "0.8.12", acc2, contract_name="A"
        )
        trx_list.append(receipt["transactionHash"])
        contract_b, receipt = web3_client.deploy_and_get_contract(
            "common/NestedCallsChecker", "0.8.12", acc2, contract_name="B"
        )
        trx_list.append(receipt["transactionHash"])
        contract_c, receipt = web3_client.deploy_and_get_contract(
            "common/NestedCallsChecker", "0.8.12", acc1, contract_name="C"
        )
        trx_list.append(receipt["transactionHash"])

        tx = {
            "from": acc1.address,
            "nonce": web3_client.eth.get_transaction_count(acc1.address),
            "gasPrice": web3_client.gas_price(),
        }

        instruction_tx = contract_a.functions.method1(contract_b.address, contract_c.address).build_transaction(tx)
        resp = web3_client.send_transaction(acc1, instruction_tx)
        trx_list.append(resp["transactionHash"])

        event_a1_logs = contract_a.events.EventA1().process_receipt(resp, errors=DISCARD)
        assert len(event_a1_logs) == 1
        event_b1_logs = contract_b.events.EventB1().process_receipt(resp, errors=DISCARD)
        assert len(event_b1_logs) == 1
        event_b2_logs = contract_b.events.EventB2().process_receipt(resp, errors=DISCARD)
        event_c1_logs = contract_c.events.EventC1().process_receipt(resp, errors=DISCARD)
        event_c2_logs = contract_c.events.EventC2().process_receipt(resp, errors=DISCARD)
        for log in (event_b2_logs, event_c1_logs, event_c2_logs):
            assert log == (), f"Trx shouldn't contain logs for the events: eventB2, eventC1, eventC2_log0. Log: {log}"

    def test_economics_for_erc721_mint(self, erc721, web3_client, check_operator_balance):
        seed = web3_client.text_to_bytes32(gen_hash_of_block(8))
        erc721.mint(seed, erc721.account.address, "uri")


    def test_erc721_interaction(self, erc721, web3_client, sol_client, bob, alice, accounts, trx_list, check_operator_balance):
        seed = web3_client.text_to_bytes32(gen_hash_of_block(8))

        solana_accounts = get_solana_accounts_by_emulation(web3_client, erc721.account, erc721.contract.address,
                                               "mint(bytes32,address,string)",
                                               [seed, erc721.account.address, "uri"])
        print_solana_accounts_info(sol_client, solana_accounts,"before mint")
        token_id = erc721.mint(seed, erc721.account.address, "uri")
        print_solana_accounts_info(sol_client, solana_accounts,"after mint")

        balance_usr1_before = erc721.contract.functions.balanceOf(erc721.account.address).call()
        balance_usr2_before = erc721.contract.functions.balanceOf(alice.address).call()

        solana_accounts = get_solana_accounts_by_emulation(web3_client, erc721.account, erc721.contract.address,
                                               "approve(address,uint256)",
                                               [alice.address, token_id])
        print_solana_accounts_info(sol_client, solana_accounts,"before approve")
        resp = erc721.approve(alice.address, token_id, erc721.account)
        print_solana_accounts_info(sol_client, solana_accounts,"after approve")

        trx_list.append(resp["transactionHash"])

        solana_accounts = get_solana_accounts_by_emulation(web3_client, alice, erc721.contract.address,
                                               "transferFrom(address,address,uint256)",
                                               [erc721.account.address, alice.address, token_id])
        print_solana_accounts_info(sol_client, solana_accounts,"before transfer_from")

        resp = erc721.transfer_from(erc721.account.address, alice.address, token_id, alice)
        print_solana_accounts_info(sol_client, solana_accounts,"after transfer_from")

        trx_list.append(resp["transactionHash"])

        balance_usr1_after = erc721.contract.functions.balanceOf(erc721.account.address).call()
        balance_usr2_after = erc721.contract.functions.balanceOf(alice.address).call()

        assert balance_usr1_after - balance_usr1_before == -1
        assert balance_usr2_after - balance_usr2_before == 1

        token_ids = []
        for _ in range(5):
            seed = web3_client.text_to_bytes32(gen_hash_of_block(8))
            token_ids.append(erc721.mint(seed, erc721.account.address, "uri"))

        for i in range(5):
            recipient = accounts[i + 3]
            balance_usr1_before = erc721.contract.functions.balanceOf(erc721.account.address).call()
            balance_usr2_before = erc721.contract.functions.balanceOf(recipient.address).call()
            resp = erc721.transfer_from(erc721.account.address, recipient.address, token_ids[i], erc721.account)
            trx_list.append(resp["transactionHash"])
            balance_usr1_after = erc721.contract.functions.balanceOf(erc721.account.address).call()
            balance_usr2_after = erc721.contract.functions.balanceOf(recipient.address).call()
            assert balance_usr1_after - balance_usr1_before == -1
            assert balance_usr2_after - balance_usr2_before == 1

    def test_erc20_interaction(self, erc20, web3_client, bob, alice, accounts, trx_list, check_operator_balance):
        balance_before = erc20.contract.functions.balanceOf(erc20.account.address).call()
        amount = 500
        resp = erc20.mint_tokens(erc20.account, erc20.account.address, amount)
        trx_list.append(resp["transactionHash"])

        balance_after = erc20.contract.functions.balanceOf(erc20.account.address).call()
        assert balance_after == balance_before + amount

        tom = accounts[9]
        balance_before = erc20.contract.functions.balanceOf(tom.address).call()
        resp = erc20.mint_tokens(erc20.account, tom.address, amount)
        trx_list.append(resp["transactionHash"])

        balance_after = erc20.contract.functions.balanceOf(tom.address).call()
        assert balance_after == amount + balance_before

        balance_before = erc20.contract.functions.balanceOf(tom.address).call()
        total_before = erc20.contract.functions.totalSupply().call()
        resp = erc20.burn(tom, tom.address, amount)
        trx_list.append(resp["transactionHash"])

        balance_after = erc20.contract.functions.balanceOf(tom.address).call()
        total_after = erc20.contract.functions.totalSupply().call()

        assert balance_after == balance_before - amount
        assert total_after == total_before - amount

        amount = 1000000000000000
        resp = erc20.mint_tokens(erc20.account, accounts[9].address, amount)
        trx_list.append(resp["transactionHash"])

        amount = 500
        for i in range(8):
            recipient = accounts[i]
            sender = accounts[9]
            balance_acc1_before = erc20.contract.functions.balanceOf(sender.address).call()
            balance_acc2_before = erc20.contract.functions.balanceOf(recipient.address).call()
            total_before = erc20.contract.functions.totalSupply().call()
            resp = erc20.transfer(sender, recipient.address, amount)
            trx_list.append(resp["transactionHash"])

            balance_acc1_after = erc20.contract.functions.balanceOf(sender.address).call()
            balance_acc2_after = erc20.contract.functions.balanceOf(recipient.address).call()
            total_after = erc20.contract.functions.totalSupply().call()
            assert balance_acc1_after == balance_acc1_before - amount
            assert balance_acc2_after == balance_acc2_before + amount
            assert total_before == total_after

        for i in range(7):
            recipient = accounts[8]
            sender = accounts[i]
            balance_acc1_before = erc20.contract.functions.balanceOf(sender.address).call()
            balance_acc2_before = erc20.contract.functions.balanceOf(recipient.address).call()
            total_before = erc20.contract.functions.totalSupply().call()
            resp = erc20.transfer(sender, recipient.address, amount)
            trx_list.append(resp["transactionHash"])
            balance_acc1_after = erc20.contract.functions.balanceOf(sender.address).call()
            balance_acc2_after = erc20.contract.functions.balanceOf(recipient.address).call()
            total_after = erc20.contract.functions.totalSupply().call()
            assert balance_acc1_after == balance_acc1_before - amount
            assert balance_acc2_after == balance_acc2_before + amount
            assert total_before == total_after



    def test_simple_counter(self, web3_client, accounts, counter, sol_client):
        # the data fits into contract account
        sender = accounts[7]
        check_counter(sender, counter, web3_client, sol_client)

    def test_counter_with_map(self, web3_client, accounts, counter_with_map, sol_client):
        sender = accounts[9]
        check_counter(sender, counter_with_map, web3_client, sol_client)


