import os
import re
import subprocess
import sys
import typing as tp
import pathlib
import logging

from paramiko.client import SSHClient
from scp import SCPClient

from deploy.cli.network_manager import NetworkManager

from solana.transaction import Signature
from deploy.cli import faucet as faucet_cli
from utils.web3client import NeonChainWeb3Client
from utils.solana_client import SolanaClient
from python_terraform import Terraform


TFSTATE_BUCKET = os.environ.get("TFSTATE_BUCKET")
TFSTATE_REGION = os.environ.get("TFSTATE_REGION")
TF_STATE_KEY = os.environ.get("TFSTATE_KEY")
TF_BACKEND_CONFIG = {"bucket": TFSTATE_BUCKET, "key": TF_STATE_KEY, "region": TFSTATE_REGION}


os.environ["TF_VAR_run_number"] = os.environ.get("GITHUB_RUN_NUMBER", "0")
os.environ["TF_VAR_branch"] = os.environ.get("GITHUB_REF_NAME", "develop").replace("/", "-").replace("_", "-")
os.environ["TF_VAR_dockerhub_org_name"] = os.environ.get("DOCKERHUB_ORG_NAME", "neonlabsorg")


terraform = Terraform(working_dir=pathlib.Path(__file__).parent.parent / "hetzner")

WEB3_CLIENT = NeonChainWeb3Client(os.environ.get("PROXY_URL"))
REPORT_HEADERS = ["Action", "Fee", "Cost in $", "Accounts", "TRx", "Estimated Gas", "Used Gas", "Used % of EG"]


def set_github_env(envs: tp.Dict, upper=True) -> None:
    """Set environment for github action"""
    path = os.getenv("GITHUB_ENV", str())
    if os.path.exists(path):
        with open(path, "a") as env_file:
            for key, value in envs.items():
                env_file.write(f"\n{key.upper() if upper else key}={str(value)}")


def deploy_infrastructure(
    evm_tag, proxy_tag, faucet_tag, evm_branch, proxy_branch, use_real_price: bool = False
) -> dict:
    print(
        f"Deploy infrastructure with evm_tag: {evm_tag}, "
        f"proxy_tag: {proxy_tag}, faucet_tag: {faucet_tag}, "
        f"evm_branch: {evm_branch}, proxy_branch: {proxy_branch}"
    )
    os.environ["TF_VAR_neon_evm_commit"] = evm_tag
    os.environ["TF_VAR_faucet_model_commit"] = faucet_tag
    os.environ["TF_VAR_proxy_image_tag"] = proxy_tag
    os.environ["TF_VAR_proxy_model_commit"] = proxy_branch
    if use_real_price:
        os.environ["TF_VAR_use_real_price"] = "1"

    terraform.init(backend_config=TF_BACKEND_CONFIG)
    return_code, stdout, stderr = terraform.apply(skip_plan=True)
    print(f"code: {return_code}")
    print(f"stdout: {stdout}")
    print(f"stderr: {stderr}")
    with open(f"terraform.log", "w") as file:
        file.write(stdout)
        file.write(stderr)
    if return_code != 0:
        print("Terraform infrastructure is not built correctly")
        sys.exit(1)
    output = terraform.output(json=True)
    print(f"output: {output}")
    proxy_ip = output["proxy_ip"]["value"]
    solana_ip = output["solana_ip"]["value"]

    infra = dict(solana_ip=solana_ip, proxy_ip=proxy_ip)
    set_github_env(infra)
    return infra


