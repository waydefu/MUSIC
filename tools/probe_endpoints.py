"""把本機的輸出端點與藍牙推定結果印出來，用來人工比對實測值。

用法::

    .venv\\Scripts\\python.exe tools\\probe_endpoints.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aurora.core.btcodec import HostContext, default_table, resolve_codec
from aurora.platform_win.btregistry import radio_usb_vid, scan_bluetooth_devices
from aurora.platform_win.endpoint import query_endpoints
from aurora.platform_win.osinfo import windows_build


def main() -> int:
    table = default_table()
    vid = radio_usb_vid()
    radio = table.radio_for_vid(vid)
    build = windows_build()
    context = HostContext(build, radio)

    print("=" * 72)
    print(f"Windows build : {build}")
    print(f"藍牙晶片      : {radio.name}  (USB VID {vid:#06x})" if vid else "藍牙晶片      : 查無")
    host_codecs, reasons = table.host_codecs(context)
    print(f"本機支援編碼  : {'、'.join(host_codecs)}")
    for reason in reasons:
        print(f"                · {reason}")

    print("\n--- 已配對的藍牙裝置（來自註冊表）---")
    for device in scan_bluetooth_devices():
        company = f"{device.company_id:04X}" if device.company_id is not None else "無"
        print(f"  {device.mac}  {device.name:<28} 公司代碼={company}")

    snapshot = query_endpoints()

    print("\n--- 預設輸出端點 ---")
    if snapshot.default is None:
        print("  查不到預設輸出端點")
    else:
        _dump(snapshot.default, context, table)
        print(f"  同型號 HFP 端點也在線: {snapshot.hfp_also_connected}")

    print(f"\n--- 所有啟用中的輸出端點（{len(snapshot.active)} 個）---")
    for info in snapshot.active:
        codec = resolve_codec(info, context, table)
        device_fmt = info.device_format.describe() if info.device_format else "—"
        print(
            f"  {info.friendly_name:<38} enum={info.enumerator:<12} "
            f"{info.transport.value:<8} {device_fmt:<34} → {codec.name} {codec.confidence.badge}"
        )
    return 0


def _dump(info, context, table) -> None:  # type: ignore[no-untyped-def]
    print(f"  名稱      : {info.friendly_name}")
    print(f"  描述      : {info.description}")
    print(f"  enumerator: {info.enumerator}")
    print(f"  instance  : {info.instance_id}")
    print(f"  傳輸      : {info.transport.label}")
    print(f"  裝置格式  : {info.device_format.describe() if info.device_format else '—'}")
    print(f"  混音格式  : {info.mix_format.describe() if info.mix_format else '—'}")
    print(f"  公司代碼  : {f'{info.company_id:04X}' if info.company_id is not None else '—'}")
    codec = resolve_codec(info, context, table)
    print(f"  編碼      : {codec.name}  {codec.confidence.badge}")
    for reason in codec.reasons:
        print(f"              └ {reason}")


if __name__ == "__main__":
    raise SystemExit(main())
