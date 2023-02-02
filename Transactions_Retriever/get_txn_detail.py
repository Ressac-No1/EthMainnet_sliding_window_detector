import sys, os, json
from web3 import Web3
RPC_HOST = "pf.uni.lux"
RPC_PORT = 8545
w3 = Web3(Web3.HTTPProvider("http://" + RPC_HOST + ":" + str(RPC_PORT), request_kwargs={'timeout': 36000}))
assert w3.isConnected(), "Connection to RPC node failed"

inner_txn_list_filename = sys.argv[1] if len(sys.argv) > 1 else "inner_txn_list"
try:
    with open(inner_txn_list_filename, 'r') as file:
        inner_txn_list_raw = file.read().replace('\'', '\"').replace('\n', '')
    inner_txn_list = json.loads(inner_txn_list_raw)
except Exception as e:
    inner_txn_list = []

old_tx_hash = None
tx_detail_list = []
for tx in inner_txn_list:
    tx_hash = tx["transaction_hash"]
    if (tx_hash == old_tx_hash):
        continue
    try:
        tx_detail = w3.eth.getTransaction(tx_hash)
    except Exception as e:
        print ('Failed to process {}'.format(tx))
        continue
    tx_detail_list.append({
        "time": tx["time"],
        "block_index":  tx_detail["blockNumber"],
        "block_hash": tx_detail["blockHash"].hex(),
        "transaction_index": tx_detail["transactionIndex"],
        "transaction_hash": tx_hash,
        "sender": tx["sender"] if "sender" in tx else tx_detail["from"]
    })
    old_tx_hash = tx_hash
print (json.dumps(tx_detail_list))
