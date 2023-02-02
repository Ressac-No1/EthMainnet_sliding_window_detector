# Example: CrETH
addr="0xd06527d5e56a3495252a528c4987003b712860ee"
till_transaction_id=99999999999999
limit=100
offset=0

tx_idx_list=[]
while true
do
    raw_sub_tx_idx_list=$(curl "https://api.blockchair.com/ethereum/calls?q=recipient($addr),transaction_id(..$till_transaction_id)&limit=$limit&offset=$offset")
    if [ $(echo $raw_sub_tx_idx_list | jq '.data' | jq length) -eq 0 ]
    then
        break
    fi
    sub_tx_idx_list=$(echo $raw_sub_tx_idx_list | jq '.data | map({"block_index": .block_id, "transaction_index": (.transaction_id % 1000000), "transaction_hash": .transaction_hash, "time": .time, "sender": .sender})')
    #echo $till_transaction_id
    #echo $offset
    #echo $sub_tx_idx_list
    #echo $(echo $sub_tx_idx_list | jq length)
    tx_idx_list=$(echo [$tx_idx_list, $sub_tx_idx_list] | jq '.[0]+.[1]')
    new_till_transaction_id=($(echo $raw_sub_tx_idx_list | jq -r '.data[-1].transaction_id'))
    if [ $new_till_transaction_id == $till_transaction_id ]
    then
        offset+=100
	#echo $offset
    else
        till_transaction_id=$new_till_transaction_id
	offset=0
    fi
    sleep 1
done
echo ${tx_idx_list}
echo $(echo $tx_idx_list | jq length)

