import sys, os, threading
import json

# Connect to the node and initialize parameters
RPC_HOST = "pf.uni.lux"
RPC_PORT = 8545
from web3 import Web3
w3 = Web3(Web3.HTTPProvider("http://" + RPC_HOST + ":" + str(RPC_PORT), request_kwargs={'timeout': 36000}))
assert w3.isConnected(), "Connection to RPC node failed"

tx_idx_list_filename = sys.argv[1] if len(sys.argv) > 1 else "tx_idx_list.txt"
hash_dict_filename = sys.argv[2] if len(sys.argv) > 2 else ""
if (len(sys.argv) > 3):
    if hash_dict_filename:
        to_backup_hash_dict = '-h' in sys.argv[3:]
    else:
        to_backup_hash_dict = False
    contract_name = str(sys.argv[sys.argv.index('-n') + 1]) if '-n' in sys.argv[3:-1] else ""
    if contract_name:
        if contract_name[0] == '-':
            contract_name = ""
        elif contract_name[-1] != '-':
            contract_name += '-'
    thread_count = int(sys.argv[sys.argv.index('-t') + 1]) if '-t' in sys.argv[3:-1] and sys.argv[sys.argv.index('-t') + 1].isnumeric() else 20
else:
    to_backup_hash_dict = False
    contract_name = ""
    thread_count = 20

# Path of facts (output) file
STORAGE_UPDATE_FACTS_PATH = contract_name + "Storage_Update_Facts/"
try:
    os.mkdir(STORAGE_UPDATE_FACTS_PATH)
    print (STORAGE_UPDATE_FACTS_PATH + " successfully created")
except Exception as e:
    if ("File exists" in str(e)):
        print (STORAGE_UPDATE_FACTS_PATH + " already existed")
    else:
        print (e)

# Unpack a 32-byte value, requires a hash dictionary
from bisect import bisect_right
def unpack_bytes32_value(hash_idx_list, hash_value_list, hash_ignored, isHex, v):
    v_int = int(v, 16 if isHex else 10)
    if (v_int < 2 ** 92):
        # Number
        return v_int
    elif (v_int < 2 ** 160):
        # Address
        return "0x{:040x}".format(v_int)
    elif (hash_ignored or hash_value_list == [] or v_int < hash_value_list[0]):
        # Padded string or byte array
        return "b0x{:064x}".format(v_int)
    else:
        potential_entry = hash_idx_list[bisect_right(hash_value_list, v_int) - 1]
        offset = v_int - potential_entry["value"]
        if (offset >= 2 ** 40):
            # Padded string or byte array
            return "0x{:064x}".format(v_int)
        else:
            # Hash value
            keyBytes = potential_entry["key"][2:]
            if (len(keyBytes) < 64):
                # Decoded as an unpadded string or byte array
                return "(b0x{}, {})".format(keyBytes, offset)
            elif (len(keyBytes) == 64):
                # Decoded as a bytes32 value
                return "({}, {})".format(unpack_bytes32_value(hash_idx_list, hash_value_list, False, True, keyBytes), offset)
            elif (len(keyBytes) == 128):
                # Mapping slot with a bytes32 index
                return "<{}, {}, {}>".format(unpack_bytes32_value(hash_idx_list, hash_value_list, False, True, keyBytes[-64:]), unpack_bytes32_value(hash_idx_list, hash_value_list, True, True, keyBytes[:64]), offset)
            else:
                # Mapping slot with an unpadded string or byte array
                return "<{}, b0x{}, {}>".format(unpack_bytes32_value(hash_idx_list, hash_value_list, False, True, keyBytes[-64:]), keyBytes[:-64], offset)

# Deduplication
def deduplicate_tx_idx_list(tx_idx_list_duplicated):
    tx_idx_list = [tx_idx_list_duplicated[0]]
    for i in range(1, len(tx_idx_list_duplicated)):
        if (tx_idx_list_duplicated[i]["transaction_hash"] != tx_idx_list_duplicated[i - 1]["transaction_hash"]):
            tx_idx_list.append(tx_idx_list_duplicated[i])
    return tx_idx_list

def deduplicate_hash_idx_list(hash_idx_list_duplicated):
    hash_idx_list = [{"key": hash_idx_list_duplicated[0]["key"], "value": int(hash_idx_list_duplicated[0]["value"])}] if hash_idx_list_duplicated != [] else []
    for i in range(1, len(hash_idx_list_duplicated)):
        if (int(hash_idx_list_duplicated[i]["value"]) != int(hash_idx_list_duplicated[i - 1]["value"])):
            hash_idx_list.append({"key": hash_idx_list_duplicated[i]["key"], "value": int(hash_idx_list_duplicated[i]["value"])})
    return hash_idx_list

# Backup hash dictionary with all the KECCAK/SHA3 operations during execution of a list of transactions
def hash_backup_for_txn_list(sub_tx_idx_list, evm_tracer, sub_hash_idx_lists, thread_idx):
    hash_idx_list_duplicated = []
    for tx_idx in sub_tx_idx_list:
        tx_hash = tx_idx["transaction_hash"]
        try:
            hash_idx_list_duplicated += w3.manager.request_blocking('debug_traceTransaction', [tx_hash, {"tracer": evm_tracer, "timeout": "1h"}])["hashDict"]
        except Exception as e:
            print (e)
    sub_hash_idx_lists[thread_idx] = deduplicate_hash_idx_list(hash_idx_list_duplicated)

