import json
from pathlib import Path

_APL_DIR = Path(__file__).resolve().parent.parent / "apl_documents"


def load_apl_document(name: str = "bus_arrival") -> dict:
    path = _APL_DIR / f"{name}.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)
