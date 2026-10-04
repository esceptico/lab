"""Templates and remote plumbing, tested without the paid services they drive.

The Tinker and Prime tests use stand-ins shaped like the real APIs (tinker-cookbook sl_loop.py,
prime CLI JSON output as of 2026-09-20); they prove our code, not the services.
"""

import importlib
import os
import py_compile
import stat
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from lab.cli import main
from lab.core.campaigns import create_campaign
from lab.events import read as read_metrics
from lab.remote import pack, unpack

LAB = Path(__file__).resolve().parent.parent
TEMPLATES = LAB / "src" / "lab" / "templates"


@pytest.fixture
def campaign(lab, monkeypatch):
    campaign = create_campaign(lab, "demo", metric="reward", goal="max", budget_usd=None)
    monkeypatch.chdir(campaign.root)
    return campaign


def test_remote_pack_unpack_round_trip(tmp_path):
    remote, local = tmp_path / "remote", tmp_path / "local"
    (remote / "figures").mkdir(parents=True)
    (remote / "metrics.jsonl").write_text('{"kind": "point", "step": 1, "loss": 0.5}\n')
    (remote / "figures" / "a.json").write_text("{}")
    (remote / "scratch.bin").write_bytes(b"not kept")
    local.mkdir()
    (local / "metrics.jsonl").write_text('{"kind": "cost", "usd": 0.1}\n')
    files = pack(remote)
    assert set(files) == {"metrics.jsonl", "figures/a.json"}
    unpack(files, local)
    parsed = read_metrics(local / "metrics.jsonl")
    assert parsed.cost == 0.1 and parsed.summary == {"loss": 0.5}
    assert (local / "figures" / "a.json").exists()
    with pytest.raises(ValueError):
        unpack({"../escape": b"x"}, local)


def test_new_exp_from_template(campaign, lab):
    assert main(["new", "exp", "sft", "--template", "tinker-sft"]) == 0
    exp = campaign.experiments / "sft"
    assert (exp / "train.py").exists() and (exp / "losses.py").exists()
    assert campaign.origin(exp).source == "template:tinker-sft"
    assert main(["new", "exp", "x", "--template", "nope"]) == 1


FAKE_PRIME = r"""#!/usr/bin/env python3
import json, sys, pathlib
state = pathlib.Path(__file__).with_name("polls")
args = [a for a in sys.argv[1:] if a not in ("-o", "json", "-y")]
if args[0] == "train" and args[1].endswith(".toml"):
    assert "-o" in sys.argv, "launch must ask for JSON"
    print(json.dumps({"run": {"runId": "run-42"}}))
elif args[:2] == ["train", "get"]:
    n = int(state.read_text()) if state.exists() else 0
    state.write_text(str(n + 1))
    print(json.dumps({"run": {"id": "run-42", "status": "COMPLETED" if n >= 1 else "RUNNING"}}))
elif args[:2] == ["train", "progress"]:
    assert "-o" not in sys.argv, "progress has no -o flag"
    print(json.dumps({"latest_step": 3}))
elif args[:2] == ["train", "metrics"]:
    assert "-o" not in sys.argv, "metrics has no -o flag"
    print(json.dumps({"metrics": [{"step": 0, "reward/mean": 0.2, "tag": "x"}, {"step": 10, "reward/mean": 0.7}]}))
elif args[:2] == ["train", "usage"]:
    print(json.dumps({"run_id": "run-42", "total_cost_usd": 3.25}))
else:
    sys.exit(f"unexpected: {sys.argv}")
"""


