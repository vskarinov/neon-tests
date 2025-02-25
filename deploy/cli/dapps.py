import os
import glob
import json
import typing as tp
import pathlib

import tabulate

from deploy.cli.infrastructure import get_solana_accounts_in_tx
from deploy.cli.network_manager import NetworkManager

from utils.web3client import NeonChainWeb3Client


REPORT_HEADERS = ["Action", "Fee", "Cost in $", "Accounts", "TRx", "Estimated Gas", "Used Gas", "Used % of EG"]
NETWORK_MANAGER = NetworkManager()


def set_github_env(envs: tp.Dict, upper=True) -> None:
    """Set environment for GitHub action"""
    path = os.getenv("GITHUB_ENV", str())
    if os.path.exists(path):
        with open(path, "a") as env_file:
            for key, value in envs.items():
                env_file.write(f"\n{key.upper() if upper else key}={str(value)}")


def prepare_report_data(directory):
    proxy_url = NETWORK_MANAGER.get_network_param(os.environ.get("NETWORK"), "proxy_url")
    web3_client = NeonChainWeb3Client(proxy_url)
    out = {}
    reports = {}
    for path in glob.glob(str(pathlib.Path(directory) / "*-report.json")):
        with open(path, "r") as f:
            rep = json.load(f)
            if type(rep) is list:
                for r in rep:
                    if "actions" in r:
                        reports[r["name"]] = r["actions"]
            else:
                if "actions" in rep:
                    reports[rep["name"]] = rep["actions"]

    for app in reports:
        out[app] = []
        for action in reports[app]:
            accounts, trx = get_solana_accounts_in_tx(action["tx"])
            tx = web3_client.get_transaction_by_hash(action["tx"])
            estimated_gas = int(tx.gas) if tx and tx.gas else None
            used_gas = int(action["usedGas"])
            row = [action["name"]]
            fee = used_gas * int(action["gasPrice"]) / 1000000000000000000
            used_gas_percentage = round(used_gas * 100 / estimated_gas, 2) if estimated_gas else None
            row.append(fee)
            row.append(fee * web3_client.get_token_usd_gas_price())
            row.append(accounts)
            row.append(trx)
            row.append(estimated_gas)
            row.append(used_gas)
            row.append(used_gas_percentage)
            out[app].append(row)
    return out


def print_report(data):
    report_content = ""
    for app in data:
        report_content += f'Cost report for "{app.title()}" dApp\n'
        report_content += "----------------------------------------\n"
        report_content += tabulate.tabulate(data[app], REPORT_HEADERS, tablefmt="simple_grid") + "\n"

    print(report_content)
    return report_content


def format_report_for_github_comment(data):
    headers = "| " + " | ".join(REPORT_HEADERS) + " |\n"
    headers += "| --- | --- | --- | --- | --- | --- | --- |--- |\n"
    report_content = ""

    for app in data:
        report_content += f'\nCost report for "{app.title()}" dApp\n\n'
        report_content += headers
        for action_data in data[app]:
            report_content += "| " + " | ".join([str(item) for item in action_data]) + " | " + "\n"
    return report_content
