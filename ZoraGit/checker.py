import json
import random
import time
import aiohttp
import asyncio
import csv
import pwinput

from datetime import datetime
from loguru import logger
import requests
from web3 import AsyncWeb3
from pathlib import Path
from decryption import decrypt_private_key, is_base64
from eth_account import Account
from termcolor import cprint

import config
from vars import NATIVE_DECIMALS


date_path = datetime.now().strftime('%d-%m-%Y-%H-%M-%S')
results_path = 'results/' + date_path
Path(results_path).mkdir(parents=True, exist_ok=True)


wallets_data = {}


def int_to_decimal(i, n):
    return i / (10 ** n)


class ZoraScan:

    def __init__(self, idx, private_key, proxy, old_ip):
        self.idx = idx
        if proxy is not None and len(proxy) > 4 and proxy[:4] != 'http':
            proxy = 'http://' + proxy
        self.proxy = proxy
        if old_ip != None and config.MOB_PROXY and len(config.MOB_PROXY_URL) > 0:
            if len(config.MOB_PROXY_URL) > 4 and config.MOB_PROXY_URL[:4] != 'http':
                self.proxy ='http://' + config.MOB_PROXY_URL
            else:
                self.proxy = config.MOB_PROXY_URL
        self.proxies = {'http': self.proxy, 'https': self.proxy}
        try:
            ip = requests.get(url='https://api.ipify.org/', proxies=self.proxies) if self.proxy is not None else requests.get('https://api.ipify.org/')
            self.ip = ip.text
            logger.info(f'Current IP: {ip.text}')
            if old_ip != None and config.MOB_PROXY_CHANGE and config.MOB_PROXY_CHANGE_URL:
                while(True):
                    try:
                        response = requests.get(config.MOB_PROXY_CHANGE_URL)
                        if response.status_code == 200:
                            logger.info(f'Change IP: Success',color='green')
                            logger.info(f'Wait 60 seconds',color='green')
                            time.sleep(60)
                            ip = requests.get(url='https://api.ipify.org/', proxies=self.proxies)
                            logger.info(f'Current IP: {ip.text}')
                            if old_ip != ip.text:
                                break
                        else:
                            logger.info(f'Change IP Failed: {response.text}',color='red')
                            logger.info(f'Wait 60 seconds',color='green')
                            time.sleep(60)
                            ip = requests.get(url='https://api.ipify.org/', proxies=self.proxies)
                            logger.info(f'Current IP: {ip.text}')
                    except requests.exceptions.RequestException as e:
                        logger.info(f'Change IP Failed: {e}', color='red')
                        logger.info(f'Wait 60 seconds',color='green')
                        time.sleep(60)
                        ip = requests.get(url='https://api.ipify.org/', proxies=self.proxies)
                        logger.info(f'Current IP: {ip.text}')
                        if old_ip != ip.text:
                            break
            old_ip = ip.text

        except Exception as e:
            raise(e)
        self.private_key = private_key
        self.account = Account().from_key(private_key)
        self.address = self.account.address

    async def get_minted_data(self):
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f'https://explorer.zora.energy/api/v2/addresses/{self.address}/tokens',
                                proxy=self.proxy) as resp_raw:
                resp = await resp_raw.json()
                erc721, erc1155 = 0, 0
                unique_erc721, unique_erc1155 = 0, 0
                for item in resp['items']:
                    token_type = item['token']['type']
                    if token_type == 'ERC-721':
                        erc721 += int(item['value'])
                        unique_erc721 += 1
                    elif token_type == 'ERC-1155':
                        erc1155 += int(item['value'])
                        unique_erc1155 += 1
                return unique_erc721, unique_erc1155, erc721, erc1155

    async def get_created_data(self):
        async with aiohttp.ClientSession() as sess:
            query = {
                'chainId': '1,7777777,10,8453,42161,81457',
                'direction': 'desc',
                'limit': 1000,
                'includeTokens': 'all',
                'excludeBrokenContracts': 'false',
            }
            async with sess.get(f'https://zora.co/api/user/{self.address.lower()}/admin',
                                params=query, proxy=self.proxy) as resp_raw:
                resp = await resp_raw.json()
                collections = len(resp)
                nfts = sum(len(r['tokens']) if r['contractStandard'] == 'ERC1155' else 1 for r in resp)
                return collections, nfts

    async def get_data(self):
        logger.info(f'{self.idx}) Processing {self.address}')
        data = [None] * 10

        try:
            req_args = {} if self.proxy is None or self.proxy == '' else {
                'proxy': self.proxy,
            }
            w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(config.RPCs['Zora'], request_kwargs=req_args))
            tx_count = await w3.eth.get_transaction_count(self.address)
            balance = await w3.eth.get_balance(self.address)
            balance = int_to_decimal(balance, NATIVE_DECIMALS)
            balance = '%.4f' % balance
            data[0], data[1] = balance, tx_count
        except Exception as e:
            logger.error(f'{self.idx}) Failed to get chain data: {str(e)}')

        try:
            unique_erc721, unique_erc1155, erc721, erc1155 = await self.get_minted_data()
            data[2], data[3], data[4] = erc721 + erc1155, erc721, erc1155
            data[5], data[6], data[7] = unique_erc721 + unique_erc1155, unique_erc721, unique_erc1155
        except Exception as e:
            logger.error(f'{self.idx}) Failed to get nft data: {str(e)}')

        try:
            data[8], data[9] = await self.get_created_data()
        except Exception as e:
            logger.error(f'{self.idx}) Failed to get created data: {e}')

        wallets_data[self.address] = data
        logger.success(f'{self.idx}) Data filled')


