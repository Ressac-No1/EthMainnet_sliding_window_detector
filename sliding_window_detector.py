import sys, os
import json

"""
Argument list:
1st (Compulsory) - address of the subject contract
2nd (Optional, default value "tx_idx_list.txt") - filename of txn list of the subject contract
3rd (Optional, default value "Storage_Update_Facts/" - path of the facts files directory generated by the extractor
4th (Optional, parameter of the sliding-window detector) - width of slide window
5th (Optional, parameter of the sliding-window detector) - width of median filter
6th (Optional, parameter of the sliding-window detector) - threshold of absolute deviation to determine abnormality
"""
if len(sys.argv) <= 1:
    raise Exception ("Usage: python3 sliding_window_detector.py <contract_address> [tx_idx_list_filename, [storage_update_facts_path, [width of slide window, [width of median filter, [threshold of absolute deviation]]]]]")
else:
    contract_address = sys.argv[1]
tx_idx_list_filename = sys.argv[2] if len(sys.argv) > 2 else "tx_idx_list.txt"
storage_update_facts_path = sys.argv[3] if len(sys.argv) > 3 else "Storage_Update_Facts/"
window_width = int(sys.argv[4]) if len(sys.argv) > 4 else 0
median_filter_width = int(sys.argv[5]) if len(sys.argv) > 5 else 0
absolute_deviation_threshold = float(sys.argv[6]) if len(sys.argv) > 6 else -0.01

# Deduplication
def deduplicate_tx_idx_list(tx_idx_list_duplicated):
    tx_idx_list = [tx_idx_list_duplicated[0]]
    for i in range(1, len(tx_idx_list_duplicated)):
        if (tx_idx_list_duplicated[i]["transaction_hash"] != tx_idx_list_duplicated[i - 1]["transaction_hash"]):
            tx_idx_list.append(tx_idx_list_duplicated[i])
    return tx_idx_list

# Processing of txn facts files, to obtain the inner difference data
def process_facts_files(tx_idx_list):
    successful_tx_idx_list = []
    tx_timestamp = []
    inner_differences = []
    slot_indices_ever_changed = {}
    for i in range(len(tx_idx_list)):
        tx_idx = tx_idx_list[i]
        block_index = tx_idx["block_index"]
        tx_ordering = tx_idx["transaction_index"]
        tx_hash = tx_idx["transaction_hash"]
        with open(storage_update_facts_path + tx_hash + ".facts", 'r') as file:
            storage_update_facts = file.readlines()
        tx_failed = False

        # Fetch the variable's value changes by slot index during the execution of this txn, and compute the sum of absolute as the inner difference
        inner_difference = {}
        for fact in storage_update_facts:
            parts = fact.split(" <- ")
            # Skip failed or reverted txns
            if (len(parts) < 3):
                tx_failed = True
                break
            this_contract_address = parts[1][1:(parts[1].find(']['))]
            if this_contract_address == contract_address and parts[0] != "None" and parts[1][0] != '(':
                this_slot_index_str = parts[1][(parts[1].find(']['))+2:-1].lstrip('<').split(',')[0]
                if this_slot_index_str.isdigit():
                    this_slot_index = int(this_slot_index_str)
                    this_inner_difference = abs(int(parts[2], 0) - int(parts[0], 0))
                    if (this_slot_index in inner_difference):
                        inner_difference[this_slot_index] += this_inner_difference
                    else:
                        inner_difference[this_slot_index] = this_inner_difference
                        if (this_slot_index not in slot_indices_ever_changed):
                            slot_indices_ever_changed[this_slot_index] = i
        
        # Only successful txns are counted
        if (not tx_failed):
            successful_tx_idx_list.append(tx_idx)
            tx_timestamp.append(block_index + tx_ordering * 0.0001)
            inner_differences.append(inner_difference)

    return (successful_tx_idx_list, tx_timestamp, inner_differences, slot_indices_ever_changed)

