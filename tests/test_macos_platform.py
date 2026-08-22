"""macOS adapter 的跨平台行為測試。

原生 reader 以 private seam 取代，讓 Windows CI 也能守住 macOS 的語意與
降級契約，而不需要載入 AppKit 或 Core Audio。
"""

from __future__ import annotations

import pytest

from aurora.platform.macos import MacOSAdapter


@pytest.mark.parametrize(
    ("reduce_motion", "expected"),
    ((True, False), (False, True)),
)
def test_system_animations_inverts_reduce_motion(reduce_motion: bool, expected: bool) -> None:
    adapter = MacOSAdapter()
    adapter._read_reduce_motion = lambda: reduce_motion  # type: ignore[method-assign]

    assert adapter.system_animations_enabled() is expected


def test_system_animations_falls_back_when_native_reader_fails() -> None:
    adapter = MacOSAdapter()

    def raise_native_error() -> bool:
        raise OSError("AppKit unavailable")

    adapter._read_reduce_motion = raise_native_error  # type: ignore[method-assign]

    assert adapter.system_animations_enabled() is True
