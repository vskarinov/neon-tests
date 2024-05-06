import allure
import pytest
import web3

from utils.accounts import EthAccounts
from utils.consts import ZERO_HASH
from utils.web3client import NeonChainWeb3Client


@allure.feature("Opcodes verifications")
@allure.story("Go-ethereum opCodes tests")
@pytest.mark.usefixtures("accounts", "web3_client")
class TestOpCodes:
    web3_client: NeonChainWeb3Client
    accounts: EthAccounts

    @pytest.fixture(scope="class")
    def opcodes_checker(self, web3_client, faucet, accounts):
        contract, _ = web3_client.deploy_and_get_contract(
            "opcodes/BaseOpCodes", "0.5.16", accounts[0], contract_name="BaseOpCodes"
        )
        return contract

    def test_base_opcodes(self, opcodes_checker):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        instruction_tx = opcodes_checker.functions.test().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1

    def test_stop(self, opcodes_checker):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        instruction_tx = opcodes_checker.functions.test_stop().build_transaction(tx)
        receipt = self.web3_client.send_transaction(sender_account, instruction_tx)
        assert receipt["status"] == 1

    def test_invalid_opcode(self, opcodes_checker):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        with pytest.raises(web3.exceptions.ContractLogicError, match="EVM encountered invalid opcode"):
            opcodes_checker.functions.test_invalid().build_transaction(tx)

    def test_revert(self, opcodes_checker):
        sender_account = self.accounts[0]
        tx = self.web3_client.make_raw_tx(sender_account)
        with pytest.raises(web3.exceptions.ContractLogicError, match="execution reverted"):
            opcodes_checker.functions.test_revert().build_transaction(tx)

    @pytest.fixture(scope="class")
    def mcopy_checker(self, web3_client, faucet, accounts):
        contract, _ = web3_client.deploy_and_get_contract(
            "opcodes/EIP5656MCopy",
            "0.8.25",
            accounts[0],
            contract_name="MemoryCopy",
        )
        return contract

    @pytest.mark.parametrize("dst, src, length, expected_result", [(1, 0, 8, '000010203405060708090a0b0c0d0e0f'),
                                                                   (0, 1, 8, '001020300405060708090a0b0c0d0e0f'),
                                                                   (0, 0, 12, '000102030405060708090a0b0c0d0e0f')])
    def test_mcopy(self, mcopy_checker, dst, src, length, expected_result):
        sender_account = self.accounts[0]
        initial_data = self.web3_client.text_to_bytes32('000102030405060708090a0b0c0d0e0f')

        tx = self.web3_client.make_raw_tx(sender_account)
        result = mcopy_checker.functions.copy(initial_data, dst, src, length).call(tx)
        assert result == self.web3_client.text_to_bytes32(expected_result)

    def test_tstore(self, accounts):
        sender_account = self.accounts[0]

        contract, _ = self.web3_client.deploy_and_get_contract(
            "opcodes/EIP1153TStoreTLoad",
            "0.8.25",
            sender_account,
            contract_name="TransientStorage",
        )

        contract_caller, _ = self.web3_client.deploy_and_get_contract(
            "opcodes/EIP1153TStoreTLoad",
            "0.8.25",
            sender_account,
            contract_name="TransientStorageCaller",
        )

        initial_data = self.web3_client.text_to_bytes32('000102030405060708090a0b0c0d0e0f')

        # save and read in one transaction
        result = contract_caller.functions.saveAndRead(initial_data).call()
        assert result == initial_data

        # save and read in different transactions
        tx = self.web3_client.make_raw_tx(sender_account)
        instr = contract.functions.save(initial_data).build_transaction(tx)
        self.web3_client.send_transaction(sender_account, instr)
        result = contract.functions.read().call()
        assert result.hex() == ZERO_HASH
