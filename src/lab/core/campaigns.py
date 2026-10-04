"""Creating campaigns and experiments."""

import shutil
from dataclasses import dataclass
from pathlib import Path

import tomlkit

from .model import ExperimentOrigin
from .runs import default_parent
from .snapshot import copy_code
from .store import RUN_ID, Campaign, Lab, LabError, valid_name

FINDINGS = """\
# {name}

Question: {question}

## Next

## What we believe now

## What we tried that did not work
"""

LOCKED_README = """\
Put data preparation and evaluation here. The first run hashes this folder; if it
changes later, runs after the change are marked as not comparable with runs before it,
until `lab lock --accept "why"` starts a new comparison epoch.
"""


def create_campaign(
    lab: Lab,
    name: str,
    *,
    question: str = "",
    metric: str = "val_loss",
    goal: str = "min",
    budget_usd: float | None = 25.0,
    target: float | None = None,
) -> Campaign:
    root = lab.campaigns_dir / valid_name(name, "campaign")
    if root.exists():
        raise LabError(f"campaign {name} already exists")
    for sub in ("locked", "experiments", "runs"):
        (root / sub).mkdir(parents=True)
    (root / "campaign.toml").write_text(campaign_toml(question, metric, goal, budget_usd, target))
    (root / "findings.md").write_text(FINDINGS.format(name=name, question=question or "(fill in)"))
    (root / "locked" / "README.md").write_text(LOCKED_README)
    return Campaign(root)


def campaign_toml(question: str, metric: str, goal: str, budget_usd: float | None, target: float | None = None) -> str:
    doc = tomlkit.document()
    doc.add(tomlkit.comment("What this campaign is trying to learn."))
    doc.add("question", question)
    doc.add(tomlkit.nl())
    doc.add(tomlkit.comment("The number runs are judged by, and which direction is better."))
    doc.add("metric", metric)
    doc.add("goal", goal)
    doc.add(tomlkit.comment("The value that answers the question, e.g. a published number to reproduce."))
    if target is None:
        doc.add(tomlkit.comment("target = 0.643"))
    else:
        doc.add("target", target)
    doc.add(tomlkit.nl())
    if budget_usd is not None:
        doc.add(tomlkit.comment("New runs do not start once this much has been spent (sum of cost_usd over runs)."))
        doc.add("budget_usd", budget_usd)
        doc.add(tomlkit.nl())
    doc.add(tomlkit.comment("Spread across seeds, once measured; deltas inside it read as inconclusive."))
    doc.add(tomlkit.comment("noise_floor = 0.004"))
    return tomlkit.dumps(doc)


BUILTIN_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"


@dataclass(frozen=True)
class Template:
    name: str
    path: Path
    custom: bool  # from the lab's templates/, overriding or adding to the built-in ones

    @property
    def summary(self) -> str:
        readme = self.path / "README.md"
        if not readme.exists():
            return ""
        paragraphs = (" ".join(p.split()) for p in readme.read_text().split("\n\n"))
        return next((p for p in paragraphs if p and not p.startswith("#")), "")


def templates(lab: Lab) -> list[Template]:
    found = {
        p.name: Template(p.name, p, False)
        for p in BUILTIN_TEMPLATES.iterdir()
        if p.is_dir() and not p.name.startswith("_")
    }
    if lab.templates.is_dir():
        found |= {p.name: Template(p.name, p, True) for p in lab.templates.iterdir() if p.is_dir()}
    return sorted(found.values(), key=lambda t: t.name)


def create_experiment(
    lab: Lab, campaign: Campaign, name: str, *, template: str | None = None, source: str | None = None
) -> Path:
    """A blank experiment, a copy of a template, or a branch of a run (its exact code) or of another experiment."""
    if template and source:
        raise LabError("choose --template or --from, not both")
    target = campaign.experiments / valid_name(name, "experiment")
    if target.exists():
        raise LabError(f"experiment {name} already exists")
    if template:
        found = next((t for t in templates(lab) if t.name == template), None)
        if found is None:
            raise LabError(f"no template {template!r}; `lab templates` lists them")
        copy_code(found.path, target)
        origin = ExperimentOrigin(source=f"template:{template}")
    elif source and RUN_ID.match(source):
        run_dir = campaign.run_dir(campaign.run(source).id)  # a clear error for a run that does not exist
        if (run_dir / "code").is_dir():
            shutil.copytree(run_dir / "code", target)
        else:  # a run of an empty experiment has no code to copy
            target.mkdir(parents=True)
        origin = ExperimentOrigin(parent=source, source=source)
    elif source:
        copy_code(campaign.experiment(source), target)
        origin = ExperimentOrigin(parent=default_parent(campaign, campaign.experiment(source)), source=source)
    else:
        target.mkdir(parents=True)
        origin = ExperimentOrigin()
    campaign.save_origin(target, origin)
    return target
