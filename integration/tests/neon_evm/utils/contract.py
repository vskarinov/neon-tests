import typing as tp
import pathlib

import eth_abi
import solcx
from eth_account.datastructures import SignedTransaction
from eth_utils import abi
from solana.keypair import Keypair

from .transaction_checks import check_transaction_logs_have_text
from ..types.types import Caller, Contract, TreasuryPool
from ..solana_utils import EvmLoader
from .storage import create_holder
from .ethereum import create_contract_address, make_eth_transaction

from web3.auto import w3


def get_contract_bin(
    contract: str,
    contract_name: tp.Optional[str] = None,
):
    version = "0.7.6"
    if not contract.endswith(".sol"):
        contract += ".sol"
    if contract_name is None:
        if "/" in contract:
            contract_name = contract.rsplit("/", 1)[1].rsplit(".", 1)[0]
        else:
            contract_name = contract.rsplit(".", 1)[0]

    solcx.install_solc(version)

    contract_path = (pathlib.Path.cwd() / "contracts" / "neon_evm" / contract).absolute()
    if not contract_path.exists():
        contract_path = (pathlib.Path.cwd() / "contracts" / f"{contract}").absolute()

    assert contract_path.exists(), f"Can't found contract: {contract_path}"

    compiled = solcx.compile_files(
        [contract_path],
        output_values=["abi", "bin"],
        solc_version=version,
        allow_paths=["."],
        optimize=True,
    )
    contract_abi = None
    for key in compiled.keys():
        if contract_name == key.rsplit(":")[-1]:
            contract_abi = compiled[key]
            break

    return contract_abi["bin"]


def make_deployment_transaction(
    evm_loader: EvmLoader,
    user: Caller,
    contract_file_name: tp.Union[pathlib.Path, str],
    contract_name: tp.Optional[str] = None,
    encoded_args=None,
    gas: int = 999999999,
    chain_id=111,
    access_list=None,
) -> SignedTransaction:
    data = get_contract_bin(contract_file_name, contract_name)
    if encoded_args is not None:
        data = data + encoded_args.hex()

    nonce = evm_loader.get_neon_nonce(user.eth_address)
    tx = {"to": None, "value": 0, "gas": gas, "gasPrice": 0, "nonce": nonce, "data": data}
    if chain_id:
        tx["chainId"] = chain_id
    if access_list:
        tx["accessList"] = access_list
        tx["type"] = 1

    return w3.eth.account.sign_transaction(tx, user.solana_account.secret_key[:32])


def make_contract_call_trx(
    evm_loader, user, contract, function_signature, params=None, value=0, chain_id=111, access_list=None, trx_type=None
):
    # does not work for tuple in params
    data = abi.function_signature_to_4byte_selector(function_signature)

    if params is not None:
        types = function_signature.split("(")[1].split(")")[0].split(",")
        data += eth_abi.encode(types, params)

    signed_tx = make_eth_transaction(
        evm_loader,
        contract.eth_address,
        data,
        user,
        value=value,
        chain_id=chain_id,
        access_list=access_list,
        type=trx_type,
    )

    return signed_tx


def deploy_contract(
    operator: Keypair,
    user: Caller,
    contract_file_name: tp.Union[pathlib.Path, str],
    evm_loader: EvmLoader,
    treasury_pool: TreasuryPool,
    encoded_args=None,
    contract_name: tp.Optional[str] = None,
):
    contract: Contract = create_contract_address(user, evm_loader)
    holder_acc = create_holder(operator, evm_loader)
    signed_tx = make_deployment_transaction(evm_loader, user, contract_file_name, contract_name, encoded_args=encoded_args)
    evm_loader.write_transaction_to_holder_account(signed_tx, holder_acc, operator)

    resp = evm_loader.execute_transaction_steps_from_account(
        operator,
        treasury_pool,
        holder_acc,
        [contract.solana_address, contract.balance_account_address, user.balance_account_address],
    )
    check_transaction_logs_have_text(resp, "exit_status=0x12")
    return contract
