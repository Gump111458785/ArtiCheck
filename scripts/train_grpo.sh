#!/usr/bin/env bash
# GPU-unverified launcher targeting the verl revision in docs/TRAINING.md.
set -euo pipefail
: "${MODEL_PATH:?Set MODEL_PATH to a merged SFT model or Hugging Face model}"
: "${TRAIN_FILE:?Set TRAIN_FILE to repository-isolated training parquet}"
: "${VAL_FILE:?Set VAL_FILE to separate validation parquet}"
articheck_root=$(cd "$(dirname "$0")/.." && pwd)
export PYTHONPATH="$articheck_root${PYTHONPATH:+:$PYTHONPATH}"
python -m verl.trainer.main_ppo \
  algorithm.adv_estimator=grpo \
  data.train_files="$TRAIN_FILE" data.val_files="$VAL_FILE" \
  data.train_batch_size=16 data.max_prompt_length=4096 data.max_response_length=2048 \
  data.truncation=error \
  actor_rollout_ref.model.path="$MODEL_PATH" \
  actor_rollout_ref.model.lora_rank=16 actor_rollout_ref.model.lora_alpha=32 \
  actor_rollout_ref.model.enable_gradient_checkpointing=True \
  actor_rollout_ref.actor.strategy=fsdp2 actor_rollout_ref.ref.strategy=fsdp2 \
  actor_rollout_ref.actor.optim.lr=1e-6 \
  actor_rollout_ref.actor.ppo_mini_batch_size=8 \
  actor_rollout_ref.actor.use_dynamic_bsz=True \
  actor_rollout_ref.actor.ppo_max_token_len_per_gpu=16384 \
  actor_rollout_ref.actor.clip_ratio_low=0.2 actor_rollout_ref.actor.clip_ratio_high=0.28 \
  actor_rollout_ref.actor.loss_agg_mode=token-mean \
  actor_rollout_ref.actor.use_kl_loss=True \
  actor_rollout_ref.rollout.name=vllm actor_rollout_ref.rollout.mode=async \
  actor_rollout_ref.rollout.n=8 \
  actor_rollout_ref.rollout.tensor_model_parallel_size=1 \
  actor_rollout_ref.rollout.gpu_memory_utilization=0.5 \
  actor_rollout_ref.rollout.calculate_log_probs=True \
  actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=True \
  actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu=16384 \
  actor_rollout_ref.ref.log_prob_use_dynamic_bsz=True \
  actor_rollout_ref.ref.log_prob_max_token_len_per_gpu=16384 \
  actor_rollout_ref.rollout.agent.agent_loop_config_path="$articheck_root/configs/agent_loop.yaml" \
  trainer.n_gpus_per_node="${NGPUS:-2}" trainer.nnodes=1 \
  trainer.logger='["console"]' trainer.project_name=ArtiCheck \
  trainer.experiment_name=planner-grpo-mvp trainer.total_epochs=1 \
  trainer.save_freq=20 trainer.test_freq=10 "$@"
