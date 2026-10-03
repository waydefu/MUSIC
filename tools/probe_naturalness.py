"""離線自然感候選準備；不開裝置、不改產品設定、不替主觀聽感評分。

所有效果臂保留 limiter，以同一固定輸入衰減反覆渲染直到無 gain reduction。
這是排除限幅影響的診斷條件，不是原音量產品行為的重現。FFmpeg loudnorm
只取 input 量測、輸出丟到 null；聽測 WAV 僅套整段固定衰減。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import random
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import miniaudio
import numpy as np
import numpy.typing as npt

from aurora.core.constants import (
    REFLECTION_HRTF_TAPS,
    REFLECTION_KERNEL_TAPS,
    REFLECTION_LEVEL,
    REFLECTION_TAP_MS,
    SPATIAL_DEPTH_DB,
    SPATIAL_FFT_SIZE,
)
from aurora.core.dsp_graph import AudioProcessor, DspGraph
from aurora.core.dynamics import Limiter, OutputMeter
from aurora.core.hrtf import SYNTHETIC_PROFILE, resolve_profile
from aurora.core.rates import scaled_fft_size, scaled_taps
from aurora.core.reflections import EarlyReflections
from aurora.core.spatial import SpatialUpmix

Audio = npt.NDArray[np.float32]
ROOT = Path(__file__).resolve().parents[1]
PROVENANCE_FILES = (
    "src/aurora/core/constants.py",
    "src/aurora/core/dsp_graph.py",
    "src/aurora/core/spatial.py",
    "src/aurora/core/reflections.py",
    "src/aurora/core/dynamics.py",
    "src/aurora/core/hrtf.py",
    "src/aurora/core/rates.py",
    "src/aurora/core/paths.py",
    "tools/probe_naturalness.py",
)


@dataclass(frozen=True)
class Arm:
    name: str
    spatial_amount: float = 0.0
    reflection_amount: float = 0.0
    depth_db: float = SPATIAL_DEPTH_DB
    reflection_scale: float = 1.0


ARMS = (
    Arm("dry"),
    Arm("current_full_50", 0.5, 0.5),
    Arm("current_full_55", 0.55, 0.55),
    Arm("current_full_60", 0.6, 0.6),
    Arm("current_full_75", 0.75, 0.75),
    Arm("current_full_100", 1.0, 1.0),
    Arm("spatial_100_without_reflections", 1.0, 0.0),
    Arm("reflections_only_100", 0.0, 1.0),
    Arm("full_100_no_depth", 1.0, 1.0, depth_db=0.0),
    Arm("full_100_half_reflections", 1.0, 1.0, reflection_scale=0.5),
)


def validate_audio(samples: Audio) -> None:
    if samples.ndim != 2 or samples.shape[1] != 2 or not samples.size:
        raise ValueError("需要非空 frames × 2 立體聲 PCM")
    if samples.dtype != np.float32 or not np.all(np.isfinite(samples)):
        raise ValueError("PCM 必須是有限 float32")


def constant_attenuate(samples: Audio, gain_db: float) -> Audio:
    validate_audio(samples)
    if not math.isfinite(gain_db) or gain_db > 0:
        raise ValueError("聽測只允許有限的整段固定衰減")
    output = np.asarray(samples * (10 ** (gain_db / 20)), dtype=np.float32)
    if not np.all(np.isfinite(output)) or np.any(np.abs(output) >= 1):
        raise ValueError("固定增益輸出有非有限值或達到滿刻度，拒絕匯出")
    return output


def explicit_profile(profile: str) -> dict[str, Any]:
    """產品會 fallback；探針須拒絕，免得將假 profile 當實測資料。"""
    if not profile:
        raise ValueError("必須明確選 synthetic 或已存在的 HRTF profile")
    if profile == SYNTHETIC_PROFILE:
        return {"requested": profile, "effective": profile, "sha256": None}
    path = resolve_profile(profile)
    if path is None or not path.is_file():
        raise ValueError(f"指定 HRTF profile 不存在：{profile}")
    return {"requested": profile, "effective": profile, "path": str(path), "sha256": sha(path)}


class ObservedLimiter(Limiter):
    """工具限定的 observer；每個內部分塊完成後記錄實際套用 gain。"""

    def __init__(self) -> None:
        super().__init__()
        self.minimum_gain = 1.0
        self.reduced_frames = 0

    def _process_chunk(self, view: Audio) -> None:
        super()._process_chunk(view)
        # private API 與 core hashes 一起記錄；升版時測試會守形狀。
        gains = self._gain_work[: len(view)]
        if gains.shape != (len(view),) or not np.all(np.isfinite(gains)):
            raise RuntimeError("Limiter observer 與當前內部 API 不相容")
        self.minimum_gain = min(self.minimum_gain, float(gains.min()))
        self.reduced_frames += int(np.count_nonzero(gains < 1.0 - 1e-12))


@dataclass
class Rendered:
    samples: Audio
    diagnostics: dict[str, Any]


def render_arm(
    samples: Audio,
    arm: Arm,
    *,
    rate: int,
    profile: str,
    block_frames: int = 2880,
    flush_seconds: float = 0.5,
) -> Rendered:
    """新 graph、新歷史、區塊串流；輸出含 latency 沖刷後的有限尾巴。"""
    validate_audio(samples)
    if rate <= 0 or block_frames <= 0 or not math.isfinite(flush_seconds):
        raise ValueError("rate／block 必須正值，flush 必須有限")
    if flush_seconds < 0.5:
        raise ValueError("至少沖刷 0.5 秒；不能把 reflection tail 當成 latency")
    explicit_profile(profile)
    graph = DspGraph()
    graph.prepare(rate, 2, block_frames)
    stages: list[AudioProcessor] = []
    spatial = None
    reflections = None
    if arm.spatial_amount > 0:
        spatial = SpatialUpmix()
        spatial.amount = arm.spatial_amount
        spatial.binaural = True
        spatial.hrtf_profile = profile
        spatial.cue_strength = 1.0
        spatial.depth_db = arm.depth_db
        stages.append(spatial)
    if arm.reflection_amount > 0:
        reflections = EarlyReflections()
        reflections.amount = arm.reflection_amount
        reflections.level = REFLECTION_LEVEL * arm.reflection_scale
        reflections.binaural = True
        reflections.hrtf_profile = profile
        reflections.cue_strength = 1.0
        stages.append(reflections)
    limiter = None
    if stages:
        limiter = ObservedLimiter()
        stages.extend((limiter, OutputMeter()))
    graph.set_stages(tuple(stages))
    if profile != SYNTHETIC_PROFILE:
        for stage in (spatial, reflections):
            if stage is not None and not stage.hrtf_is_measured:
                raise ValueError(f"指定 profile 載入失敗，拒絕 synthetic fallback：{profile}")

    latency = graph.latency_frames
    reflection_tail = (
        math.ceil(max(REFLECTION_TAP_MS) * rate / 1000)
        + max(scaled_taps(REFLECTION_HRTF_TAPS, rate), scaled_taps(REFLECTION_KERNEL_TAPS, rate))
        - 1
        if reflections is not None
        else 0
    )
    spatial_tail = scaled_fft_size(SPATIAL_FFT_SIZE, rate) if spatial is not None else 0
    tail = max(math.ceil(flush_seconds * rate), reflection_tail + spatial_tail)
    flush = latency + tail
    output = np.pad(samples, ((0, flush), (0, 0)))
    started = time.perf_counter()
    calls = 0
    for start in range(0, len(output), block_frames):
        graph.process(output[start : start + block_frames].reshape(-1))
        calls += 1
        if graph.degraded:
            raise RuntimeError(f"DSP 降級，探針停止：{graph.degradation_reason}")
    elapsed = time.perf_counter() - started
    validate_audio(output)
    # STFT 的宣報延遲已補償；不把冷啟動暫態當成原曲段落。
    aligned = output[latency : latency + len(samples) + tail].copy()
    last_peak = float(np.abs(aligned[-min(rate // 10, tail) :]).max())
    if last_peak > 1e-7:
        raise RuntimeError("沖刷尾端尚未回到靜音；增加 flush_seconds")
    return Rendered(
        aligned,
        {
            "arm": asdict(arm),
            "limiter_present": limiter is not None,
            "limiter_engaged_frames": limiter.engaged_frames if limiter else 0,
            "limiter_reduced_frames_including_context_tail": limiter.reduced_frames
            if limiter
            else 0,
            "minimum_limiter_gain": limiter.minimum_gain if limiter else 1.0,
            "effective_spatial_profile": profile if spatial else None,
            "effective_reflection_profile": profile if reflections else None,
            "cue_strength": 1.0,
            "spatial_binaural": spatial.binaural if spatial else None,
            "reflection_binaural": reflections.binaural if reflections else None,
            "spatial_surround_level": spatial.surround_level if spatial else None,
            "spatial_width": spatial.width if spatial else None,
            "reflection_level": reflections.level if reflections else None,
            "eq": "flat; omitted no-op stage",
            "product_user_volume_applied": False,
            "product_user_gain": 1.0,
            "stage_types": [type(stage).__name__ for stage in stages],
            "latency_frames": latency,
            "flush_frames": flush,
            "reflection_tail_bound_frames": reflection_tail,
            "aligned_tail_frames": tail,
            "rendered_frames": len(output),
            "last_100ms_peak": last_peak,
            "block_frames": block_frames,
            "process_calls": calls,
            "offline_process_elapsed_s": elapsed,
            "timing_is_authoritative_device_performance": False,
            "spatial_label_note": "upmix/depth/HRTF retained; not HRTF-only",
        },
    )


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def decode_context(
    path: Path,
    *,
    start: float,
    seconds: float,
    rate: int,
    preroll: float,
    postroll: float = 0.0,
    grid_frames: int = 1,
) -> tuple[Audio, int, dict[str, Any]]:
    if not path.is_file():
        raise ValueError("來源檔案不存在")
    if not all(math.isfinite(value) for value in (start, seconds, preroll, postroll)):
        raise ValueError("段落秒數必須有限")
    if start < 0 or seconds <= 0 or rate <= 0 or preroll < 2.0 or postroll < 0:
        raise ValueError("start>=0、seconds/rate>0、preroll>=2、postroll>=0 秒")
    if not isinstance(grid_frames, int) or grid_frames <= 0:
        raise ValueError("context grid 必須是正整數 frames")
    start_frame = round(start * rate)
    desired_frames = round(seconds * rate)
    raw_context_start = max(0, start_frame - math.ceil(preroll * rate))
    # 必須沿用由曲首0開始的STFT窗格。任意截段起點會改掉所有後續視窗，
    # 即使暖機2/4秒充分，仍是不同的非線性處理，而不是相同狀態的比較。
    context_start = raw_context_start - raw_context_start % grid_frames
    before = start_frame - context_start
    required = before + desired_frames
    if desired_frames <= 0:
        raise ValueError("段落必須至少一個 sample frame")
    requested_post = math.ceil(postroll * rate)
    wanted = required + requested_post
    source = miniaudio.stream_file(
        str(path),
        output_format=miniaudio.SampleFormat.FLOAT32,
        nchannels=2,
        sample_rate=rate,
        frames_to_read=4096,
        seek_frame=context_start,
    )
    chunks: list[Audio] = []
    received = 0
    # miniaudio 1.71 的 stream_file 已先吃掉 dummy yield；再 next 會丟掉
    # 第一批真正的 PCM（4096 frames），使 source 時間與交付 WAV 全部錯位。
    try:
        while received < wanted:
            try:
                frame = source.send(min(4096, wanted - received))
            except StopIteration:
                break
            decoded = np.frombuffer(frame, dtype=np.float32).copy().reshape(-1, 2)
            if not len(decoded):
                break
            chunks.append(decoded)
            received += len(decoded)
    finally:
        source.close()
    if received < required:
        raise ValueError("來源長度不足；不以補零假裝存在真實音樂")
    actual_frames = min(received, wanted)
    samples = np.concatenate(chunks)[:actual_frames]
    validate_audio(samples)
    return (
        samples,
        before,
        {
            "source_start_frame": start_frame,
            "source_end_frame": start_frame + desired_frames,
            "decode_start_frame": context_start,
            "requested_raw_context_start_frame": raw_context_start,
            "context_grid_frames": grid_frames,
            "global_stft_origin_frame": 0,
            "alignment_extra_preroll_frames": raw_context_start - context_start,
            "real_preroll_frames": before,
            "real_preroll_seconds": before / rate,
            "short_preroll_at_track_start": before < 2 * rate,
            "decoded_frames": len(samples),
            "segment_frames": desired_frames,
            "requested_postroll_frames": requested_post,
            "real_postroll_frames": actual_frames - required,
            "real_postroll_seconds": (actual_frames - required) / rate,
            "shortened_postroll_at_source_eof": actual_frames < wanted,
            "decode_requested_end_frame": context_start + wanted,
            "decode_actual_end_frame": context_start + actual_frames,
            "seek_frame_units": "decoded output sample rate",
        },
    )


def sample_levels(samples: Audio) -> dict[str, float]:
    validate_audio(samples)
    peak = float(np.abs(samples).max())
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return {
        "sample_peak_dbfs": 20 * math.log10(max(peak, 1e-30)),
        "rms_dbfs": 20 * math.log10(max(rms, 1e-30)),
    }


def measure_loudness(samples: Audio, rate: int) -> dict[str, float]:
    validate_audio(samples)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-f",
            "f32le",
            "-ar",
            str(rate),
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-af",
            "loudnorm=I=-23:TP=-2:LRA=50:print_format=json",
            "-f",
            "null",
            "-",
        ],
        input=samples.astype("<f4", copy=False).tobytes(),
        capture_output=True,
        check=True,
        timeout=120,
    )
    stderr = result.stderr.decode("utf-8", errors="replace")
    raw, _ = json.JSONDecoder().raw_decode(stderr[stderr.rfind("{") :])
    metrics = {
        "integrated_lufs": float(raw["input_i"]),
        "true_peak_dbtp": float(raw["input_tp"]),
        **sample_levels(samples),
    }
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("靜音或無效 LUFS；不產生虛構的匹配增益")
    return metrics


def common_loudness_target(rows: list[dict[str, float]], ceiling_dbtp: float = -2.0) -> float:
    if not rows or not math.isfinite(ceiling_dbtp) or ceiling_dbtp > -2.0:
        raise ValueError("匯出 true-peak ceiling 必須 <= -2 dBTP")
    target = min(row["integrated_lufs"] for row in rows)
    for row in rows:
        if not all(math.isfinite(value) for value in row.values()):
            raise ValueError("量測值必須有限")
        target = min(target, row["integrated_lufs"] + ceiling_dbtp - row["true_peak_dbtp"])
    # loudnorm 回報只保留兩位；多留0.1 dB，不能卡在量測／量化邊界。
    return target - 0.1


def validate_delivered_loudness(rows: list[dict[str, float]], target: float) -> float:
    """逐檔容差不足以確保 pairwise 等響；必須再守整組的 spread。"""
    if not rows or not math.isfinite(target):
        raise ValueError("交付響度資料必須非空且有限")
    for row in rows:
        if not all(math.isfinite(row[key]) for key in ("integrated_lufs", "true_peak_dbtp")):
            raise ValueError("交付響度資料必須有限")
        if row["true_peak_dbtp"] > -2.0 or abs(row["integrated_lufs"] - target) > 0.1 + 1e-9:
            raise RuntimeError("交付 WAV 的 target／true-peak 回量未通過")
    loudness = [row["integrated_lufs"] for row in rows]
    spread = max(loudness) - min(loudness)
    if spread > 0.1 + 1e-9:
        raise RuntimeError("交付 24-bit WAV pairwise LUFS spread > 0.1")
    return spread


def write_wav(samples: Audio, path: Path, rate: int) -> None:
    validate_audio(samples)
    if path.exists() or np.any(np.abs(samples) >= 1):
        raise ValueError("不覆蓋既有檔案，亦不輸出 clipping PCM")
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-f",
            "f32le",
            "-ar",
            str(rate),
            "-ac",
            "2",
            "-i",
            "pipe:0",
            "-c:a",
            "pcm_s24le",
            str(path),
        ],
        input=samples.astype("<f4", copy=False).tobytes(),
        capture_output=True,
        check=True,
        timeout=120,
    )


def git_provenance() -> dict[str, str]:
    prefix = ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT)]
    return {
        "head": subprocess.check_output([*prefix, "rev-parse", "HEAD"], text=True).strip(),
        "status_porcelain": subprocess.check_output(
            [*prefix, "status", "--porcelain"], text=True, encoding="utf-8"
        ),
    }


def source_media_info(path: Path) -> dict[str, Any]:
    result = subprocess.check_output(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(result)
    if not isinstance(payload, dict):
        raise ValueError("ffprobe 回傳格式不是 object")
    streams = payload.get("streams")
    if not isinstance(streams, list) or not streams:
        raise ValueError("來源沒有 audio stream")
    first = streams[0]
    if not isinstance(first, dict) or not all(isinstance(key, str) for key in first):
        raise ValueError("ffprobe audio stream metadata 格式無效")
    return dict(first)


def run(args: argparse.Namespace) -> Path:
    requested = Path(args.source).resolve()
    destination = Path(args.out).resolve()
    if destination.exists():
        raise ValueError("輸出資料夾必須尚未存在，避免覆蓋聽測證據")
    if not math.isfinite(args.pre_db) or args.pre_db > 0:
        raise ValueError("pre-db 必須是有限衰減")
    profile = explicit_profile(args.profile)
    source_hash = sha(requested)
    hashes_at_start = {name: sha(ROOT / name) for name in PROVENANCE_FILES}
    git_at_start = git_provenance()
    media_info = source_media_info(requested)
    decoded, before, context = decode_context(
        requested,
        start=args.start,
        seconds=args.seconds,
        rate=args.rate,
        preroll=args.preroll,
        postroll=args.postroll,
        grid_frames=scaled_fft_size(SPATIAL_FFT_SIZE, args.rate) // 2,
    )
    length = context["segment_frames"]
    original_segment = decoded[before : before + length]
    pre_db = args.pre_db
    trials: list[dict[str, Any]] = []
    renders: list[Rendered] = []
    for _ in range(9):
        source = constant_attenuate(decoded, pre_db)
        renders = [
            render_arm(
                source,
                arm,
                rate=args.rate,
                profile=args.profile,
                block_frames=args.block,
                flush_seconds=args.flush,
            )
            for arm in ARMS
        ]
        reduced = {
            item.diagnostics["arm"]["name"]: item.diagnostics[
                "limiter_reduced_frames_including_context_tail"
            ]
            for item in renders
        }
        trials.append({"common_input_attenuation_db": pre_db, "reduced_frames": reduced})
        if not any(reduced.values()):
            break
        pre_db -= 6.0
    else:
        raise RuntimeError("共同衰減重試仍有限幅器動作；不匯出候選")

    segments = [item.samples[before : before + length].copy() for item in renders]
    raw_metrics = [measure_loudness(samples, args.rate) for samples in segments]
    target = common_loudness_target(raw_metrics)
    gains = [min(0.0, target - row["integrated_lufs"]) for row in raw_metrics]
    exports = [
        constant_attenuate(samples, gain) for samples, gain in zip(segments, gains, strict=True)
    ]
    export_metrics = [measure_loudness(samples, args.rate) for samples in exports]
    if any(row["true_peak_dbtp"] > -2.0 for row in export_metrics):
        raise RuntimeError("固定增益後 true peak 超過 -2 dBTP；不匯出")
    if (
        max(row["integrated_lufs"] for row in export_metrics)
        - min(row["integrated_lufs"] for row in export_metrics)
        > 0.1 + 1e-9
    ):
        raise RuntimeError("固定增益後 LUFS spread > 0.1；不匯出")
    order = list(range(len(ARMS)))
    if args.seed is not None:
        random.Random(args.seed).shuffle(order)
    destination.mkdir(parents=True, exist_ok=False)
    answer_map: dict[str, str] = {}
    diagnostics = []
    for number, index in enumerate(order, start=1):
        name = f"sample_{number:02d}.wav" if args.seed is not None else f"{ARMS[index].name}.wav"
        path = destination / name
        write_wav(exports[index], path, args.rate)
        # 24-bit 量化之後再 decode／回量，不能只用浮點輸出推論交付 WAV。
        final, _, _ = decode_context(
            path, start=0, seconds=length / args.rate, rate=args.rate, preroll=2.0, postroll=0.0
        )
        measured = measure_loudness(final, args.rate)
        validate_delivered_loudness([measured], target)
        answer_map[name] = ARMS[index].name
        diagnostics.append(
            {
                **renders[index].diagnostics,
                "sample_file": name,
                "sample_sha256": sha(path),
                "raw_segment_levels": raw_metrics[index],
                "fixed_export_attenuation_db": gains[index],
                "float_export_levels": export_metrics[index],
                "delivered_wav_levels": measured,
            }
        )
    delivered_spread = validate_delivered_loudness(
        [row["delivered_wav_levels"] for row in diagnostics], target
    )
    if sha(requested) != source_hash:
        raise RuntimeError("來源 hash 在執行期間改變，結果無效")
    hashes_at_end = {name: sha(ROOT / name) for name in PROVENANCE_FILES}
    if hashes_at_end != hashes_at_start:
        raise RuntimeError("core／工具在渲染期間被修改；結果無效、不發布 manifest")
    if explicit_profile(args.profile) != profile:
        raise RuntimeError("HRTF profile 在渲染期間改變；結果無效")
    report = {
        "method": "gated loudnorm INPUT measurements; constant attenuation export only",
        "claim": "Offline diagnostic preparation; listening/device/release acceptance NOT_RUN",
        "limiter_control": (
            "effects retain limiter; common fixed preattenuation retried "
            "until actual gain reduction absent"
        ),
        "limiter_control_limit": (
            "Preattenuation changes DSP input amplitude; not original-level product replay"
        ),
        "source": str(requested),
        "source_sha256": source_hash,
        "source_media_info": media_info,
        "source_segment_levels": measure_loudness(original_segment, args.rate),
        "processing_rate": args.rate,
        "channels": 2,
        **context,
        "profile": profile,
        "git": git_provenance(),
        "git_at_start": git_at_start,
        "core_sha256": hashes_at_start,
        "core_sha256_at_end": hashes_at_end,
        "source_and_core_hashes_unchanged": True,
        "python_version": sys.version,
        "numpy_version": np.__version__,
        "miniaudio_version": importlib.metadata.version("miniaudio"),
        "ffmpeg_version": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[
            0
        ],
        "hardware_context": {
            "headphone": "Sony WH-1000XM4",
            "power": args.xm4_power,
            "anc": args.anc,
        },
        "common_input_attenuation_db": pre_db,
        "retry_trials": trials,
        "target_lufs": target,
        "delivered_pairwise_lufs_spread": delivered_spread,
        "export_true_peak_ceiling_dbtp": -2.0,
        "randomization_seed": args.seed,
        "arms": diagnostics,
        "limitations": [
            "No slider remap selected; current 50/55/60 retained as anchors.",
            "Spatial-without-reflections retains upmix/depth/makeup, not HRTF-only.",
            "Preroll starts from zero DSP history; verify 2s versus longer context convergence.",
            "Context decode start is floored to the global source STFT-hop grid.",
            "Real postroll precedes zero tail flushing; EOF-shortened context is explicit.",
            "No real device, QML, driver or authoritative callback performance measurement.",
        ],
    }
    (destination / "diagnostics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    (destination / "answer_map.json").write_text(
        json.dumps(answer_map, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "listener_manifest.json").write_text(
        json.dumps(
            {
                "samples": list(answer_map),
                "sample_rate": args.rate,
                "frames": length,
                "instruction": (
                    "Use fixed headphone power/ANC, flat EQ and spatial 0%; "
                    "rate thickness/clarity/naturalness separately."
                ),
                "listening_status": "NOT_RUN",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return destination / "diagnostics.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument(
        "--profile", required=True, help="explicit synthetic or installed named profile"
    )
    parser.add_argument("--rate", type=int, default=48000)
    parser.add_argument("--block", type=int, default=2880)
    parser.add_argument("--preroll", type=float, default=2.0)
    parser.add_argument("--postroll", type=float, default=2.0)
    parser.add_argument("--flush", type=float, default=0.5)
    parser.add_argument("--pre-db", type=float, default=-12.0)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--xm4-power", choices=("unknown", "on", "off"), default="unknown")
    parser.add_argument("--anc", choices=("unknown", "on", "off", "ambient"), default="unknown")
    args = parser.parse_args()
    try:
        print(run(args))
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"probe failed: {exc}\n")


if __name__ == "__main__":
    main()
