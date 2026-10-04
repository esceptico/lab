import json
import shlex

import pytest

from conftest import run
from lab.cli import build_parser, main
from lab.core import findings
from lab.core.campaigns import create_campaign
from lab.core.store import LabError
from lab.views import board, report


def payload(html: str) -> dict:
    return json.loads(
        html.split('<script type="application/json" id="data">', 1)[1].split("</script>", 1)[0].replace("<\\/", "</")
    )


def test_board_carries_the_comparison_policy(campaign, lab):
    run("train.py", "0.1")
    main(["verdict", "r001", "keep"])
    (campaign.experiments / "base" / "train.py").write_text(
        (campaign.experiments / "base" / "train.py").read_text().replace("1.0 / (step + 1)", "0.9 / (step + 1)")
    )
    run("train.py", "0.05")
    (campaign.findings).write_text("## What we believe now\n\n- Lower lr wins (r002 vs r001).\n")

    data = payload(board.render(lab, lab.root / "board"))
    c = data["campaigns"][0]
    first, second = c["runs"]
    assert c["best"] == "r001" and c["spent"] == pytest.approx(0.5)
    assert second["delta"] == pytest.approx(-0.05) and second["change"] == "better"
    assert first["bestSoFar"] == second["bestSoFar"] == pytest.approx(0.6)
    assert second["curve"]["key"] == "loss" and second["curve"]["x"] == [0, 1, 2]
    assert second["metrics"][c["metric"]] == second["value"]  # every logged number, for comparing any two runs
    rec = second["record"]  # the run page's evidence: where it lives, the files lab keeps, the raw record
    assert rec["dir"].endswith("runs/r002") and {f["name"] for f in rec["files"]} >= {"run.json"}
    assert '"id": "r002"' in rec["show"] and "Kept, baseline" in c["ls"] and c["updated"]
    assert "@@ train.py" in second["changes"]["diff"] and second["changes"]["command"][1].endswith("train.py 0.05")
    assert c["findings"] == [["Lower lr wins.", ["r002", "r001"]]]
    assert data["labels"]["keep"] == "Kept" and data["labels"]["none"] == "Not judged"


def test_board_renders_a_lab_without_runs(lab):
    create_campaign(lab, "empty")
    assert payload(board.render(lab, lab.root / "board"))["campaigns"][0]["runs"] == []


REPORT = """# Result

Larger lr wins (r002 vs r001), see **below**. r999 is not a run.

{{figure loss runs=r001,r002 labels="lr 0.1,lr 0.05" label="lr"}}

- one `code` item
"""


def test_report_links_runs_switches_figures_and_reproduces(campaign):
    run("train.py", "0.1")
    run("train.py", "0.05")
    main(["verdict", "r001", "revert", "-m", "too slow"])
    (campaign.root / "report.md").write_text(REPORT)
    html = report.render(campaign)
    data = payload(html)

    assert [o["label"] for o in data["figures"][0]["options"]] == ["lr 0.1", "lr 0.05"]
    assert set(data["runs"]) == {"r001", "r002"}  # only what the page cites or plots
    assert '<a class="ref" data-run="r002">r002</a>' in html and 'data-run="r999"' not in html
    assert "<strong>below</strong>" in html and "<code>code</code>" in html
    assert "<h2>Result</h2>" in html and "too slow" in html
    for line in html.split("<h2>Reproduce</h2>", 1)[1].split("<code>")[1].split("</code>")[0].splitlines():
        build_parser().parse_args(shlex.split(line)[1:])  # every printed command is valid


def test_report_without_report_md_shows_findings_and_the_baseline(campaign):
    run("train.py")
    main(["verdict", "r001", "keep"])
    campaign.findings.write_text("## Next\n- Try a lower lr.\n\n## What we believe now\n- It trains (r001).\n")
    toml = campaign.root / "campaign.toml"
    toml.write_text(toml.read_text() + "target = 0.5\n")
    body = report.default_report(campaign, {r.id: r for r in campaign.runs()})
    assert body.startswith("## Result\n\n**0.600** val_loss (r001) against the target 0.500: 0.100 short.")
    assert body.index("## Next") < body.index("## What we believe now")
    data = payload(report.render(campaign))
    assert data["figures"][0]["options"][0]["run"] == "r001"


def test_report_names_the_figures_that_exist(campaign):
    run("train.py")
    (campaign.root / "report.md").write_text("{{figure nope runs=r001}}\n")
    with pytest.raises(LabError, match="it has: loss"):
        report.render(campaign)


def test_findings_keep_text_and_cite_runs(tmp_path):
    path = tmp_path / "findings.md"
    path.write_text("## What we believe now\n- A holds (r003).\n- B, see r004 and r005.\n## Other\n- ignored r001\n")
    assert [(f.text, f.refs) for f in findings.read(path)] == [
        ("A holds.", ("r003",)),
        ("B, see r004 and r005.", ("r004", "r005")),
    ]


def test_board_findings_render_markdown_and_cite_each_run_once(campaign):
    run("train.py")
    campaign.findings.write_text("## What we believe now\n- **0.6** with `lr=0.1` (r001), again r001, <b>raw</b>\n")
    ((text, refs),) = board.campaign_data(campaign, campaign.root)["findings"]
    assert "<strong>0.6</strong>" in text and "<code>lr=0.1</code>" in text and "&lt;b&gt;" in text
    assert refs == ["r001"]


def test_record_text_cannot_end_the_page_data(campaign, lab):
    run("train.py", hypothesis="<!--<script> </script>")
    html = board.render(lab, lab.root / "board")
    data = html[html.index('id="data">') : html.index("</script>", html.index('id="data">'))]
    assert "<" not in data[len('id="data">') :]
