import os
import json
import logging
import time
import random
import typing as tp
from functools import lru_cache

import web3.types
import requests
import gevent
from gevent.pool import Pool
from locust import TaskSet, events

from utils import helpers
from utils.faucet import Faucet
from utils.web3client import NeonChainWeb3Client

from .events import statistics_collector, save_transaction

LOG = logging.getLogger(__name__)

saved_transactions = []


@events.test_stop.add_listener
def save_transactions_list(environment: "locust.env.Environment", **kwargs):
    if "SAVE_TRANSACTIONS" in os.environ:
        web3_client = NeonWeb3ClientExt(
            environment.credentials["proxy_url"])

        def get_solana_trx(tr):
            return tr, web3_client.get_solana_trx_by_neon(tr)

        trx = {}
        print("Start save transactions list")
        pool = Pool(10)
        tasks = [pool.spawn(get_solana_trx, t) for t in saved_transactions]
        gevent.joinall(tasks)

        for res in tasks:
            if res.value is None:
                continue
            tr, resp = res.value
            if "result" not in resp:
                print(f"Can't get solana trx from tx {tr}: {resp}")
                continue
            trx[tr] = resp["result"]
        with (open(f"transactions-{random.randint(0, 1000)}.json", "w+")) as f:
            json.dump(trx, f)
        print("Results saved")


def init_session(size: int = 1000) -> requests.Session:
    """init request session with extended connection pool size"""
    adapter = requests.adapters.HTTPAdapter(
        pool_connections=size, pool_maxsize=size, pool_block=True)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class NeonWeb3ClientExt(NeonChainWeb3Client):
    """Extends Neon Web3 client adds statistics metrics"""

    def __getattribute__(self, item):
        ignore_list = ["create_account", "_send_transaction"]
        try:
            attr = object.__getattribute__(self, item)
        except AttributeError:
            attr = super(NeonWeb3ClientExt, self).__getattr__(item)
        if callable(attr) and item not in ignore_list:
            attr = statistics_collector()(attr)
            if "SAVE_TRANSACTIONS" in os.environ:
                attr = save_transaction(saved_transactions)(attr)
        return attr


class NeonProxyTasksSet(TaskSet):
    """Implements base initialization, creates data requirements and helpers"""

    faucet: tp.Optional[Faucet] = None
    account: tp.Optional["eth_account.signers.local.LocalAccount"] = None
    web3_client: tp.Optional[NeonWeb3ClientExt] = None

    def setup(self) -> None:
        """Prepare data requirements"""
        # create new shared account for each simulating user
        self.account = self.web3_client.create_account()
        self.check_balance()
        self.user.environment.shared.accounts.append(self.account)
        LOG.info(f"New account {self.account.address} created")

    def prepare_account(self) -> None:
        """Prepare data requirements"""
        # create new account for each simulating user
        self.account = self.web3_client.create_account()
        self.check_balance()
        LOG.info(f"New account {self.account.address} created")

    def on_start(self) -> None:
        """on_start is called when a Locust start before any task is scheduled"""
        # setup class once
        session = init_session(
            int(self.user.environment.parsed_options.num_users or self.user.environment.runner.target_user_count) * 100
        )
        self.credentials = self.user.environment.credentials
        LOG.info(f"Create web3 client to: {self.credentials['proxy_url']}")
        self.web3_client = NeonWeb3ClientExt(
            self.credentials["proxy_url"]
        )
        self.faucet = Faucet(
            self.credentials["faucet_url"], self.web3_client, session=session)

    def task_block_number(self) -> None:
        """Check the number of the most recent block"""
        self.web3_client.get_block_number()

    def check_balance(self, account: tp.Optional["eth_account.signers.local.LocalAccount"] = None) -> None:
        """Keeps account balance not empty"""
        account = account or self.account
        balance_before = self.web3_client.get_balance(account.address)
        if balance_before < 100:
            # add credits to account
            self.faucet.request_neon(account.address, 1000)
            for _ in range(5):
                if self.web3_client.get_balance(account.address) <= balance_before:
                    time.sleep(3)
                    continue
                break
            else:
                raise AssertionError(
                    f"Account {account.address} balance didn't change after 15 seconds")

    def deploy_contract(
        self,
        name: str,
        version: str,
        account: "eth_account.signers.local.LocalAccount",
        constructor_args: tp.Optional[tp.Any] = None,
        gas: tp.Optional[int] = 0,
        contract_name: tp.Optional[str] = None,
    ) -> "web3._utils.datatypes.Contract":
        """contract deployments"""

        contract_interface = self._compile_contract_interface(
            name, version, contract_name)
        contract_deploy_tx = self.web3_client.deploy_contract(
            account,
            abi=contract_interface["abi"],
            bytecode=contract_interface["bin"],
            constructor_args=constructor_args,
            gas=gas,
        )

        if not (contract_deploy_tx and contract_interface):
            return None, None

        contract = self.web3_client.eth.contract(
            address=contract_deploy_tx["contractAddress"], abi=contract_interface["abi"]
        )

        return contract, contract_deploy_tx

    @lru_cache(maxsize=32)
    def _compile_contract_interface(self, name, version, contract_name: tp.Optional[str] = None) -> tp.Any:
        """Compile contract inteface form file"""
        return helpers.get_contract_interface(name, version, contract_name=contract_name)
