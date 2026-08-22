"""macOS adapter 的跨平台行為測試。

原生 reader 以 private seam 取代，讓 Windows CI 也能守住 macOS 的語意與
降級契約，而不需要載入 AppKit 或 Core Audio。
"""

from __future__ import annotations

import sys

import pytest

import aurora.platform as platform
from aurora.core.btcodec import default_table
from aurora.core.models import AudioFormat, EndpointInfo, TransportKind
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


def _endpoint(identifier: str, name: str) -> EndpointInfo:
    return EndpointInfo(
        id=identifier,
        friendly_name=name,
        description="Apple Inc.",
        enumerator="bltn",
        instance_id="",
        transport=TransportKind.WIRED,
        device_format=AudioFormat(48000, 2, 24),
        mix_format=AudioFormat(48000, 2, 32, is_float=True),
    )


def test_query_endpoints_reuses_the_active_default_object(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MacOSAdapter()
    other = _endpoint("other-uid", "Other Output")
    selected = _endpoint("selected-uid", "Selected Output")
    monkeypatch.setattr(adapter, "_query_coreaudio", lambda: (selected.id, (other, selected)))

    snapshot = adapter.query_endpoints()

    assert snapshot.active == (other, selected)
    assert snapshot.default is selected
    assert snapshot.default is snapshot.active[1]


def test_query_endpoints_does_not_invent_a_missing_default(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MacOSAdapter()
    active = _endpoint("active-uid", "Active Output")
    monkeypatch.setattr(adapter, "_query_coreaudio", lambda: ("removed-uid", (active,)))

    snapshot = adapter.query_endpoints()

    assert snapshot.default is None
    assert snapshot.active == (active,)


def test_query_endpoints_falls_back_to_an_empty_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = MacOSAdapter()

    def raise_coreaudio_error() -> tuple[str | None, tuple[EndpointInfo, ...]]:
        raise OSError("Core Audio unavailable")

    monkeypatch.setattr(adapter, "_query_coreaudio", raise_coreaudio_error)

    snapshot = adapter.query_endpoints()

    assert snapshot.default is None
    assert snapshot.active == ()


def test_macos_keeps_unimplemented_capabilities_at_null_adapter_defaults() -> None:
    adapter = MacOSAdapter()

    assert adapter.host_context(default_table()).windows_build == 0
    assert adapter.register_file_types() is False
    assert adapter.unregister_file_types() is False
    assert adapter.is_registered() is False
    assert adapter.open_default_apps_settings() is False


@pytest.mark.parametrize(
    ("enumerator", "name", "device_format", "mix_format", "expected"),
    (
        ("blue", "Headphones Hands-Free", None, None, TransportKind.BLUETOOTH_HFP),
        (
            "blue",
            "Headphones",
            AudioFormat(48000, 2, 24),
            AudioFormat(16000, 1, 16),
            TransportKind.BLUETOOTH_HFP,
        ),
        (
            "blue",
            "Headphones",
            AudioFormat(48000, 2, 24),
            AudioFormat(48000, 2, 32, is_float=True),
            TransportKind.BLUETOOTH_A2DP,
        ),
        ("blea", "LE headphones", None, None, TransportKind.UNKNOWN),
        ("airp", "AirPlay", None, None, TransportKind.UNKNOWN),
        ("virt", "Virtual device", None, None, TransportKind.UNKNOWN),
        ("grup", "Aggregate device", None, None, TransportKind.UNKNOWN),
        ("bltn", "Mac speakers", None, None, TransportKind.WIRED),
    ),
)
def test_macos_classifies_coreaudio_transport_conservatively(
    enumerator: str,
    name: str,
    device_format: AudioFormat | None,
    mix_format: AudioFormat | None,
    expected: TransportKind,
) -> None:
    assert MacOSAdapter._classify_transport(enumerator, name, device_format, mix_format) is expected


def test_platform_selector_uses_macos_adapter_on_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform.sys, "platform", "darwin")
    platform.reset_cache()
    try:
        assert isinstance(platform.adapter(), MacOSAdapter)
    finally:
        platform.reset_cache()


@pytest.mark.skipif(sys.platform != "darwin", reason="Core Audio is only available on macOS")
def test_coreaudio_snapshot_is_coherent_on_a_real_macos_host() -> None:
    """沒有輸出端點的 hosted runner 應 skip，不把環境限制誤報成產品故障。"""
    adapter = MacOSAdapter()
    # 直接呼叫 native reader：若 ctypes bridge 壞掉，不能被 public fallback
    # 偽裝成「沒有裝置」而 skip。
    default_id, active = adapter._query_coreaudio()
    if default_id is None:
        pytest.skip("Core Audio did not expose a default output endpoint")

    default = next(item for item in active if item.id == default_id)
    snapshot = adapter.query_endpoints()
    assert snapshot.default is not None
    assert any(snapshot.default is item for item in snapshot.active)
    assert default.id == default_id
    assert snapshot.default.id
    assert snapshot.default.friendly_name
    for endpoint in snapshot.active:
        assert endpoint.id
        assert endpoint.friendly_name
        assert isinstance(endpoint.transport, TransportKind)
        for audio_format in (endpoint.device_format, endpoint.mix_format):
            if audio_format is not None:
                assert 4000 <= audio_format.sample_rate <= 768000
                assert 1 <= audio_format.channels <= 32
                assert 1 <= audio_format.bits_per_sample <= 64