# Read the txn list of the subject contract and process related facts files
try:
    with open(tx_idx_list_filename, 'r') as file:
        raw_tx_idx_list = file.read().replace('\'', '\"').replace('\n', '')
    tx_idx_list = deduplicate_tx_idx_list(json.loads(raw_tx_idx_list))
    successful_tx_idx_list, tx_timestamp, inner_differences, slot_indices_ever_changed = process_facts_files(tx_idx_list)
    tx_list_length = len(inner_differences)
    assert len(successful_tx_idx_list) == tx_list_length
    assert len(tx_timestamp) == tx_list_length
except Exception as e:
    print(e)

# Compute front percentile ranks of inner difference of every slot index
import matplotlib.pyplot as plt
from bisect import bisect_left
inner_differences_percentile_ranks = {}
for slot_index in slot_indices_ever_changed:
    this_percentile_ranks = []
    inner_differences_sorted = []
    for i in range(tx_list_length):
        if slot_index in inner_differences[i]:
            this_percentile_ranks.append(bisect_left(inner_differences_sorted, inner_differences[i][slot_index]) / (i + 1))
            inner_differences_sorted = sorted(inner_differences_sorted + [inner_differences[i][slot_index]])
        else:
            # No value change, the percentile rank is zero
            this_percentile_ranks.append(0)
            inner_differences_sorted = sorted(inner_differences_sorted + [0])
    inner_differences_percentile_ranks[slot_index] = this_percentile_ranks

# Detection
if (window_width > 0 and median_filter_width > 0):
    from statistics import median
    from functools import reduce
    # Median filtering
    filtered_inner_differences_percentile_ranks = {}
    filtered_percentile_rank_average = {}
    for slot_index in slot_indices_ever_changed:
        this_filtered_percentile_ranks = []
        this_filtered_percentile_rank_average = []
        median_filtering_window = []
        sum_of_filtered_percentile_ranks_in_the_window = 0
        for i in range(tx_list_length):
            # Seemed too slow to do list slicing in every loop
            #filtered_percentile_rank = median(inner_differences_percentile_ranks[slot_index][(i-median_filter_width+1 if i+1>=median_filter_width else 0):(i+1)])
            if (i < median_filter_width):
                median_filtering_window.append(inner_differences_percentile_ranks[slot_index][i])
            else:
                median_filtering_window[i % median_filter_width] = inner_differences_percentile_ranks[slot_index][i]
            filtered_percentile_rank = median(median_filtering_window)
            this_filtered_percentile_ranks.append(filtered_percentile_rank)
            # Compute the average filtered percentile ranks in the sliding window
            if (i >= window_width):
                this_filtered_percentile_rank_average.append(sum_of_filtered_percentile_ranks_in_the_window / window_width)
                sum_of_filtered_percentile_ranks_in_the_window += filtered_percentile_rank - this_filtered_percentile_ranks[i - window_width]
            elif (i > 0):
                this_filtered_percentile_rank_average.append(sum_of_filtered_percentile_ranks_in_the_window / i)
                sum_of_filtered_percentile_ranks_in_the_window += filtered_percentile_rank
            else:
                this_filtered_percentile_rank_average.append(None)
                sum_of_filtered_percentile_ranks_in_the_window += filtered_percentile_rank
        filtered_inner_differences_percentile_ranks[slot_index] = this_filtered_percentile_ranks 
        filtered_percentile_rank_average[slot_index] = this_filtered_percentile_rank_average

        #print(slot_index)
        #plt.plot(this_filtered_percentile_ranks, 'g')
        #plt.plot(list(map(lambda _, __: _ - __ if __ != None else 0, this_filtered_percentile_ranks, this_filtered_percentile_rank_average)), 'g')
        #plt.show()

    if (absolute_deviation_threshold > 0 and absolute_deviation_threshold < 1): 
        # Compute the alert level of each txn
        alert_levels = []
        for i in range(tx_list_length):
            this_alert_level = 0
            for slot_index in slot_indices_ever_changed:
                if (i >= window_width and i >= slot_indices_ever_changed[slot_index]):
                    absolute_deviation = abs(filtered_inner_differences_percentile_ranks[slot_index][i] - filtered_percentile_rank_average[slot_index][i]) 
                    if (absolute_deviation >= absolute_deviation_threshold):
                        this_alert_level += absolute_deviation
            alert_levels.append(this_alert_level)
        # Show the plot of alert levels
        plt.plot(alert_levels, 'r')
        plt.show()
        
        # Show all the periods of potential attacks with alert levels, here alerted_txns_id is a monotonic queue container
        alerted_txns_id = []
        for i in range(tx_list_length):
            if (alerted_txns_id != [] and alerted_txns_id[0] + window_width <= i):
                alerted_txns_id.pop(0)
            if (alerted_txns_id == [] or alert_levels[i] > alert_levels[alerted_txns_id[0]]):
                if (i >= window_width):
                    print ('Potential attacking detected at txn #{}, time: {}, hash: {}, alert level: {}'.format(i, successful_tx_idx_list[i]["time"], successful_tx_idx_list[i]["transaction_hash"], alert_levels[i]))
                    #print ('Potential attacking detected at txn #{}, hash: {}, alert level: {}'.format(i, successful_tx_idx_list[i]["transaction_hash"], alert_levels[i]))
                alerted_txns_id = [i]
            else:
                while (alert_levels[i] > alert_levels[alerted_txns_id[-1]]):
                    alerted_txns_id.pop()
                alerted_txns_id.append(i)

