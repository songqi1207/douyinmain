"""Windows desktop bridge for importing draft_key JSON into JianYing."""

from .core import (
    BridgeError,
    detect_draft_roots,
    detect_jianying_executables,
    extract_draft_key,
    import_draft_payload,
)

__all__ = [
    "BridgeError",
    "detect_draft_roots",
    "detect_jianying_executables",
    "extract_draft_key",
    "import_draft_payload",
]