# Extraction via geth.debug.traceTransaction and geth.debug.storageRangeAt
def extract_txn_list(sub_tx_idx_list, hash_idx_list, hash_value_list, evm_tracer):
    for tx_idx in sub_tx_idx_list:
        raw_logs = w3.manager.request_blocking('debug_traceTransaction', [tx_idx["transaction_hash"], {"tracer": evm_tracer, "timeout": "1h"}]).structLogs
        storage_accessed = {}
        err_msg = None
        reverted = False

        for log in raw_logs:
            if "op" in log:
                # Monitoring log of SLOAD, the value before this txn is the value read from the first SLOAD among the logs without SSTORE before it
                if log.op == "SLOAD":
                    if log.contract in storage_accessed:
                        if log.location not in storage_accessed[log.contract]:
                            storage_accessed[log.contract][log.location] = {"previousValue": log.value}
                    else:
                        storage_accessed[log.contract] = {log.location: {"previousValue": log.value}}
                # Monitoring log of SSTORE, the value after this txn is the value set at the last SSTORE among the logs
                elif log.op == "SSTORE":
                    if log.contract in storage_accessed:
                        if log.location in storage_accessed[log.contract]:
                            storage_accessed[log.contract][log.location]["endValue"] = log.newValue
                        else:
                            storage_accessed[log.contract][log.location] = {"endValue": log.newValue}
                    else:
                        storage_accessed[log.contract] = {log.location: {"endValue": log.newValue}}
                elif log.op == "REVERT":
                    reverted = True
            elif log.error:
                err_msg = log.error

        # Output inner value changes to a facts file
        with open(STORAGE_UPDATE_FACTS_PATH + tx_idx["transaction_hash"] + ".facts", 'w') as output_file:
            for contract_hash in storage_accessed:
                for location_str in storage_accessed[contract_hash]:
                    location = unpack_bytes32_value(hash_idx_list, hash_value_list, False, False, location_str)
                    try:
                        log = storage_accessed[contract_hash][location_str]
                        if "endValue" in log:
                            if "previousValue" in log:
                                print (str(log["previousValue"]) + ' <- [' + contract_hash + '][' + str(location) + '] <- ' + str(log["endValue"]), file=output_file)
                            else:
                                # No previous value available, try to get it from the value at the beginning of the txn
                                try:
                                    location_hex = "0x{:064x}".format(int(location_str, 0))
                                    location_keccak = w3.keccak(hexstr=location_hex).hex()
                                    previous_storage_record = w3.manager.request_blocking('debug_storageRangeAt', [tx_idx["block_hash"], tx_idx["transaction_index"], contract_hash, location_keccak, 1]).storage
                                    previous_value = int(previous_storage_record[location_keccak].value, 0) if location_keccak in previous_storage_record.keys() and previous_storage_record[location_keccak].key == location_hex else None
                                except Exception as e:
                                    previous_value = None

                                print (str(previous_value) + ' <- [' + contract_hash + ']['+ str(location) + '] <- ' + str(log["endValue"]), file=output_file)
                    except Exception as e:
                        print(e)
                # Error and reverted message
                if (err_msg != None):
                    print("Error: " + str(err_msg), file=output_file)
                if (reverted):
                    print("Reverted", file=output_file)
            output_file.close()

# Read evm tracer from file
evm_tracer_filename = "evm_tracing.js"
try:
    with open(evm_tracer_filename, 'r') as file:
        evm_tracer = file.read().replace('\n', '')
except Exception as e:
    evm_tracer = None

# Read the list of txn indices and deduplicate
try:
    with open(tx_idx_list_filename, 'r') as file:
        raw_tx_idx_list = file.read().replace('\'', '\"').replace('\n', '')
    tx_idx_list = deduplicate_tx_idx_list(sorted(json.loads(raw_tx_idx_list), key=lambda x: x["transaction_hash"]))
except Exception as e:
    tx_idx_list = []

# Read hash dictionary
hash_idx_list = []
if (hash_dict_filename):
    try:
        with open(hash_dict_filename, 'r') as file:
            raw_hash_idx_list = file.read().replace('\'', '\"').replace('\n', '')
            file.close()
        hash_idx_list = json.loads(raw_hash_idx_list)
    except Exception as e:
        hash_idx_list = []

    if (to_backup_hash_dict):
        # Backup hash dictionary, accelerated via multi-threading
        try:
            if not evm_tracer:
                raise Exception ("No tracer available")
            elif not tx_idx_list:
                raise Exception ("No transaction to extract")
            
            threads = []
            sub_hash_idx_lists = []
            for t in range(thread_count):
                sub_hash_idx_lists.append([])
                threads.append(threading.Thread(target=hash_backup_for_txn_list, args=(tx_idx_list[t::thread_count], evm_tracer, sub_hash_idx_lists, t)))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            hash_idx_list_duplicated = hash_idx_list
            for sub_hash_idx_list in sub_hash_idx_lists:
                hash_idx_list_duplicated += sub_hash_idx_list
            hash_idx_list = deduplicate_hash_idx_list(sorted(hash_idx_list_duplicated, key=lambda x: int(x["value"])))

            with open(hash_dict_filename, 'w') as output_file:
                print (json.dumps(hash_idx_list), file=output_file)
                output_file.close()
        except Exception as e:
            print_exception(e)
hash_value_list = list(map(lambda x: x["value"], hash_idx_list))

try:
    if not evm_tracer:
        raise Exception ("No tracer available")
    elif not tx_idx_list:
        raise Exception ("No transaction to extract")
    else:
        # Multi-threaded extractor
        try:
            threads = []
            for t in range(thread_count):
                threads.append(threading.Thread(target=extract_txn_list, args=(tx_idx_list[t::thread_count], hash_idx_list, hash_value_list, evm_tracer)))
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        except Exception as e:
            print(e)
except Exception as e:
    print (e)

