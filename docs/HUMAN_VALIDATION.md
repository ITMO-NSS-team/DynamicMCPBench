# DynamicMCPBench — Human Validation (≈90 min)

We check that the auto-generated tasks are good. **3 one-tap questions per card.** Anonymous
raters: **alpha, beta, gamma, delta, epsilon, zeta** (the lead tells you which you are).

## Setup (once)
```
git clone https://github.com/ITMO-NSS-team/DynamicMCPBench.git && cd DynamicMCPBench
python3 -m pip install huggingface_hub          # the only dependency
huggingface-cli login                           # your own token
```

## Do it (resume-safe — stop & restart anytime)
```
python3 scripts/annotate2.py fetch  --rater <you>
python3 scripts/annotate2.py run    --rater <you>
python3 scripts/annotate2.py submit --rater <you>
```
~175 cards, ~90 minutes. Progress saves after every card.

## Each card shows the prompt and the reference answer. You answer:
- **Q1. Is this a valid, realistic task?**  `y` yes · `n` no (nonsensical / impossible)
- **Q2. Does the REFERENCE answer correctly solve it?**  `y` yes · `p` partial · `n` no
- *(then a model's attempt + the auto-grader's PASS/FAIL appear)*
- **Q3. Do you agree with the auto-grader?**  `y` yes · `n` no

That's it. Keys: `Enter`=back, `x`=skip, `q`=save&quit. A note is optional.

**Judge by reading**, not by rules: does the request make sense (Q1), does the reference
answer actually deliver it (Q2), and is the grader's verdict on the model right (Q3). Don't
overthink — go with your first read.

## Lead
```
python3 scripts/annotate2.py build --evals eval_qwen3.6-35b.jsonl --cand cand_qwen3.6-35b.jsonl \
   --specs data/hf_root/specs_50x15.jsonl --traces data/hf_root/traces_50x15.jsonl \
   --raters alpha,beta,gamma,delta,epsilon,zeta --kappa 60 --push
python3 scripts/annotate2.py report --pull --out reports/human_validation.md \
   --json docs/experiments/human_validation.json
```
Report = per-category % valid & % reference-correct, scorer false-positive/negative rate,
Fleiss kappa on the shared kappa-set, and the flagged-task list.
