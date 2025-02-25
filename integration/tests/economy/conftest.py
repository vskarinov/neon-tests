import pytest

from pythclient.solana import SolanaClient
from _pytest.config import Config

from integration.tests.basic.helpers.chains import make_nonce_the_biggest_for_chain
from utils.erc20wrapper import ERC20Wrapper
from utils.erc721ForMetaplex import ERC721ForMetaplex
from utils.web3client import NeonChainWeb3Client


@pytest.fixture(scope="session")
def sol_client_tx_v2(pytestconfig: Config):
    """Client for work with transactions version 2"""
    client = SolanaClient(
        pytestconfig.environment.solana_url,
        pytestconfig.environment.account_seed_version,
    )
    return client


@pytest.fixture(scope="class")
def counter_contract(account_with_all_tokens, client_and_price, web3_client_sol, web3_client):
    w3_client, _ = client_and_price
    make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
    contract, _ = w3_client.deploy_and_get_contract("common/Counter", "0.8.10", account=account_with_all_tokens)
    return contract


@pytest.fixture(scope="class", params=["neon", "sol"])
def client_and_price(web3_client, web3_client_sol, request, pytestconfig):
    client = {
        "neon": web3_client,
        "sol": web3_client_sol if "sol" in pytestconfig.environment.network_ids else None,
    }.get(request.param)

    if client:
        price = client.get_token_usd_gas_price()
        return client, price

    pytest.skip(f"{request.param} chain is not available")


@pytest.fixture(scope="class")
def erc20_wrapper(
    account_with_all_tokens,
    client_and_price,
    faucet,
    solana_account,
    sol_client,
    web3_client_sol,
    web3_client,
):
    client, _ = client_and_price
    make_nonce_the_biggest_for_chain(account_with_all_tokens, client, [web3_client, web3_client_sol])
    contract = ERC20Wrapper(
        client,
        faucet,
        "Test AAA",
        "AAA",
        sol_client,
        account=account_with_all_tokens,
        solana_account=solana_account,
        mintable=True,
    )
    contract.mint_tokens(account_with_all_tokens, contract.account.address)
    return contract


@pytest.fixture(scope="class")
def erc721_neon_chain(web3_client: NeonChainWeb3Client, faucet, pytestconfig: Config, account_with_all_tokens):
    contract = ERC721ForMetaplex(web3_client, faucet, account_with_all_tokens)
    return contract


@pytest.fixture(scope="class")
def erc721(erc721_neon_chain, client_and_price, faucet, account_with_all_tokens):
    client, _ = client_and_price
    contract = ERC721ForMetaplex(
        client, faucet, account=account_with_all_tokens, contract_address=erc721_neon_chain.contract.address
    )

    return contract


@pytest.fixture(scope="class")
def alt_contract(accounts, web3_client):
    contract, _ = web3_client.deploy_and_get_contract("common/ALT", "0.8.10", account=accounts[0], constructor_args=[8])
    return contract


@pytest.fixture(scope="class")
def mapping_actions_contract(account_with_all_tokens, client_and_price, web3_client_sol, web3_client):
    w3_client = client_and_price[0]
    make_nonce_the_biggest_for_chain(account_with_all_tokens, w3_client, [web3_client, web3_client_sol])
    contract, _ = w3_client.deploy_and_get_contract(
        contract="common/Common", version="0.8.12", contract_name="MappingActions", account=account_with_all_tokens
    )
    return contract