def test_prime_rl_run_records_metrics_and_cost(campaign, lab, tmp_path, monkeypatch):
    main(["new", "exp", "rl", "--template", "prime-rl"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "prime"
    fake.write_text(FAKE_PRIME)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.chdir(campaign.experiments / "rl")
    assert main(["run", "-H", "rl works", "--", sys.executable, "run.py", "rl.toml", "--poll", "0"]) == 0
    record = campaign.run("r001")
    assert record.metrics["reward"] == 0.7
    assert record.cost_usd == 3.25
    assert record.artifacts[0].path == "artifacts/prime_run.json"


STUBS = {
    "tinker/__init__.py": """
        class AdamParams:
            def __init__(self, **kw): self.__dict__.update(kw)
    """,
    "tinker_cookbook/__init__.py": "",
    "tinker_cookbook/model_info.py": "def get_recommended_renderer_name(name): return 'stub'",
    "tinker_cookbook/renderers.py": """
        class TrainOnWhat: ALL_ASSISTANT_MESSAGES = 'all'
        def get_renderer(name, tok): return None
    """,
    "tinker_cookbook/tokenizer_utils.py": "def get_tokenizer(name): return None",
    "tinker_cookbook/supervised/__init__.py": "",
    "tinker_cookbook/supervised/data.py": "def conversation_to_datum(*a): raise NotImplementedError",
    "tinker_cookbook/supervised/common.py": """
        def compute_mean_nll(logprobs_list, weights_list):
            num = -sum(sum(l * w for l, w in zip(lp, ws)) for lp, ws in zip(logprobs_list, weights_list))
            return num / sum(sum(ws) for ws in weights_list)
    """,
}


class Done:
    def __init__(self, value):
        self.value = value

    def result(self):
        return self.value


class Result:
    def __init__(self, batch, scale):
        self.loss_fn_outputs = [{"logprobs": [-scale] * len(d.loss_fn_inputs["weights"])} for d in batch]
        self.metrics = {"loss:sum": scale}


class Datum:
    def __init__(self, n):
        self.loss_fn_inputs = {"weights": [1.0] * n}
        self.model_input = type("MI", (), {"length": n})()


class FakeClient:
    """Loss falls with every optimiser step, like a model that learns."""

    def __init__(self):
        self.steps, self.calls = 0, []

    def forward_backward(self, batch, loss_fn):
        self.calls.append(("fb", loss_fn))
        return Done(Result(batch, 1.0 / (1 + self.steps)))

    def forward_backward_custom(self, batch, fn):
        self.calls.append(("custom", fn.__name__))
        return Done(Result(batch, 1.0 / (1 + self.steps)))

    def optim_step(self, params):
        self.steps += 1
        self.calls.append(("opt", round(params.learning_rate, 6)))
        return Done(None)

    def forward(self, batch, loss_fn):
        return Done(Result(batch, 1.0 / (1 + self.steps)))


def test_tinker_sft_loop_logs_to_lab(tmp_path, monkeypatch):
    for rel, body in STUBS.items():
        path = tmp_path / "stubs" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body))
    monkeypatch.syspath_prepend(str(tmp_path / "stubs"))
    monkeypatch.syspath_prepend(str(TEMPLATES / "tinker-sft"))
    run = tmp_path / "run"
    run.mkdir()
    monkeypatch.setenv("LAB_RUN_DIR", str(run))
    for name in ("train", "losses"):
        sys.modules.pop(name, None)
    train = importlib.import_module("train")

    args = SimpleNamespace(
        batch=2, epochs=1, max_steps=None, lr=1e-4, eval_every=2, loss="cross_entropy", model="stub", seed=0
    )
    client = FakeClient()
    rows = [[{"role": "user", "content": str(i)}] for i in range(8)]
    val_nll = train.train(args, client, lambda m: Datum(5), rows, rows[:2])

    assert [c for c in client.calls if c[0] == "opt"] == [
        ("opt", 1e-4),
        ("opt", 7.5e-5),
        ("opt", 5e-5),
        ("opt", 2.5e-5),
    ]
    parsed = read_metrics(run / "metrics.jsonl")
    assert [p["step"] for p in parsed.points] == [0, 1, 2, 3]
    assert "val_nll" in parsed.points[0] and "val_nll" in parsed.points[3]
    assert val_nll == pytest.approx(0.2)  # evaluated after the 4th step
    assert parsed.points[-1]["tokens"] == 40 and parsed.cost == 0  # tokens are recorded; no priced guess

    args.loss = "focal_nll"
    train.train(args, client, lambda m: Datum(5), rows, rows[:2])
    assert ("custom", "focal_nll") in client.calls


def test_modal_app_and_templates_compile():
    for path in [LAB / "src/lab/modal_app.py", *TEMPLATES.glob("*/*.py")]:
        py_compile.compile(str(path), doraise=True)


@pytest.mark.network
def test_interp_helpers_on_a_tiny_model():
    """Real torch + transformers on a 2-layer random GPT-2: Jacobian shape, ablation, loss."""
    import torch

    from lab import interp

    model, tok = interp.load("sshleifer/tiny-gpt2", device="cpu")
    J = interp.jacobian(model, tok, "The capital of France is", src=0, dst=1)
    d = model.config.n_embd
    assert J.shape == (d, d) and torch.isfinite(J).all()
    S, Vh = interp.spectrum(J)
    assert S.shape == (d,) and bool((S[:-1] >= S[1:]).all())
    base = interp.next_token_loss(model, tok, ["hello world", "a b c"])
    with interp.ablate(model, 0, Vh[:1]):
        ablated = interp.next_token_loss(model, tok, ["hello world", "a b c"])
    assert ablated.shape == base.shape == (2,)
    assert not torch.equal(ablated, base)  # the hook changed the forward pass
    after = interp.next_token_loss(model, tok, ["hello world", "a b c"])
    assert torch.equal(after, base)  # and was removed afterwards
    q = interp.random_basis(d, 2, seed=0)
    assert torch.allclose(q @ q.T, torch.eye(2), atol=1e-5)


def test_custom_losses_match_cross_entropy_and_backprop(monkeypatch):
    monkeypatch.syspath_prepend(str(TEMPLATES / "tinker-sft"))
    sys.modules.pop("losses", None)
    import torch

    losses = importlib.import_module("losses")

    class Tensor:  # tinker.TensorData carries values in .data
        def __init__(self, data):
            self.data = data

    datum = type("D", (), {"loss_fn_inputs": {"weights": Tensor([0.0, 1.0, 1.0])}})()
    logprobs = torch.log(torch.tensor([0.5, 0.25, 0.8])).requires_grad_()
    loss, metrics = losses.weighted_nll([datum], [logprobs])
    expected = -(torch.log(torch.tensor(0.25)) + torch.log(torch.tensor(0.8))) / 2
    assert torch.allclose(loss, expected) and metrics["weighted_nll"] == pytest.approx(float(expected))
    loss.backward()
    assert logprobs.grad[0] == 0 and logprobs.grad[1] < 0  # masked token gets no gradient
    focal, _ = losses.focal_nll([datum], [logprobs.detach().requires_grad_()])
    assert focal < loss  # confident tokens are down-weighted


