import logging

import allure

from utils import web3client

LOGGER = logging.getLogger(__name__)


class ERC721ForMetaplex:
    def __init__(
        self,
        web3_client: web3client.NeonChainWeb3Client,
        faucet,
        account=None,
        contract="neon-evm/erc721_for_metaplex.sol",
        contract_name="ERC721ForMetaplex",
        contract_address=None,
    ):
        self.web3_client = web3_client
        self.account = account or web3_client.create_account()
        faucet.request_neon(self.account.address, 600)
        if contract_address:
            self.contract = web3_client.get_deployed_contract(
                contract_address, contract_file=contract, contract_name=contract_name
            )
        else:
            self.contract = self.deploy(contract, contract_name)

    @allure.step("Make tx object")
    def make_tx_object(self, from_address, gasPrice=None, gas=None):
        tx = {
            "from": from_address,
            "nonce": self.web3_client.eth.get_transaction_count(from_address),
            "gasPrice": gasPrice if gasPrice is not None else self.web3_client.gas_price(),
        }
        if gas is not None:
            tx["gas"] = gas
        return tx

    @allure.step("Deploy contract")
    def deploy(self, contract, contract_name):
        contract, _ = self.web3_client.deploy_and_get_contract(
            contract, "0.8.0", self.account, contract_name=contract_name
        )
        return contract

    @allure.step("Mint")
    def mint(self, seed, to_address, uri, gas_price=None, gas=None, signer=None):
        signer = self.account if signer is None else signer
        tx = self.make_tx_object(signer.address, gas_price, gas)
        instruction_tx = self.contract.functions.mint(seed, to_address, uri).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        logs = self.contract.events.Transfer().process_receipt(resp)
        LOGGER.info(f"Event logs: {logs}")
        return logs[0]["args"]["tokenId"]

    @allure.step("Safe mint")
    def safe_mint(self, seed, to_address, uri, data=None, gas_price=None, gas=None, signer=None):
        signer = self.account if signer is None else signer
        tx = self.make_tx_object(signer.address, gas_price, gas)
        if data is None:
            instruction_tx = self.contract.functions.safeMint(seed, to_address, uri).build_transaction(tx)
        else:
            instruction_tx = self.contract.functions.safeMint(seed, to_address, uri, data).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        logs = self.contract.events.Transfer().process_receipt(resp)
        LOGGER.info(f"Event logs: {logs}")
        return logs[0]["args"]["tokenId"]

    @allure.step("Transfer from")
    def transfer_from(self, address_from, address_to, token_id, signer, gas_price=None, gas=None):
        tx = self.make_tx_object(signer.address, gas_price, gas)
        instruction_tx = self.contract.functions.transferFrom(address_from, address_to, token_id).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        return resp

    @allure.step("Safe transfer from")
    def safe_transfer_from(self, address_from, address_to, token_id, signer, data=None, gas_price=None, gas=None):
        tx = self.make_tx_object(signer.address, gas_price, gas)
        if data is None:
            instruction_tx = self.contract.functions.safeTransferFrom(
                address_from, address_to, token_id
            ).build_transaction(tx)
        else:
            instruction_tx = self.contract.functions.safeTransferFrom(
                address_from, address_to, token_id, data
            ).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        return resp

    @allure.step("Approve")
    def approve(self, address_to, token_id, signer, gas_price=None, gas=None):
        tx = self.make_tx_object(signer.address, gas_price, gas)
        instruction_tx = self.contract.functions.approve(address_to, token_id).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        return resp

    @allure.step("Set approval for all")
    def set_approval_for_all(self, operator, approved, signer, gas_price=None, gas=None):
        tx = self.make_tx_object(signer.address, gas_price, gas)
        instruction_tx = self.contract.functions.setApprovalForAll(operator, approved).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        return resp

    @allure.step("Transfer solana from")
    def transfer_solana_from(self, from_address, to_address, token_id, signer, gas_price=None, gas=None):
        tx = self.make_tx_object(signer.address, gas_price, gas)
        instruction_tx = self.contract.functions.transferSolanaFrom(
            from_address, to_address, token_id
        ).build_transaction(tx)
        resp = self.web3_client.send_transaction(signer, instruction_tx)
        return resp
