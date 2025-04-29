!/bin/bash

# export PROMPT_DEVICE_ID_0=0,1,2,3
# export PROMPT_DEVICE_ID_1=4,5,6,7
# export DECODE_DEVICE_ID_0=8,9,10,11
# export DECODE_DEVICE_ID_1=12,13,14,15
# export NUM_PROMPT_INSTANCE=2
# export NUM_DECODE_INSTANCE=2

current_dir=$(dirname "$0")
OUTPUT_DIR="${current_dir}"

generate_hccl() {
    local role=$1
    local instance_index=$2
    local start=${devices[0]}
    local end=$((${devices[-1]}+1))
    python rank_table_utils.py generate \
        --device_num="[$start,$end)" \
        --visible_devices=$(IFS=,; echo "${devices[*]}") \
        --instance_role $role \
        --instance_rank $instance_index \
        --output_dir=$OUTPUT_DIR
}

for ((i=0; i<NUM_PROMPT_INSTANCE; i++)); do
    device_var_name="PROMPT_DEVICE_ID_${i}"
    devices=(${!device_var_name//,/ })
    generate_hccl "prefill" $i
done

# 生成decode实例（索引从0开始）
for ((i=0; i<NUM_DECODE_INSTANCE; i++)); do
    device_var_name="DECODE_DEVICE_ID_${i}"
    devices=(${!device_var_name//,/ })
    generate_hccl "decode" $i
done


python rank_table_utils.py merge $OUTPUT_DIR/prefill_*_rank_table_*.json $OUTPUT_DIR/decode_*_rank_table_*.json \
    --output_dir=$OUTPUT_DIR



