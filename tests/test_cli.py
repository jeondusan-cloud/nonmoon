import shutil
from pathlib import Path

import pytest

from nonmoon import cli

FIXTURE = Path(__file__).parent / "fixtures" / "sample"


def test_slug_for():
    assert cli.slug_for(Path("Do et al. 2008 (PRA).pdf")) == "do-et-al-2008-pra"
    assert cli.slug_for(Path("루비듐 냉각.pdf")) == "루비듐-냉각"
    assert cli.slug_for(Path("___.pdf")) == "paper"


def test_render_and_check_fixture(tmp_path, paper, capsys):
    work = tmp_path / "sample"
    shutil.copytree(FIXTURE, work)
    shutil.copy(paper, work / "source.pdf")
    out = tmp_path / "out.html"
    assert cli.main(["render", str(work), "-o", str(out)]) == 0
    assert out.is_file() and (work / "figures" / "fig1.png").is_file()
    assert cli.main(["render", str(work), "-o", str(tmp_path / "a.html"), "--artifact"]) == 0
    code = cli.main(["check", str(work)])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert "수식" in printed


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node for the KaTeX check")
def test_check_reports_broken_math(tmp_path, capsys):
    work = tmp_path / "bad"
    shutil.copytree(FIXTURE, work)
    text = (work / "book.yaml").read_text(encoding="utf-8")
    (work / "book.yaml").write_text(text.replace("\\frac{\\nu_0}{c}", "\\frac{\\nu_0}{c"), encoding="utf-8")
    assert cli.main(["check", str(work)]) == 1
    assert "수식 오류" in capsys.readouterr().out


def test_build_dry_run_prepares_only(tmp_path, paper, capsys):
    work = tmp_path / "w"
    assert cli.main(["build", str(paper), "--work", str(work), "--dry-run"]) == 0
    assert (work / "source.pdf").is_file() and not (work / "api").exists()


def test_profile_drops_headings_and_comments(tmp_path):
    f = tmp_path / "me.md"
    f.write_text("# 독자\n\n<!-- 나만 보는\n메모 -->\n- 리드베리 원자를 공부한다.\n", encoding="utf-8")
    assert cli.read_profile(str(f)) == "- 리드베리 원자를 공부한다."
