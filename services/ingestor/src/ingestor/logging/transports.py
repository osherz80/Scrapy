"""Console delivery. Future provider SDKs belong behind the Transport contract."""

import json
import sys
from collections.abc import Mapping
from typing import TextIO


class ConsoleTransport:
    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = sys.stderr if stream is None else stream

    def write(self, record: Mapping[str, object]) -> None:
        self._stream.write(json.dumps(dict(record), ensure_ascii=False, allow_nan=False) + "\n")

    def flush(self) -> None:
        self._stream.flush()
