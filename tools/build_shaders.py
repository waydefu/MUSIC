"""把 GLSL 著色器編譯成 Qt 的 .qsb 格式。

Qt 6 的 ShaderEffect 不吃原始 GLSL —— 它要的是 qsb 容器，裡面同時包著
SPIR-V 以及轉譯後的 HLSL / MSL / 各版本 GLSL，執行期再依實際後端挑用。
Windows 上 Qt 預設走 Direct3D 11，所以 HLSL 是必要的目標。

編譯器是 PySide6 自帶的 ``pyside6-qsb``，不需要額外安裝 Qt SDK。

用法::

    .venv\\Scripts\\python.exe tools\\build_shaders.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHADER_DIR = ROOT / "src" / "aurora" / "qml" / "Aurora" / "shaders"

#: 轉譯目標。涵蓋 D3D11(HLSL 5.0)、Metal、以及桌面與行動的 GLSL 版本。
TARGETS = [
    "--glsl",
    "100es,120,150",
    "--hlsl",
    "50",
    "--msl",
    "12",
]


def qsb_executable() -> Path | None:
    candidate = Path(sys.executable).parent / "pyside6-qsb.exe"
    if candidate.exists():
        return candidate
    candidate = Path(sys.executable).parent / "pyside6-qsb"
    return candidate if candidate.exists() else None


def main() -> int:
    qsb = qsb_executable()
    if qsb is None:
        print("pyside6-qsb was not found in the active Python environment.")
        return 1

    sources = sorted(SHADER_DIR.glob("*.frag")) + sorted(SHADER_DIR.glob("*.vert"))
    if not sources:
        print(f"No shader sources found in {SHADER_DIR}")
        return 1

    failures = 0
    for source in sources:
        target = source.with_suffix(source.suffix + ".qsb")
        result = subprocess.run(
            [str(qsb), *TARGETS, "-o", str(target), str(source)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            failures += 1
            print(f"  [error] {source.name}")
            print((result.stderr or result.stdout).strip())
            continue
        print(f"  [ok] {source.name} -> {target.name}  ({target.stat().st_size} bytes)")

    if failures:
        print(f"\n{failures} shader compilation(s) failed")
        return 1
    print(f"\nCompiled {len(sources)} shader(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
