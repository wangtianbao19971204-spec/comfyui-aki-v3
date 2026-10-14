"""Load the immutable dependency in a host-local namespace; see UPSTREAM.json."""
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "upstream/stocking"
__path__.append(str(SOURCE_ROOT))