def destroy_infrastructure():
    os.environ["TF_VAR_neon_evm_commit"] = "latest"
    os.environ["TF_VAR_faucet_model_commit"] = "develop"
    os.environ["TF_VAR_proxy_image_tag"] = "latest"
    os.environ["TF_VAR_proxy_model_commit"] = "develop"

    log = logging.getLogger()
    log.handlers = []
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "%(asctime)4s %(name)4s [%(filename)s:%(lineno)s - %(funcName)s()] %(levelname)4s %(message)4s"
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    def format_tf_output(output):
        return re.sub(r"(?m)^", " " * TF_OUTPUT_OFFSET, str(output))

    TF_OUTPUT_OFFSET = 16
    terraform.init(backend_config=TF_BACKEND_CONFIG)
    tf_destroy = terraform.apply("-destroy", skip_plan=True)
    log.info(format_tf_output(tf_destroy))


def download_remote_docker_logs():
    proxy_ip = os.environ.get("PROXY_IP")
    solana_ip = os.environ.get("SOLANA_IP")

    home_path = os.environ.get("HOME")
    artifact_logs = "./logs"
    ssh_key = "/tmp/ci-stands"
    os.mkdir(artifact_logs)
    if not os.path.exists(f"{home_path}/.ssh"):
        os.mkdir(f"{home_path}/.ssh")

    subprocess.run(f"ssh-keyscan -H {solana_ip} >> {home_path}/.ssh/known_hosts", shell=True)
    subprocess.run(f"ssh-keyscan -H {proxy_ip} >> {home_path}/.ssh/known_hosts", shell=True)

    ssh_client = SSHClient()
    ssh_client.load_system_host_keys()
    ssh_client.connect(solana_ip, username="root", key_filename=ssh_key, timeout=120)

    upload_service_logs(ssh_client, "opt_solana_1", artifact_logs)

    ssh_client.connect(proxy_ip, username="root", key_filename=ssh_key, timeout=120)
    services = ["postgres", "dbcreation", "indexer", "proxy", "faucet"]
    for service in services:
        upload_service_logs(ssh_client, service, artifact_logs)


def upload_service_logs(ssh_client, service, artifact_logs):
    scp_client = SCPClient(transport=ssh_client.get_transport())
    print(f"Upload logs for service: {service}")
    ssh_client.exec_command(f"touch /tmp/{service}.log.bz2")
    stdin, stdout, stderr = ssh_client.exec_command(
        f"sudo docker logs {service} 2>&1 | pbzip2 -f > /tmp/{service}.log.bz2"
    )
    print(stdout.read())
    print(stderr.read())
    scp_client.get(f"/tmp/{service}.log.bz2", artifact_logs)


def prepare_accounts(network_name, count, amount) -> tp.List:
    network_manager = NetworkManager(network_name)
    network = network_manager.get_network_object(network_name)
    accounts = faucet_cli.prepare_wallets_with_balance(network, count, amount)
    if os.environ.get("CI"):
        set_github_env(dict(accounts=",".join(accounts)))
    return accounts


def get_solana_accounts_in_tx(eth_transaction):
    network = os.environ.get("NETWORK")
    network_manager = NetworkManager(network)
    solana_url = network_manager.get_network_param(network, "solana_url")
    proxy_url = network_manager.get_network_param(network, "proxy_url")
    sol_client = SolanaClient(solana_url)
    web3_client = NeonChainWeb3Client(proxy_url)
    trx = web3_client.get_solana_trx_by_neon(eth_transaction)
    print(f"neon_getSolanaTransactionByNeonTransaction(eth_transaction={eth_transaction}): {trx}")
    print(f"minimum_ledger_slot={sol_client.get_minimum_ledger_slot()}")
    print(f"first_available_block={sol_client.get_first_available_block()}")
    print(f"get_slot={sol_client.get_slot()}")
    tr = sol_client.get_transaction(Signature.from_string(trx["result"][0]), max_supported_transaction_version=0)
    print(f"get_transaction({trx}): {tr}")
    if tr.value.transaction.transaction.message.address_table_lookups:
        alt = tr.value.transaction.transaction.message.address_table_lookups
        return len(alt[0].writable_indexes) + len(alt[0].readonly_indexes), len(trx["result"])
    else:
        return len(tr.value.transaction.transaction.message.account_keys), len(trx["result"])
