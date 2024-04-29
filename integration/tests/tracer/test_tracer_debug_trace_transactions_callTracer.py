import random

import allure
import pytest
import json

from deepdiff import DeepDiff
from utils.helpers import wait_condition
from integration.tests.basic.helpers.basic import AccountData
from utils.web3client import NeonChainWeb3Client
from utils.accounts import EthAccounts
from utils.apiclient import JsonRPCSession
from integration.tests.tracer.test_tracer_historical_methods import call_storage

@allure.feature("Tracer API")
@allure.story("Tracer API RPC calls debug method trace_transaction callTracer check")
@pytest.mark.usefixtures("accounts", "web3_client", "tracer_api")
class TestDebugTraceTransactionCallTracer:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts
    tracer_api: JsonRPCSession


    def fill_expected_response(self, instruction_tx, receipt, 
                               logs=False, 
                               revert=False, 
                               revert_reason=None, 
                               calls_value="0x1", 
                               calls_type="CALL", 
                               calls_logs_append=False
                               ):
        expected_response = {}
        expected_response["calls"] = []

        address_to = instruction_tx["to"].lower()
        expected_response["from"] = instruction_tx["from"].lower()
        expected_response["to"] = address_to
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["input"] = instruction_tx["data"]
        expected_response["type"] = "CALL"

        if logs:
            for log in receipt["logs"]:
                if log["logIndex"] == 0:
                    expected_response["logs"] = [{
                        "address": address_to,
                        "topics": [log["topics"][0].hex()],
                        "data": log["data"].hex(),
                    }]

        if calls_logs_append:
            for log in receipt["logs"]:
                if log["logIndex"] == 1:
                    expected_response["calls"].append({
                    "from": address_to,
                    "gasUsed":"0x0",
                    "gas": "0x0",
                    "type": "CALL",
                    "value": calls_value,
                    "logs": [{
                        "address": address_to,
                        "topics": [log["topics"][0].hex()],
                        "data": log["data"].hex(),
                        }]
                    })

        expected_response["calls"].append({
            "from": address_to,
            "gasUsed":"0x0",
            "gas": "0x0",
            "type": calls_type,
            "value": calls_value,
        })

        if revert:
            expected_response["calls"][0]["error"] = "execution reverted"
            expected_response["calls"][0]["revertReason"] = revert_reason

        return expected_response
    
    def assert_response_contains_expected(self, expected_response, response):
        diff = DeepDiff(expected_response, response["result"])
        assert ("dictionary_item_added" and "dictionary_item_removed") not in diff

    def wait_for_trace_transaction_response_from_tracer(self, receipt, tracer_params):
        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        return self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

    def test_callTracer_type_create2(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.callTypeCreate2().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, receipt, calls_value="0x0", calls_type="CREATE2")
        result_diff = DeepDiff(expected_response, response["result"])
        assert ("dictionary_item_added" and "dictionary_item_removed") not in result_diff

    @pytest.mark.skip(reason="NDEV-2934")
    def test_callTracer_without_tracerConfig(self, storage_contract_with_deploy_tx):
        receipt = storage_contract_with_deploy_tx[1]
        expected_response = {}
        tracer_params = { "tracer": "callTracer" }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response["from"] = receipt["from"].lower()
        expected_response["to"] = receipt["contractAddress"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["type"] = "CREATE"

        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_type_call(self, storage_contract):
        sender_account = self.accounts[0]
        store_value = random.randint(1, 100)
        tracer_params = { "tracer": "callTracer", "tracerConfig": { "onlyTopCall": True } }
        expected_response = {}

        tx_obj, _, receipt = call_storage(sender_account, storage_contract, store_value, "blockNumber", self.web3_client)
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response["from"] = tx_obj["from"].lower()
        expected_response["to"] = tx_obj["to"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["input"] = tx_obj["data"]
        expected_response["type"] = "CALL"

        self.assert_response_contains_expected(expected_response, response)
    
    def test_callTracer_withLog_check(self, event_caller_contract):
        sender_account = self.accounts[0]
        expected_response = {}

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = event_caller_contract.functions.callEvent1("Event call").build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response["from"] = instruction_tx["from"].lower()
        expected_response["to"] = instruction_tx["to"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["input"] = instruction_tx["data"]
        expected_response["type"] = "CALL"
        expected_response["logs"] = [{
            "address": instruction_tx["to"].lower(),
            "topics": [receipt["logs"][0]["topics"][0].hex(), receipt["logs"][0]["topics"][1].hex()],
            "data": receipt["logs"][0]["data"].hex(),
        }]

        self.assert_response_contains_expected(expected_response, response)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": False } }
        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )
        assert "logs" not in response["result"]

    def test_callTracer_call_contract_from_contract_type_static_call(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.getBalanceOfContractCallee(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "OnlyTopCall": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, receipt, calls_value="0x0", calls_type="STATICCALL")
        self.assert_response_contains_expected(expected_response, response)
   
    def test_callTracer_call_contract_from_contract_type_static_call_with_events(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.emitEventAndGetBalanceOfContractCalleeWithEvents(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, 
                                                        receipt, 
                                                        logs=True, 
                                                        calls_value="0x0", 
                                                        calls_type="STATICCALL", 
                                                        calls_logs_append=True)
        
        self.assert_response_contains_expected(expected_response, response)
    
    def test_callTracer_call_contract_from_contract_type_call_with_events(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.lowLevelCallContractWithEvents(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, receipt, calls_value="0x0", calls_type="STATICCALL")
        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_call_contract_from_contract_type_call(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.lowLevelCallContract(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, receipt, calls_value="0x0")
        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_call_contract_from_contract_type_delegate_call(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.setParamWithDelegateCall(address_of_contractOne, 9).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, receipt, calls_value="0x0", calls_type="DELEGATECALL")
        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_call_contract_from_contract_type_callcode(self, opcodes_checker):
        sender_account = self.accounts[0]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = opcodes_checker.functions.test_callcode().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        
        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        expected_response = self.fill_expected_response(instruction_tx, receipt, calls_value="0x0", calls_type="CALLCODE")
        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_call_contract_with_zero_division(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.callNotSafeDivision(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        reason = f"division or modulo by zero"
        expected_response = self.fill_expected_response(instruction_tx, receipt, revert=True, revert_reason=reason, calls_value="0x0")
        self.assert_response_contains_expected(expected_response, response)
    
    def test_callTracer_call_contract_from_other_contract_revert_with_assert(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.callContactRevertWithAssertFalse(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        address_to = instruction_tx["to"].lower()
        reason = f"Insufficient balance for transfer, account = {address_to}, chain = 111, required = 1"
        expected_response = self.fill_expected_response(instruction_tx, receipt, logs=True, revert=True, revert_reason=reason)
        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_call_contract_from_other_contract_revert(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.callContactRevert(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        address_to = instruction_tx["to"].lower()
        reason = f"Insufficient balance for transfer, account = {address_to}, chain = 111, required = 1"
        expected_response = self.fill_expected_response(instruction_tx, receipt, logs=True, revert=True, revert_reason=reason)
        self.assert_response_contains_expected(expected_response, response)
    
    def test_callTracer_call_contract_from_other_contract_revert_with_require(self, caller_contract):
        sender_account = self.accounts[0]
        contractCaller = caller_contract[0]
        address_of_contractOne = caller_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractCaller.functions.callContractRevertWithRequire(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)

        address_to = instruction_tx["to"].lower()
        reason = f"Insufficient balance for transfer, account = {address_to}, chain = 111, required = 1"
        expected_response = self.fill_expected_response(instruction_tx, receipt, logs=True, revert=True, revert_reason=reason)
        self.assert_response_contains_expected(expected_response, response)

    def test_callTracer_call_to_precompiled_contract(self, eip1052_checker):
        expected_response = {}
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        precompiled_acc = AccountData(address="0xFf00000000000000000000000000000000000004")
        instruction_tx = eip1052_checker.functions.getContractHashWithLog(precompiled_acc.address).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1
        
        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": False } }
        response = self.wait_for_trace_transaction_response_from_tracer(receipt, tracer_params)
        
        expected_response["from"] = instruction_tx["from"].lower()
        expected_response["to"] = instruction_tx["to"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["input"] = instruction_tx["data"]
        expected_response["type"] = "CALL"

        self.assert_response_contains_expected(expected_response, response)