### Results

# CrETH
# 0xd06527d5e56a3495252a528c4987003b712860ee
#ATTACK_TXN_FROM = 36633
# time: 2021-02-13 04:17:32, tx_hash: 0x106718096c18827a7c7481f0c5a75055eb013261c1ea4abf86ba90b830290acc
#ATTACK_TXN_TO = 36639
# time: 2021-02-13 07:26:35, tx_hash: 0x8cdf82a2b3fb89f40521a9e5ea2abc3226f6b194b89f847cd7340c6790b180b6
#ATTACK_TXN_FROM = 46035
# time: 2021-08-30 04:03:40, tx_hash: 0x0016745693d68d734faa408b94cdf2d6c95f511b50f47b03909dc599c1dd9ff6
#ATTACK_TXN_TO = 46119
# time: 2021-08-30 05:44:47, tx_hash: 0xa9a1b8ea288eb9ad315088f17f7c7386b9989c95b4d13c81b69d5ddad7ffe61e
#ATTACK_TXN_FROM = 47452
# time: 2021-10-27 13:54:10, tx_hash: 0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92
#ATTACK_TXN_TO = 47452
# time: 2021-10-27 13:54:10, tx_hash: 0x0fe2542079644e107cbf13690eb9c2c65963ccb79089ff96bfaf8dced2331c92
# Attacks detected with (500, 50, 0.3): 2/3
# Attacks detected with (500, 5, 0.5): 1/3
# Attacks detected with (1200, 50, 0.3): 2/3

# TheDAO
# 0xbb9bc244d798123fde783fcc1c72d3bb8c189413 
#ATTACK_TXN_FROM = 22637
# time: 2016-06-17 03:34:48, tx_hash: 0x0ec3f2488a93839524add10ea229e773f6bc891b4eb4794c3337d4495263790b
#ATTACK_TXN_TO = 23136
# time: 2016-06-17 11:00:23, tx_hash: 0xa348da60799bff3ca804b3e49c96edebea44c5728a97f64bec3e21056d42f6e3
# Attacks detected with (500, 50, 0.3): 1/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 1/1

# Akropolis
# 0x73fc3038b4cd8ffd07482b92a52ea806505e5748
#ATTACK_TXN_FROM = 2324
# time: 2020-11-12 11:50:41, tx_hash: 0xddf8c15880a20efa0f3964207d345ff71fbb9400032b5d33b9346876bd131dc2
#ATTACK_TXN_TO = 2340
# time: 2020-11-12 12:04:37, tx_hash: 0x3db8d4618aa3b97eeb3af01f01692897d14f2da090d5d6407f550a1b10c15133
# Attacks detected with (500, 50, 0.3): 1/1
# Attacks detected with (500, 5, 0.5): 0/1
# Attacks detected with (1200, 50, 0.3): 1/1