@pytest.mark.network
def test_interp_reads_raw_residual_and_ablates_one_position():
    import torch

    from lab import interp

    model, tok = interp.load("sshleifer/tiny-gpt2", device="cpu")
    last = len(interp.blocks(model)) - 1
    raw = interp.resid(model, tok, ["a b c"], last)[0]
    with torch.no_grad():
        normed = model(**tok("a b c", return_tensors="pt"), output_hidden_states=True).hidden_states[-1][0]
    assert not torch.allclose(raw, normed)  # hidden_states[-1] went through ln_f; resid() did not

    clean = interp.resid(model, tok, ["a b c"], 0)[0]
    basis = torch.eye(model.config.n_embd)[:1]
    with interp.ablate(model, 0, basis, position=-1):
        ablated = interp.resid(model, tok, ["a b c"], 0)[0]  # hook registered after ablate's: sees its output
    assert torch.allclose(ablated[:-1], clean[:-1])  # earlier positions untouched
    assert ablated[-1, 0].abs() < 1e-6 and not torch.allclose(ablated[-1], clean[-1])  # last lost direction 0


def ssh(root: Path, python: str = sys.executable) -> list[str]:
    """`lab run` arguments for the SSH runner with --host local."""
    return [
        "--",
        sys.executable,
        "-m",
        "lab.ssh_app",
        "--host",
        "local",
        "--root",
        str(root),
        "--python",
        python,
        "--no-setup",
    ]


def test_ssh_runner_round_trip_on_local_host(campaign, lab, tmp_path, monkeypatch):
    """The whole ssh path (push, env file, run, pull) with --host local instead of ssh."""
    main(["new", "exp", "remote"])
    exp = campaign.experiments / "remote"
    (exp / "train.py").write_text(
        "import os, interp_marker\n"
        "from lab import log, summary, fig\n"
        "log(step=0, loss=1.0)\n"
        "summary(val_loss=0.5, token_seen=float(os.environ.get('HF_TOKEN') == 'secret'))\n"
        "fig.bars(['a'], {'x': [1.0]}, title='remote fig')\n"
    )
    (lab.lib / "interp_marker.py").write_text("")  # lib/ must be importable remotely
    (campaign.locked / "eval.txt").write_text("x\n")
    monkeypatch.setenv("HF_TOKEN", "secret")
    monkeypatch.chdir(exp)
    code = main(["run", "-H", "remote works", *ssh(tmp_path / "machine")])
    assert code == 0
    record = campaign.run("r001")
    assert record.metrics == {"loss": 1.0, "val_loss": 0.5, "token_seen": 1.0}
    assert [f.type for f in record.figures] == ["bars"]
    assert record.cost_usd == 0
    assert not any((tmp_path / "machine").iterdir())  # the token and the run's folder are gone


def test_ssh_runner_reports_the_script_exit_code_and_output(campaign, tmp_path, monkeypatch):
    main(["new", "exp", "remote"])
    exp = campaign.experiments / "remote"
    (exp / "train.py").write_text("print('partial result')\nraise SystemExit(3)\n")
    monkeypatch.chdir(exp)
    code = main(["run", *ssh(tmp_path / "m")])
    assert code == 3 and campaign.run("r001").exit_code == 3
    assert "partial result" in (campaign.run_dir("r001") / "stdout.log").read_text()


def test_ssh_runner_ends_when_the_script_cannot_start(campaign, tmp_path, monkeypatch):
    main(["new", "exp", "remote"])
    monkeypatch.chdir(campaign.experiments / "remote")
    (campaign.experiments / "remote" / "train.py").write_text("print('never')\n")
    code = main(["run", *ssh(tmp_path / "m", python="no-such-python")])
    assert code == 1  # not a wait for an exit code that never comes


def test_ssh_runner_keeps_runs_with_the_same_id_apart(campaign, lab, tmp_path, monkeypatch):
    """Two labs both have an r001: on one machine, each gets its own folder and only its own results."""
    main(["new", "exp", "remote"])
    exp = campaign.experiments / "remote"
    stale = tmp_path / "m" / "run"
    stale.mkdir(parents=True)  # what a folder named after the run id alone would have left behind
    (stale / "metrics.jsonl").write_text('{"t": 0, "kind": "summary", "stale": 1}\n')
    (exp / "train.py").write_text("from lab import summary\nsummary(fresh=1.0)\n")
    monkeypatch.chdir(exp)
    main(["run", *ssh(tmp_path / "m")])
    assert campaign.run("r001").metrics == {"fresh": 1.0}
    assert [p.name for p in (tmp_path / "m").iterdir()] == ["run"]  # its own folder was removed once copied back
