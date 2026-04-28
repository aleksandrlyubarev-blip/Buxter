import pytest

from buxter.vision import ScriptExtractionError, extract_script


def test_extracts_fenced_python():
    text = "Sure:\n```python\nimport FreeCAD\nprint('ok')\n```\n"
    assert extract_script(text).strip() == "import FreeCAD\nprint('ok')"


def test_extracts_bare_fence():
    text = "```\nimport Part\n```"
    assert extract_script(text).strip() == "import Part"


def test_accepts_raw_python_without_fence():
    assert extract_script("import FreeCAD\nx = 1\n").strip() == "import FreeCAD\nx = 1"


def test_rejects_prose_only():
    with pytest.raises(ScriptExtractionError):
        extract_script("I cannot produce code right now.")


def test_picks_first_block_when_multiple():
    text = "```python\nA = 1\n```\nand\n```python\nB = 2\n```"
    assert extract_script(text).strip() == "A = 1"
