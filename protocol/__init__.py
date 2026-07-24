"""Protocol package for StateBus."""

from __future__ import annotations

import os

# The host ships libprotoc 3.6.x while Python uses protobuf 6.x.
# Force the pure-Python runtime so generated pb2 files remain importable.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
