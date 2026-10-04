"""`lab bench`: lm-evaluation-harness as a recorded run (the work happens in lab.bench_run)."""

from dataclasses import dataclass

from ..core import runs
from ..core.model import Run
from ..core.store import Campaign, Lab

EXPERIMENT = "bench"
# lm-eval extras needed per --model type.
EXTRAS = {
    "hf": "hf",
    "vllm": "vllm",
    "local-completions": "api",
    "local-chat-completions": "api",
    "openai-completions": "api",
    "openai-chat-completions": "api",
}


@dataclass(frozen=True)
class BenchRequest:
    model: str
    tasks: str
    model_type: str = "hf"
    model_args: str = ""
    limit: float | None = None
    num_fewshot: int | None = None
    extra: str = ""

    def command(self) -> list[str]:
        model_args = f"pretrained={self.model}" + (f",{self.model_args}" if self.model_args else "")
        return [
            "uv", "run", "--no-project", "--with", f"lm-eval[{EXTRAS.get(self.model_type, 'hf')}]",
            "python", "-m", "lab.bench_run",
            "--model", self.model_type, "--model-args", model_args, "--tasks", self.tasks,
            *(["--limit", str(self.limit)] if self.limit else []),
            *(["--num-fewshot", str(self.num_fewshot)] if self.num_fewshot is not None else []),
            *(["--extra", self.extra] if self.extra else []),
        ]  # fmt: skip


def run(
    lab: Lab,
    campaign: Campaign,
    request: BenchRequest,
    *,
    hypothesis: str = "",
    prediction: str = "",
    parent: str | None = None,
) -> Run:
    experiment = campaign.experiments / EXPERIMENT
    if not experiment.exists():
        experiment.mkdir(parents=True)
        (experiment / "README.md").write_text(
            "Runs created by `lab bench` (lm-evaluation-harness). Outputs land in each run.\n"
        )
    return runs.start(
        lab,
        campaign,
        runs.RunRequest(
            experiment=experiment,
            command=request.command(),
            hypothesis=hypothesis or f"Benchmark {request.model} on {request.tasks}",
            prediction=prediction,
            parent=parent,
            tags=("bench",),
        ),
    )
