"""The frozen build's module list must not fall behind the source tree.

`build_common._HIDDEN_FRAMEDRAFT` is what both PyInstaller specs hand to
Analysis so a module reached only through a lazy or conditional import still
lands in the bundle. It is hand-maintained, and a module missing from it fails
*only* in the frozen app — never in the source tree, never in this suite —
which is the worst place to find out. `framedraft.fontpicker` was added to the
source and missed here; this is the check that would have caught it.
"""
import ast
import pathlib

SRC  = pathlib.Path(__file__).resolve().parents[1]
PKG  = SRC / "framedraft"

# Reached directly as the entry point (main.py imports framedraft.app), so it
# never needs declaring as a hidden import.
_ENTRY_POINTS = {"framedraft.app"}


def _hidden_framedraft() -> set[str]:
    """Parse the list out of build_common.py rather than importing it —
    importing pulls in PyInstaller, which is not a test dependency."""
    tree = ast.parse((SRC / "build_common.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and getattr(node.targets[0], "id", "") == "_HIDDEN_FRAMEDRAFT"):
            return {el.value for el in node.value.elts}
    raise AssertionError("_HIDDEN_FRAMEDRAFT not found in build_common.py")


def _modules_on_disk() -> set[str]:
    return {".".join(p.relative_to(SRC).with_suffix("").parts)
            for p in PKG.rglob("*.py") if p.name != "__init__.py"}


def test_every_framedraft_module_is_declared_for_the_bundle():
    missing = _modules_on_disk() - _hidden_framedraft() - _ENTRY_POINTS
    assert not missing, (
        "modules in framedraft/ that build_common._HIDDEN_FRAMEDRAFT does not "
        "declare: " + ", ".join(sorted(missing))
        + " — a lazy import of one of these is missing from the frozen build.")


def test_the_list_has_no_modules_that_no_longer_exist():
    """A renamed or deleted module left in the list makes PyInstaller fail the
    build outright, which at least is loud — but it is still stale."""
    stale = _hidden_framedraft() - _modules_on_disk()
    assert not stale, "declared but gone from framedraft/: " + ", ".join(sorted(stale))


def test_the_resources_directory_is_bundled_as_data():
    """framedraft/resources ships the BPI tint table. Its loader degrades to an
    empty list and hides the picker button when the file is unreadable, so a
    packaging miss would be silent in the frozen app."""
    text = (SRC / "build_common.py").read_text(encoding="utf-8")
    assert '("framedraft/resources", "framedraft/resources")' in text
    assert (PKG / "resources" / "bpi_tints.json").is_file()