# Harvest.Finance
# 0xf0358e8c3cd5fa238a29301d0bea3d63a17bedbe
#ATTACK_TXN_FROM = 2161
# time: 2020-10-26 02:53:58, tx_hash: 0x35f8d2f572fceaac9288e5d462117850ef2694786992a8c3f6d02612277b0877
#ATTACK_TXN_TO = 2177
# time: 2020-10-26 02:59:22, tx_hash: 0x3a06ef1cfd88d98be61a82c469c8c411417f92c5a9577446078874a72d71680f
# Attacks detected with (500, 50, 0.3): 1/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 1/1

# Lendf.me
# 0x0eee3e3828a45f7601d5f54bf49bb01d1a9df5ea
#ATTACK_TXN_FROM = 11416
# time: 2020-04-19 00:58:43, tx_hash: 0xe49304cd3edccf32069dcbbb5df7ac3b8678daad34d0ad1927aa725a8966d52a
#ATTACK_TXN_TO = 11517
# time: 2020-04-19 02:12:11, tx_hash: 0x2101276893be9aef459c28b52b3622719e18545d2cdaf46d9ac87fea27aa4725
# Attacks detected with (500, 50, 0.3): 1/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 1/1

# PAID Network
# 0x8c8687fc965593dfb2f0b4eaefd55e9d8df348df
#ATTACK_TXN_FROM = 2946
# time: 2021-03-05 17:42:21, tx_hash: 0x1bee0ec6da02dfa9ebf4eab7be3a4d456227e2fb005bfa6913e35bea6052fc95
#ATTACK_TXN_TO = 2974
# time: 2021-03-05 18:06:10, tx_hash: 0x1a23506c2a53e9811ebe7ab9d78ba1ab9e02766d2440ff152437a3176a314a38
# Attacks detected with (500, 50, 0.3): 1/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 1/1

# Saddle.Finance
# 0x5f86558387293b6009d7896a61fcc86c17808d62
#ATTACK_TXN_FROM = 4588
# time: 2022-04-30 08:24:23, tx_hash: 0xe7e0474793aad11875c131ebd7582c8b73499dd3c5a473b59e6762d4e373d7b8
#ATTACK_TXN_TO = 4588
# time: 2022-04-30 08:24:23, tx_hash: 0xe7e0474793aad11875c131ebd7582c8b73499dd3c5a473b59e6762d4e373d7b8
# Attacks detected with (500, 50, 0.3): 0/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 0/1

# Visor Finance
# 0x3a84ad5d16adbe566baa6b3dafe39db3d5e261e5
#ATTACK_TXN_FROM = 1704
# time: 2021-12-21 14:18:15, tx_hash: 0x69272d8c84d67d1da2f6425b339192fa472898dce936f24818fda415c1c1ff3f
#ATTACK_TXN_TO = 1704
# time: 2021-12-21 14:18:15, tx_hash: 0x69272d8c84d67d1da2f6425b339192fa472898dce936f24818fda415c1c1ff3f
# Attacks detected with (500, 50, 0.3): 0/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 0/1

# Yearn Finance (yDai)
# 0xacd43e627e64355f1861cec6d3a6688b31a6f952
#ATTACK_TXN_FROM = 26677
# time: 2021-02-04 21:12:40, tx_hash: 0x59faab5a1911618064f1ffa1e4649d85c99cfd9f0d64dcebbc1af7d7630da98b
#ATTACK_TXN_TO = 26692
# time: 2021-02-04 21:52:15, tx_hash: 0xb094d168dd90fcd0946016b19494a966d3d2c348f57b890410c51425d89166e8
# Attacks detected with (500, 50, 0.3): 1/1
# Attacks detected with (500, 5, 0.5): 1/1
# Attacks detected with (1200, 50, 0.3): 1/1