async def fill_batch(batch):
    old_ip = '0.0.0.0'
    for idx, (key, proxy) in batch:
        client = ZoraScan(idx, key, proxy, old_ip)
        old_ip = client.ip
        await client.get_data()
        await asyncio.sleep(1)


async def fill_data(data):
    tasks = []
    batches = [[] for _ in range(config.CHECKER_THREADS)]
    for i, d in enumerate(data):
        batches[i % config.CHECKER_THREADS].append(d)
    for b in batches:
        tasks.append(asyncio.create_task(fill_batch(b)))
    await asyncio.gather(*tasks)


def main():
    random.seed(int(datetime.now().timestamp()))

    with open('files/wallets.txt', 'r', encoding='utf-8') as file:
        passwordWallet = pwinput.pwinput(prompt='Enter your password for wallets or skip:', mask='*')
        wallets = file.read().splitlines()
        if passwordWallet:
            try:
                keys = []
                for key in wallets:
                    key = decrypt_private_key(key, passwordWallet)
                    keys.append(key)
                wallets = keys
            except Exception as e:
                if 'Padding is incorrect' in str(e):
                    cprint(f'Failed to encrypt: Wrong password', color='red')
                else:
                    cprint(f'Failed to encrypt: {str(e)}', color='red')
                return
            
    with open('files/proxies.txt', 'r', encoding='utf-8') as file:
        proxies = file.read().splitlines()

    if len(proxies) == 0:
        proxies = [None] * len(wallets)
    if len(proxies) != len(wallets):
        cprint('Proxies count doesn\'t match wallets count. Add proxies or leave proxies file empty', 'red')
        return

    wallets = [w if w.find(';') == -1 else w.split(';')[1] for w in wallets]

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    loop.run_until_complete(fill_data(list(enumerate(list(zip(wallets, proxies)), start=1))))

    csv_data = [['Address', 'Balance', 'Tx Count',
                 'Total NFT', 'ERC-721', 'ERC-1155',
                 'Unique Total NFT', 'Unique ERC-721', 'Unique ERC-1155',
                 'Created Collections', 'Created NFTs']]
    for w in wallets:
        address = ZoraScan(None, w, None).address
        csv_data.append([address] + list(wallets_data[address]))

    with open(f'{results_path}/stats.csv', 'w') as file:
        writer = csv.writer(file)
        writer.writerows(csv_data)

    print()
    logger.success(f'Stats saves in {results_path}/stats.csv')


if __name__ == '__main__':
    cprint('\n#########################################\n#', 'cyan', end='')
    cprint(f'Started'.center(39), 'magenta', end='')
    cprint('#\n#########################################', 'cyan')

    main()
