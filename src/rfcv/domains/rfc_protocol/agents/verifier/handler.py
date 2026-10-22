"""Handler của Verifier: phản biện không tạo bằng chứng; hub đọc `Critique` thẳng từ đầu ra của agent."""

from __future__ import annotations

from typing import Any


class NoopHandler:
    """CRITIQUE."""

    async def handle(self, *args: Any) -> int:
        return 0
