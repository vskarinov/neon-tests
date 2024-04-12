import hashlib
import json

import base58
from solana.publickey import PublicKey
from solana.system_program import SYS_PROGRAM_ID
from solana.transaction import AccountMeta, TransactionInstruction
from spl.token.constants import TOKEN_PROGRAM_ID
from spl.token.instructions import get_associated_token_address, approve, ApproveParams

from utils.instructions import TransactionWithComputeBudget, make_CreateBalanceAccount


class Instruction:

    @staticmethod
    def claim(_from, to, amount, web3_client, ata_address,
              emulate_signer, contract, gas_price=None):
        emulated_tx = None
        result = dict()

        claim_to = contract.contract.functions.claimTo(
            bytes(ata_address), _from.address, amount)
        data = claim_to.abi

        tx = {
            "from": _from.address,
            "to": to,
            "nonce": web3_client.eth.get_transaction_count(emulate_signer.address),
            "gasPrice": gas_price if gas_price is not None else web3_client.gas_price(),
            "chainId": web3_client.eth.chain_id,
            "data": json.dumps(data).encode('utf-8'),
            "gas": 100000000
        }

        signed_tx = web3_client._web3.eth.account.sign_transaction(
            tx, _from.key)
        if signed_tx.rawTransaction is not None:
            emulated_tx = web3_client.get_neon_emulate(
                str(signed_tx.rawTransaction.hex())[2:])
        if emulated_tx is not None:
            for account in emulated_tx['result']['solana_accounts']:
                key = account['pubkey']
                result[key] = AccountMeta(pubkey=PublicKey(
                    key), is_signer=False, is_writable=True)
                if 'contract' in account:
                    key = account['contract']
                    result[key] = AccountMeta(pubkey=PublicKey(
                        key), is_signer=False, is_writable=True)

            for account in emulated_tx['result']['solana_accounts']:
                key = account['pubkey']
                result[key] = AccountMeta(pubkey=PublicKey(
                    key), is_signer=False, is_writable=True)

        return signed_tx, result

    @staticmethod
    def build_tx_instruction(solana_wallet, neon_wallet, neon_raw_transaction,
                            neon_keys, evm_loader_id):
        program_id = PublicKey(evm_loader_id)
        treasure_pool_index = 2
        treasure_pool_address = get_collateral_pool_address(
            treasure_pool_index, evm_loader_id)

        data = bytes.fromhex('32') + treasure_pool_index.to_bytes(4, 'little') + \
               bytes.fromhex(str(neon_raw_transaction.hex())[2:])
        keys = [AccountMeta(pubkey=solana_wallet, is_signer=True, is_writable=True),
                AccountMeta(pubkey=treasure_pool_address,
                            is_signer=False, is_writable=True),
                AccountMeta(pubkey=neon_wallet,
                            is_signer=False, is_writable=True),
                AccountMeta(pubkey=SYS_PROGRAM_ID,
                            is_signer=False, is_writable=False),
                AccountMeta(pubkey=program_id, is_signer=False,
                            is_writable=False),
                ]

        for k in neon_keys:
            keys.append(neon_keys[k])

        return TransactionInstruction(
            keys=keys,
            program_id=program_id,
            data=data
        )


def neon_transfer_tx(
    web3_client, sol_client, amount, spl_token, solana_account, neon_account, erc20_spl, evm_loader_id
):
    chain_id = web3_client.eth.chain_id
    delegate_pda = sol_client.ether2balance(neon_account.address, chain_id, evm_loader_id)
    contract_pubkey = PublicKey(sol_client.ether2program(neon_account.address)[0])

    emulate_signer = get_solana_wallet_signer(solana_account, neon_account, web3_client)
    emulated_signer_pda = sol_client.ether2balance(emulate_signer.address, chain_id, evm_loader_id)
    emulated_contract_pubkey = PublicKey(sol_client.ether2program(emulate_signer.address)[0])

    solana_wallet = solana_account.public_key

    ata_address = get_associated_token_address(solana_wallet, PublicKey(spl_token["address_spl"]))

    neon_transaction, neon_keys = Instruction.claim(
        neon_account, spl_token["address"], amount, web3_client, ata_address, emulate_signer, erc20_spl
    )

    tx = TransactionWithComputeBudget(solana_account)

    tx.add(
        approve(
            ApproveParams(
                program_id=TOKEN_PROGRAM_ID,
                source=ata_address,
                delegate=delegate_pda,
                owner=solana_account.public_key,
                amount=amount,
            )
        )
    )

    tx.add(make_CreateBalanceAccount(evm_loader_id,
                                     solana_wallet,
                                     bytes.fromhex(str(neon_account.address)[2:]),
                                     delegate_pda,
                                     contract_pubkey,
                                     chain_id))

    tx.add(
        make_CreateBalanceAccount(evm_loader_id,
                                  solana_wallet,
                                  bytes.fromhex(str(emulate_signer.address)[2:]),
                                  emulated_signer_pda,
                                  emulated_contract_pubkey,
                                  chain_id)

    )
    tx.add(
        Instruction.build_tx_instruction(
            solana_wallet, delegate_pda, neon_transaction.rawTransaction, neon_keys, evm_loader_id
        )
    )
    return tx


def get_collateral_pool_address(index: int, evm_loader_id):
    return PublicKey.find_program_address(
        [bytes('treasury_pool', 'utf8'), index.to_bytes(4, 'little')],
        PublicKey(evm_loader_id)
    )[0]


def get_solana_wallet_signer(solana_account, neon_account, web3_client):
    solana_wallet = base58.b58encode(str(solana_account.public_key))
    neon_wallet = bytes(neon_account.address, 'utf-8')
    new_wallet = hashlib.sha256(solana_wallet + neon_wallet).hexdigest()
    emulate_signer_private_key = f'0x{new_wallet}'
    return web3_client.eth.account.from_key(emulate_signer_private_key)


