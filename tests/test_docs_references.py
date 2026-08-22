"""守住 agent 文件裡的路徑引用不會爛掉。

這個倉庫沒有 CI，也沒有 Markdown lint。AGENTS.md / CLAUDE.md / SKILL.md 的
價值完全建立在「它指的檔案真的在那裡」之上 —— 指錯的路徑比沒有文件更糟，
因為 agent 會照著找、找不到、然後自己編一個。

實際發生過：``core/constants.py`` 的 docstring 指向從來不存在的
``qml/Palette.qml``。這個測試就是用來擋這一類的。

檢查三件事：

1. Markdown 連結的目標檔案存在。
2. 行內程式碼裡的倉庫路徑（``src/``、``tests/``… 開頭）存在。
3. 每個 Skill 都有合法的 frontmatter，且 ``name`` 與資料夾同名。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: 掃描 Markdown 時要跳過的目錄：版控、虛擬環境、建置產物與工具快取。
#:
#: 工具快取那三個不是為了效能，是為了讓綠燈的意義穩定 —— ``.pytest_cache/``
#: 裡有一個 ``README.md``，不排除的話「收集到幾個測試」會取決於 pytest
#: 之前跑過沒有（本機 24 個、乾淨的 CI runner 22 個）。數量會飄的測試套件
#: 會讓人分不清「新文件沒被收進去」和「快取還沒建立」。
#: ``.mypy_cache/`` 與 ``.ruff_cache/`` 目前不含 Markdown，一併列上是因為
#: 它們同屬一類，將來多出一個 README 不該讓這個坑重演。
_SKIPPED_DIRS = (
    ".git/",
    ".venv/",
    "dist/",
    "build/",
    "node_modules/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
)

#: 只有這些前綴會被當成「倉庫內的路徑」。其餘（Windows 路徑、打包後的
#: ``_internal/``、外部網址）都不是這個測試該管的。
_REPO_PREFIXES = ("src/", "tests/", "tools/", "packaging/", "data/", ".claude/")

#: 產物與外部目錄：文件可以提到它們，但它們不保證存在。
_IGNORED_PREFIXES = (
    "tests/_generated",
    "dist/",
    "build/",
    "_internal/",
    ".venv/",
)

#: 路徑裡出現這些字元代表它是 glob、佔位符或外部 URL，不做存在性檢查。
_UNCHECKABLE = ("*", "<", ">", "%", "\\", "://", "$")

_MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_HTML_SRC = re.compile(r'<img[^>]+src="([^"]+)"')
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

_TRAILING = "。，、）)],.:;！？"


def markdown_files() -> list[Path]:
    """倉庫內所有需要檢查的 Markdown，排除產物與虛擬環境。"""
    found = []
    for path in ROOT.rglob("*.md"):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith(_SKIPPED_DIRS):
            continue
        found.append(path)
    return sorted(found)


def _checkable(target: str) -> bool:
    if not target or target.startswith(("#", "mailto:")):
        return False
    return not any(token in target for token in _UNCHECKABLE)


def link_targets(text: str) -> list[str]:
    """Markdown 連結與 ``<img src>`` 指向的本地路徑。"""
    raw = _MD_LINK.findall(text) + _HTML_SRC.findall(text)
    return [target.split("#", 1)[0] for target in raw if _checkable(target)]


def code_span_paths(text: str) -> list[str]:
    """行內程式碼裡看起來像倉庫路徑的 token。"""
    found = []
    for span in _CODE_SPAN.findall(text):
        for token in span.split():
            candidate = token.rstrip(_TRAILING)
            if not candidate.startswith(_REPO_PREFIXES):
                continue
            if candidate.startswith(_IGNORED_PREFIXES):
                continue
            if _checkable(candidate):
                found.append(candidate)
    return found


def _resolve(document: Path, target: str) -> bool:
    """路徑可以相對於文件本身，也可以相對於倉庫根目錄。"""
    return (document.parent / target).exists() or (ROOT / target).exists()


@pytest.mark.parametrize("document", markdown_files(), ids=lambda p: p.name)
def test_markdown_links_resolve(document: Path) -> None:
    broken = [
        target for target in link_targets(document.read_text(encoding="utf-8"))
        if not _resolve(document, target)
    ]
    assert not broken, f"{document.relative_to(ROOT)} 指向不存在的路徑：{broken}"


@pytest.mark.parametrize("document", markdown_files(), ids=lambda p: p.name)
def test_referenced_repository_paths_exist(document: Path) -> None:
    broken = [
        target for target in code_span_paths(document.read_text(encoding="utf-8"))
        if not _resolve(document, target)
    ]
    assert not broken, f"{document.relative_to(ROOT)} 提到不存在的倉庫路徑：{broken}"


def skill_files() -> list[Path]:
    return sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))


def test_skills_directory_is_not_empty() -> None:
    assert skill_files(), "找不到任何 SKILL.md —— 檢查是否搬動了 .claude/skills/"


@pytest.mark.parametrize("skill", skill_files(), ids=lambda p: p.parent.name)
def test_skill_frontmatter_is_valid(skill: Path) -> None:
    match = _FRONTMATTER.match(skill.read_text(encoding="utf-8"))
    assert match, f"{skill.parent.name} 缺少 --- 包起來的 frontmatter"

    fields = dict(
        (key.strip(), value.strip())
        for key, _, value in (line.partition(":") for line in match.group(1).splitlines())
        if key and not key.startswith(" ")
    )
    assert fields.get("name") == skill.parent.name, (
        f"{skill.parent.name} 的 name 欄位必須與資料夾同名，目前是 {fields.get('name')!r}"
    )
    assert len(fields.get("description", "")) >= 20, (
        f"{skill.parent.name} 的 description 太短，無法讓 agent 判斷何時該用它"
    )


# ------------------------------------------------------------ 抽取器本身的覆蓋


def test_extractors_flag_a_broken_link() -> None:
    text = "見 [架構](ARCHITECTURE.md) 與 [不存在](docs/nope.md)。"
    targets = link_targets(text)
    assert targets == ["ARCHITECTURE.md", "docs/nope.md"]
    assert not _resolve(ROOT / "README.md", "docs/nope.md")


def test_extractors_flag_a_broken_code_path() -> None:
    text = "改 `src/aurora/core/paths.py`，不是 `src/aurora/qml/Palette.qml`。"
    assert code_span_paths(text) == [
        "src/aurora/core/paths.py",
        "src/aurora/qml/Palette.qml",
    ]
    assert not _resolve(ROOT / "AGENTS.md", "src/aurora/qml/Palette.qml")


def test_extractors_skip_non_repository_paths() -> None:
    text = (
        r"設定在 `%APPDATA%\Aurora\config.json`，產物在 `dist/AURORA/AURORA.exe`，"
        "素材在 `tests/_generated/test.flac`，樣板是 `.claude/skills/<name>/SKILL.md`，"
        "著色器是 `shaders/*.frag`。"
    )
    assert code_span_paths(text) == []
    assert link_targets("見 <https://example.com> 與 [外部](https://example.com/a)") == []
