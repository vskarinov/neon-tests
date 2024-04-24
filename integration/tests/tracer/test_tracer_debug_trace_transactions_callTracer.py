import random

import allure
import pytest

from utils.helpers import wait_condition
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

    def assert_trace_transaction_response(self, response, expected_response, log=False, calls=False):
        assert response["from"] == expected_response["from"]
        assert response["to"] == expected_response["to"]
        assert response["type"] == expected_response["type"]
        assert response["gasUsed"] == expected_response["gasUsed"]

        if "input" in expected_response:
            assert response["input"] == expected_response["input"]

        if log:
            for key in expected_response["logs"][0]:
                assert response["logs"][0][key] == expected_response["logs"][0][key]

        if calls:
            for index, call in enumerate(expected_response["calls"]):
                for key in call:
                    assert response["calls"][index][key] == expected_response["calls"][index][key]
 
    def test_callTracer_type_create(self, storage_contract_with_deploy_tx):
        receipt = storage_contract_with_deploy_tx[1]
        expected_response = {}

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "onlyTopCall": True }}
        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

        expected_response["from"] = receipt["from"].lower()
        expected_response["to"] = receipt["contractAddress"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["type"] = "CREATE"

        self.assert_trace_transaction_response(response["result"], expected_response)
    
    @pytest.mark.skip(reason="NDEV-2934")
    def test_callTracer_without_tracerConfig(self, storage_contract_with_deploy_tx):
        receipt = storage_contract_with_deploy_tx[1]
        expected_response = {}
        tracer_params = { "tracer": "callTracer" }

        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

        expected_response["from"] = receipt["from"].lower()
        expected_response["to"] = receipt["contractAddress"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["type"] = "CREATE"

        self.assert_trace_transaction_response(response["result"], expected_response)

    def test_callTracer_type_call(self, storage_contract):
        sender_account = self.accounts[0]
        store_value = random.randint(1, 100)
        tracer_params = { "tracer": "callTracer", "tracerConfig": { "onlyTopCall": True } }
        expected_response = {}

        tx_obj, _, receipt = call_storage(sender_account, storage_contract, store_value, "blockNumber", self.web3_client)
        
        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

        expected_response["from"] = tx_obj["from"].lower()
        expected_response["to"] = tx_obj["to"].lower()
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["input"] = tx_obj["data"]
        expected_response["type"] = "CALL"

        self.assert_trace_transaction_response(response["result"], expected_response)
    
    def test_callTracer_withLog_option_check(self, event_caller_contract):
        sender_account = self.accounts[0]
        expected_response = {}

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = event_caller_contract.functions.callEvent1("Event call").build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }

        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

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

        self.assert_trace_transaction_response(response["result"], expected_response, log=True)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": False } }
        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )
        assert "logs" not in response["result"]

    def fill_expected_response(self, instruction_tx, receipt):
        expected_response = {}
        address_to = instruction_tx["to"].lower()
        expected_response["from"] = instruction_tx["from"].lower()
        expected_response["to"] = address_to
        expected_response["gasUsed"] =  hex(receipt["gasUsed"])
        expected_response["input"] = instruction_tx["data"]
        expected_response["type"] = "CALL"
        expected_response["logs"] = [{
            "address": address_to,
            "topics": [receipt["logs"][0]["topics"][0].hex()],
            "data": receipt["logs"][0]["data"].hex(),
        }]
        expected_response["calls"] = [{
            "from": address_to,
            "gasUsed":"0x0",
            "gas": "0x0",
            "type": "CALL",
            "error": "execution reverted",
            "revertReason":f"Insufficient balance for transfer, account = {address_to}, chain = 111, required = 1",
            "value": "0x1",
        }]
        return expected_response
    
    def test_callTracer_call_contract_from_other_contract_revert_with_assert(self, contract_caller_for_another_contract):
        sender_account = self.accounts[0]
        contractTwo = contract_caller_for_another_contract[0]
        address_of_contractOne = contract_caller_for_another_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractTwo.functions.depositOnContractOneRevertWithAssertFalse(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }

        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )
        
        expected_response = self.fill_expected_response(instruction_tx, receipt)
        self.assert_trace_transaction_response(response["result"], expected_response, log=True, calls=True)

    def test_callTracer_call_contract_from_other_contract_revert(self, contract_caller_for_another_contract):
        sender_account = self.accounts[0]
        contractTwo = contract_caller_for_another_contract[0]
        address_of_contractOne = contract_caller_for_another_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractTwo.functions.depositOnContractOneRevert(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }

        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

        expected_response = self.fill_expected_response(instruction_tx, receipt)
        self.assert_trace_transaction_response(response["result"], expected_response, log=True, calls=True)
    
    def test_callTracer_call_contract_from_other_contract_revert_with_require(self, contract_caller_for_another_contract):
        sender_account = self.accounts[0]
        contractTwo = contract_caller_for_another_contract[0]
        address_of_contractOne = contract_caller_for_another_contract[1]

        tx = self.web3_client.make_raw_tx(from_=sender_account)
        instruction_tx = contractTwo.functions.depositOnContractOneRevertWithRequire(address_of_contractOne).build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)

        tracer_params = { "tracer": "callTracer", "tracerConfig": { "withLog": True } }

        wait_condition(
            lambda: self.tracer_api.send_rpc(
                method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
            )["result"]
            is not None,
            timeout_sec=120,
        )

        response = self.tracer_api.send_rpc(
            method="debug_traceTransaction", params=[receipt["transactionHash"].hex(), tracer_params]
        )

        expected_response = self.fill_expected_response(instruction_tx, receipt)
        self.assert_trace_transaction_response(response["result"], expected_response, log=True, calls=True)