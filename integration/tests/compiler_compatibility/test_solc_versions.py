import pytest
import solcx
from integration.tests.compiler_compatibility.helpers.erc_20_common_checks import (
    check_erc20_mint_function,
    check_erc20_transfer_function,
)
from utils.helpers import generate_text

INIT_NAME = "SampleToken"
INIT_SYMBOL = "ST"
INIT_DECIMALS = 18
INIT_SUPPLY = 1000


def load_data():
    versions = [str(item) for item in solcx.get_installable_solc_versions()]
    major_versions = sorted(set(version.split('.')[1] for version in versions), reverse=True)
    last_three_majors = major_versions[:3]
    last_three_versions = []
    for major in last_three_majors:
        filtered_versions = [version for version in versions if version.startswith(f'0.{major}.')]
        highest_version = max(filtered_versions, key=lambda v: [int(part) for part in v.split('.')])
        last_three_versions.append(highest_version)

    result = {"params": last_three_versions, "ids": last_three_versions}
    return result


class TestSolcCompatibility:

    @pytest.fixture(scope="class", **load_data())
    def solc_version(self, request):
        return request.param

    @pytest.mark.parametrize()
    @pytest.fixture(scope="class")
    def erc20_solc(self, web3_client, accounts, solc_version):
        contract, _ = web3_client.deploy_and_get_contract(
            "EIPs/ERC20/ERC20.sol",
            solc_version,
            accounts[0],
            contract_name="ERC20",
            constructor_args=[INIT_NAME, INIT_SYMBOL, INIT_SUPPLY],
        )
        return contract

    @pytest.fixture(scope="class")
    def recursion_factory(self, accounts, web3_client, solc_version):
        contract, _ = web3_client.deploy_and_get_contract(
            "common/Recursion",
            solc_version,
            accounts[0],
            contract_name="DeployRecursionFactory",
            constructor_args=[3],
        )
        return contract

    def test_name(self, erc20_solc):
        assert erc20_solc.functions.name().call() == INIT_NAME

    def test_mint(self, erc20_solc, accounts, web3_client):
        check_erc20_mint_function(web3_client, erc20_solc, accounts[0])

    def test_transfer(self, erc20_solc, accounts, web3_client):
        check_erc20_transfer_function(web3_client, erc20_solc, accounts[0], accounts[1])

    def test_deploy_contract_by_contract(self, recursion_factory, accounts, web3_client):
        tx = web3_client.make_raw_tx(accounts[0].address, estimate_gas=False)
        salt = generate_text(min_len=5, max_len=7)
        instruction_tx = recursion_factory.functions.deploySecondContractViaCreate2(salt).build_transaction(tx)
        receipt = web3_client.send_transaction(accounts[0], instruction_tx)
        assert receipt["status"] == 1

        event_logs = recursion_factory.events.SecondContractDeployed().process_receipt(receipt)
        addresses = [event_log["args"]["addr"] for event_log in event_logs]
        assert len(addresses) == 2
