"""docs/contract.json and the generated block in docs/tools.md match what the server serves.

On failure, regenerate both with `uv run --frozen --extra dev python scripts/contract.py --write` and review the
diff: it is the change a client will see (a description, a parameter, a schema, an annotation, a resource).
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from tests.inventory import ALL_TOOLS

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "contract.py"


def _contract_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("contract_script", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_contract_and_reference_match_the_server() -> None:
    contract = _contract_module()
    for path, text in contract.expected().items():
        assert path.read_text() == text, (
            f"{path.name} drifts from the server's contract; run: {contract.REGENERATE}"
        )


def test_contract_lists_every_tool_and_reaches_no_instance() -> None:
    contract = _contract_module()
    committed = json.loads(contract.CONTRACT.read_text())
    assert {t["name"] for t in committed["tools"]} == ALL_TOOLS
    text = contract.CONTRACT.read_text()
    assert (
        "contract.invalid" not in text
    )  # the placeholder instance never leaks into what clients see
    assert "service-now.com" not in text


def test_generated_block_is_replaced_not_appended() -> None:
    contract = _contract_module()
    block = contract.render_reference(json.loads(contract.CONTRACT.read_text()))
    doc = contract.TOOLS_MD.read_text()
    assert doc.count(contract.BEGIN) == 1 and doc.count(contract.END) == 1
    assert contract.with_reference(doc, block) == doc
