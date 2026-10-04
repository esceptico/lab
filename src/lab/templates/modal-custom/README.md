# modal-custom

Plain PyTorch you own completely: custom architectures, losses on activations, anything Tinker
cannot express. The same script runs locally or on a Modal GPU.

- `train.py`: model, data, loss, eval. Logs `loss`, `val_loss`, `val_acc`, `active` per step,
  a figure, and `summary(val_loss=..., val_acc=...)`.
- `requirements.txt`: installed into the Modal image (cached between runs).

On Modal, `lab.modal_app` ships this folder, the campaign's `locked/` and the lab's `lib/` into
the container, runs the script, copies metrics, figures and artifacts back into the run, and
leaves cost to your Modal bill: lab records only amounts a service reports.

```bash
lab run -H "L1 on activations sparsifies without hurting accuracy" -P "active < 0.3, acc within 1%" -- \
  python train.py --sparsity 1e-2                                                   # local
lab run -H "..." -- modal run -m lab.modal_app --script train.py --args "--sparsity 1e-2" --gpu A10
```

Setup for Modal: `pip install modal` (or `uv tool install modal`) and `modal token new`.
GPUs: T4, L4, A10, L40S, A100-40GB, A100-80GB, H100, H200, B200 (append `:N` for several).
Checkpoints: write to `$LAB_DATA_DIR` (on Modal, the `lab-data` volume), not to artifacts.
