from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.signal import find_peaks, savgol_filter


SIDES = ("left", "right")
SKELETON = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_hip", "left_knee"),
    ("left_knee", "left_ankle"),
    ("left_ankle", "left_heel"),
    ("left_ankle", "left_foot_index"),
    ("left_heel", "left_foot_index"),
    ("right_hip", "right_knee"),
    ("right_knee", "right_ankle"),
    ("right_ankle", "right_heel"),
    ("right_ankle", "right_foot_index"),
    ("right_heel", "right_foot_index"),
    ("left_shoulder", "left_elbow"),
    ("left_elbow", "left_wrist"),
    ("right_shoulder", "right_elbow"),
    ("right_elbow", "right_wrist"),
)


def smooth(values: np.ndarray, window: int = 21, order: int = 3) -> np.ndarray:
    values = pd.Series(values).interpolate(limit_direction="both").to_numpy(float)
    window = min(window, len(values) if len(values) % 2 else len(values) - 1)
    window = max(window, order + 2 + (order + 2) % 2)
    return savgol_filter(values, window, order)


def points(df: pd.DataFrame, name: str, space: str = "world") -> np.ndarray:
    return df[
        [
            f"{name}_x_{space}",
            f"{name}_y_{space}",
            f"{name}_z_{space}",
        ]
    ].to_numpy(float)


def joint_angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    ba = a - b
    bc = c - b
    denominator = np.linalg.norm(ba, axis=1) * np.linalg.norm(bc, axis=1)
    cosine = np.sum(ba * bc, axis=1) / np.maximum(denominator, 1e-9)
    return np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))


def derive_signals(df: pd.DataFrame, fps: float) -> dict[str, np.ndarray]:
    signals: dict[str, np.ndarray] = {}
    shoulder_width = np.abs(
        df["left_shoulder_x_pxnorm"] - df["right_shoulder_x_pxnorm"]
    ).to_numpy()
    hip_width = np.abs(
        df["left_hip_x_pxnorm"] - df["right_hip_x_pxnorm"]
    ).to_numpy()
    body_scale = smooth((shoulder_width + hip_width) / 2.0, 31)
    signals["body_scale"] = body_scale

    shoulder_x = (
        df["left_shoulder_x_pxnorm"] + df["right_shoulder_x_pxnorm"]
    ).to_numpy() / 2.0
    shoulder_y = (
        df["left_shoulder_y_pxnorm"] + df["right_shoulder_y_pxnorm"]
    ).to_numpy() / 2.0
    hip_x = (
        df["left_hip_x_pxnorm"] + df["right_hip_x_pxnorm"]
    ).to_numpy() / 2.0
    hip_y = (
        df["left_hip_y_pxnorm"] + df["right_hip_y_pxnorm"]
    ).to_numpy() / 2.0
    signals["trunk_lean_deg"] = smooth(
        np.degrees(np.arctan2(shoulder_x - hip_x, hip_y - shoulder_y)), 31
    )
    signals["pelvis_obliquity_deg"] = smooth(
        np.degrees(
            np.arctan2(
                (
                    df["right_hip_y_pxnorm"] - df["left_hip_y_pxnorm"]
                ).to_numpy(),
                np.maximum(hip_width, 1e-6),
            )
        ),
        31,
    )

    rolling_window = max(15, int(round(fps * 1.6)))
    for side in SIDES:
        knee_flexion = 180.0 - joint_angle(
            points(df, f"{side}_hip"),
            points(df, f"{side}_knee"),
            points(df, f"{side}_ankle"),
        )
        signals[f"{side}_knee_flexion_deg"] = smooth(knee_flexion, 21)

        leg_extension = (
            df[f"{side}_ankle_y_pxnorm"].to_numpy() - hip_y
        )
        extension_trend = (
            pd.Series(leg_extension)
            .rolling(rolling_window, center=True, min_periods=1)
            .median()
            .to_numpy()
        )
        signals[f"{side}_foot_clearance_proxy"] = smooth(
            (extension_trend - leg_extension) / np.maximum(body_scale, 1e-6), 15
        )
        signals[f"{side}_ankle_lateral_proxy"] = smooth(
            (
                df[f"{side}_ankle_x_pxnorm"].to_numpy()
                - df[f"{side}_hip_x_pxnorm"].to_numpy()
            )
            / np.maximum(body_scale, 1e-6),
            15,
        )
        wrist_x = (
            df[f"{side}_wrist_x_pxnorm"].to_numpy()
            - df[f"{side}_shoulder_x_pxnorm"].to_numpy()
        ) / np.maximum(body_scale, 1e-6)
        signals[f"{side}_wrist_swing_proxy"] = smooth(wrist_x, 15)

    return signals


def detect_passes(
    df: pd.DataFrame, body_scale: np.ndarray
) -> dict[str, tuple[float, float]]:
    time = df["time"].to_numpy()
    turn_time = float(time[int(np.argmin(body_scale))])
    return {
        "away": (max(float(time[0]) + 0.75, 0.75), turn_time - 1.5),
        "toward": (turn_time + 1.5, float(time[-1]) - 0.5),
    }


def detect_swing_peaks(
    time: np.ndarray,
    signal: np.ndarray,
    interval: tuple[float, float],
    fps: float,
) -> np.ndarray:
    mask = (time >= interval[0]) & (time <= interval[1])
    indices = np.flatnonzero(mask)
    local_peaks, _ = find_peaks(
        signal[mask],
        prominence=0.025,
        distance=max(20, int(round(fps * 1.1))),
    )
    return indices[local_peaks]


def percentile_range(values: np.ndarray) -> float:
    low, high = np.percentile(values, [5, 95])
    return float(high - low)


def summarize_passes(
    df: pd.DataFrame,
    signals: dict[str, np.ndarray],
    passes: dict[str, tuple[float, float]],
    fps: float,
) -> tuple[pd.DataFrame, dict[str, dict[str, list[int]]]]:
    rows: list[dict[str, float | str | int]] = []
    all_peaks: dict[str, dict[str, list[int]]] = {}
    time = df["time"].to_numpy()
    for pass_name, interval in passes.items():
        mask = (time >= interval[0]) & (time <= interval[1])
        all_peaks[pass_name] = {}
        for side in SIDES:
            peaks = detect_swing_peaks(
                time,
                signals[f"{side}_foot_clearance_proxy"],
                interval,
                fps,
            )
            all_peaks[pass_name][side] = peaks.tolist()
            stride_times = np.diff(time[peaks])
            knee = signals[f"{side}_knee_flexion_deg"][mask]
            clearance = signals[f"{side}_foot_clearance_proxy"][peaks]
            lateral = np.abs(signals[f"{side}_ankle_lateral_proxy"][peaks])
            wrist = signals[f"{side}_wrist_swing_proxy"][mask]
            rows.append(
                {
                    "pass": pass_name,
                    "side": side,
                    "num_swing_peaks": int(len(peaks)),
                    "stride_time_s": float(np.median(stride_times))
                    if len(stride_times)
                    else np.nan,
                    "knee_flexion_p05_deg": float(np.percentile(knee, 5)),
                    "knee_flexion_p95_deg": float(np.percentile(knee, 95)),
                    "knee_flexion_rom_deg": percentile_range(knee),
                    "foot_clearance_proxy": float(np.median(clearance))
                    if len(clearance)
                    else np.nan,
                    "ankle_lateral_proxy": float(np.median(lateral))
                    if len(lateral)
                    else np.nan,
                    "wrist_swing_rom_proxy": percentile_range(wrist),
                    "mean_distal_visibility": float(
                        df.loc[
                            mask,
                            [
                                f"{side}_knee_visibility",
                                f"{side}_ankle_visibility",
                                f"{side}_heel_visibility",
                                f"{side}_foot_index_visibility",
                            ],
                        ]
                        .mean(axis=1)
                        .mean()
                    ),
                }
            )
    return pd.DataFrame(rows), all_peaks


def aggregate_side_metrics(pass_metrics: pd.DataFrame) -> pd.DataFrame:
    numeric = [
        "stride_time_s",
        "knee_flexion_p05_deg",
        "knee_flexion_p95_deg",
        "knee_flexion_rom_deg",
        "foot_clearance_proxy",
        "ankle_lateral_proxy",
        "wrist_swing_rom_proxy",
        "mean_distal_visibility",
    ]
    return pass_metrics.groupby("side", as_index=False)[numeric].mean()


def classify_phenotypes(
    df: pd.DataFrame,
    signals: dict[str, np.ndarray],
    passes: dict[str, tuple[float, float]],
    pass_metrics: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, str | float]] = []
    aggregate = aggregate_side_metrics(pass_metrics).set_index("side")
    left = aggregate.loc["left"]
    right = aggregate.loc["right"]

    lower_knee_side = (
        "right"
        if right["knee_flexion_p95_deg"] < left["knee_flexion_p95_deg"]
        else "left"
    )
    other_side = "left" if lower_knee_side == "right" else "right"
    knee_difference = float(
        aggregate.loc[other_side, "knee_flexion_p95_deg"]
        - aggregate.loc[lower_knee_side, "knee_flexion_p95_deg"]
    )
    pass_differences = []
    for pass_name in passes:
        local = pass_metrics[pass_metrics["pass"] == pass_name].set_index("side")
        pass_differences.append(
            float(
                local.loc[other_side, "knee_flexion_p95_deg"]
                - local.loc[lower_knee_side, "knee_flexion_p95_deg"]
            )
        )
    if knee_difference >= 3.0 and all(value > 2.0 for value in pass_differences):
        rows.append(
            {
                "phenotype_id": "reduced_swing_knee_flexion",
                "side": lower_knee_side,
                "status": "screen_positive",
                "confidence": "moderate",
                "video_evidence": (
                    f"{lower_knee_side} peak knee flexion was "
                    f"{knee_difference:.1f} deg lower on average; "
                    f"pass differences={pass_differences[0]:.1f},"
                    f"{pass_differences[1]:.1f} deg"
                ),
                "interpretation": (
                    "Candidate stiff-knee pattern. The threshold is a custom "
                    "screening rule, not a diagnostic cutoff."
                ),
                "observability": "moderate_front_view",
            }
        )

    clearance_ratio = float(
        aggregate.loc[lower_knee_side, "foot_clearance_proxy"]
        / max(aggregate.loc[other_side, "foot_clearance_proxy"], 1e-6)
    )
    lateral_ratio = float(
        aggregate.loc[lower_knee_side, "ankle_lateral_proxy"]
        / max(aggregate.loc[other_side, "ankle_lateral_proxy"], 1e-6)
    )
    if clearance_ratio > 1.25:
        rows.append(
            {
                "phenotype_id": "compensatory_foot_clearance",
                "side": lower_knee_side,
                "status": "screen_positive",
                "confidence": "moderate",
                "video_evidence": (
                    f"Foot-clearance proxy ratio={clearance_ratio:.2f}; "
                    f"lateral ankle excursion ratio={lateral_ratio:.2f}"
                ),
                "interpretation": (
                    "Higher foot lift despite lower knee flexion suggests a "
                    "possible proximal or lateral clearance strategy."
                ),
                "observability": "moderate_front_view",
            }
        )

    straight_mask = np.zeros(len(df), dtype=bool)
    time = df["time"].to_numpy()
    for interval in passes.values():
        straight_mask |= (time >= interval[0]) & (time <= interval[1])
    trunk = signals["trunk_lean_deg"][straight_mask]
    trunk_median = float(np.median(trunk))
    trunk_excursion = percentile_range(trunk)
    if abs(trunk_median) >= 3.0 or trunk_excursion >= 10.0:
        image_direction = "image_left_patient_right" if trunk_median < 0 else "image_right_patient_left"
        rows.append(
            {
                "phenotype_id": "lateral_trunk_lean",
                "side": "right" if trunk_median < 0 else "left",
                "status": "screen_positive",
                "confidence": "moderate",
                "video_evidence": (
                    f"Median trunk lean={trunk_median:.1f} deg "
                    f"({image_direction}); p05-p95 excursion={trunk_excursion:.1f} deg"
                ),
                "interpretation": (
                    "Possible balance or lower-limb unloading compensation; "
                    "camera perspective remains a confounder."
                ),
                "observability": "good_front_view",
            }
        )

    arm_ratio = float(
        min(left["wrist_swing_rom_proxy"], right["wrist_swing_rom_proxy"])
        / max(left["wrist_swing_rom_proxy"], right["wrist_swing_rom_proxy"], 1e-6)
    )
    if arm_ratio < 0.75:
        reduced_side = (
            "left"
            if left["wrist_swing_rom_proxy"] < right["wrist_swing_rom_proxy"]
            else "right"
        )
        rows.append(
            {
                "phenotype_id": "reduced_arm_swing",
                "side": reduced_side,
                "status": "confounded",
                "confidence": "low",
                "video_evidence": f"Arm-swing ROM ratio={arm_ratio:.2f}",
                "interpretation": (
                    "The hand is held near/in a pocket and distal visibility "
                    "is lower, so this should not be interpreted as neurological impairment."
                ),
                "observability": "poor_behavioral_confound",
            }
        )

    return pd.DataFrame(rows)


def select_patient_cycle(
    df: pd.DataFrame,
    signals: dict[str, np.ndarray],
    peaks: dict[str, dict[str, list[int]]],
    phenotype_table: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float | str]]:
    knee_rows = phenotype_table[
        phenotype_table["phenotype_id"] == "reduced_swing_knee_flexion"
    ]
    anchor_side = str(knee_rows.iloc[0]["side"]) if len(knee_rows) else "right"
    candidates = peaks["toward"][anchor_side]
    if len(candidates) < 2:
        candidates = peaks["away"][anchor_side]
    if len(candidates) < 2:
        raise RuntimeError("Could not identify a complete same-side gait cycle.")
    pair_index = 1 if len(candidates) >= 3 else 0
    start_idx, end_idx = candidates[pair_index], candidates[pair_index + 1]
    cycle = df.iloc[start_idx : end_idx + 1][["frame", "time"]].copy()
    cycle["time_from_start_s"] = cycle["time"] - cycle["time"].iloc[0]
    duration = float(cycle["time_from_start_s"].iloc[-1])
    cycle["gait_cycle_percent"] = 100.0 * cycle["time_from_start_s"] / duration
    for side in SIDES:
        cycle[f"{side}_knee_flexion_deg"] = signals[
            f"{side}_knee_flexion_deg"
        ][start_idx : end_idx + 1]
        cycle[f"{side}_foot_clearance_proxy"] = signals[
            f"{side}_foot_clearance_proxy"
        ][start_idx : end_idx + 1]
        cycle[f"{side}_ankle_lateral_proxy"] = signals[
            f"{side}_ankle_lateral_proxy"
        ][start_idx : end_idx + 1]
    cycle["trunk_lean_deg"] = signals["trunk_lean_deg"][start_idx : end_idx + 1]
    metadata: dict[str, float | str] = {
        "anchor_side": anchor_side,
        "start_time_s": float(df["time"].iloc[start_idx]),
        "end_time_s": float(df["time"].iloc[end_idx]),
        "duration_s": duration,
    }
    return cycle, metadata


def plot_signals(
    df: pd.DataFrame,
    signals: dict[str, np.ndarray],
    passes: dict[str, tuple[float, float]],
    peaks: dict[str, dict[str, list[int]]],
    output_path: Path,
) -> None:
    colors = {"left": "#2676b8", "right": "#c84d3a"}
    time = df["time"].to_numpy()
    fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True)
    for side in SIDES:
        axes[0].plot(
            time,
            signals[f"{side}_knee_flexion_deg"],
            color=colors[side],
            label=side,
        )
        axes[1].plot(
            time,
            signals[f"{side}_foot_clearance_proxy"],
            color=colors[side],
            label=side,
        )
        axes[2].plot(
            time,
            signals[f"{side}_ankle_lateral_proxy"],
            color=colors[side],
            label=side,
        )
        for pass_name in passes:
            idx = np.array(peaks[pass_name][side], dtype=int)
            axes[1].scatter(
                time[idx],
                signals[f"{side}_foot_clearance_proxy"][idx],
                color=colors[side],
                s=22,
                zorder=3,
            )
    axes[3].plot(time, signals["trunk_lean_deg"], color="#3a6b35")
    axes[3].axhline(0, color="#777777", linewidth=0.8)
    for axis in axes:
        for pass_name, interval in passes.items():
            axis.axvspan(interval[0], interval[1], color="#dfe8ee", alpha=0.35)
        axis.grid(alpha=0.22)
    axes[0].set_ylabel("Knee flexion (deg)")
    axes[1].set_ylabel("Foot-clearance proxy")
    axes[2].set_ylabel("Lateral ankle proxy")
    axes[3].set_ylabel("Trunk lean (deg)")
    axes[3].set_xlabel("Video time (s)")
    axes[0].legend(ncol=2, loc="upper right")
    fig.suptitle("Video-derived gait phenotype signals")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def save_pose_contact_sheet(
    video_path: Path,
    df: pd.DataFrame,
    passes: dict[str, tuple[float, float]],
    output_path: Path,
) -> None:
    cap = cv2.VideoCapture(str(video_path))
    selected_times: list[float] = []
    for interval in passes.values():
        selected_times.extend(np.linspace(interval[0], interval[1], 6).tolist())
    fig, axes = plt.subplots(3, 4, figsize=(12, 14))
    for axis, target_time in zip(axes.flat, selected_times):
        row_index = int(np.argmin(np.abs(df["time"].to_numpy() - target_time)))
        frame_index = int(df["frame"].iloc[row_index])
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            axis.axis("off")
            continue
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width = frame.shape[:2]
        row = df.iloc[row_index]
        for first, second in SKELETON:
            x1 = int(row[f"{first}_x_pxnorm"] * width)
            y1 = int(row[f"{first}_y_pxnorm"] * height)
            x2 = int(row[f"{second}_x_pxnorm"] * width)
            y2 = int(row[f"{second}_y_pxnorm"] * height)
            axis.plot([x1, x2], [y1, y2], color="#f4f4f4", linewidth=1.4)
        for side, color in (("left", "#2c7fb8"), ("right", "#d95f0e")):
            for landmark in ("hip", "knee", "ankle", "heel", "foot_index"):
                name = f"{side}_{landmark}"
                axis.scatter(
                    row[f"{name}_x_pxnorm"] * width,
                    row[f"{name}_y_pxnorm"] * height,
                    s=13,
                    color=color,
                )
        axis.imshow(frame)
        axis.set_title(f"t={row['time']:.1f}s")
        axis.axis("off")
    cap.release()
    fig.suptitle("Patient video pose tracking (anatomical left=blue, right=orange)")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--landmarks", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.landmarks).interpolate(limit_direction="both")
    cap = cv2.VideoCapture(str(args.video))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    cap.release()

    signals = derive_signals(df, fps)
    passes = detect_passes(df, signals["body_scale"])
    pass_metrics, peaks = summarize_passes(df, signals, passes, fps)
    side_metrics = aggregate_side_metrics(pass_metrics)
    phenotypes = classify_phenotypes(df, signals, passes, pass_metrics)
    cycle, cycle_metadata = select_patient_cycle(df, signals, peaks, phenotypes)

    pass_metrics.to_csv(args.output_dir / "gait_pass_metrics.csv", index=False)
    side_metrics.to_csv(args.output_dir / "gait_side_summary.csv", index=False)
    phenotypes.to_csv(args.output_dir / "movement_phenotypes.csv", index=False)
    cycle.to_csv(args.output_dir / "selected_patient_gait_cycle.csv", index=False)
    with (args.output_dir / "analysis_metadata.json").open("w", encoding="utf-8") as file:
        json.dump(
            {
                "video": str(args.video),
                "fps": fps,
                "num_frames": len(df),
                "pose_detection_rate": float(df["pose_detected"].mean()),
                "passes": passes,
                "cycle": cycle_metadata,
                "method": (
                    "Custom interpretable screening rules applied to smoothed "
                    "MediaPipe landmarks; not a clinical diagnosis."
                ),
            },
            file,
            indent=2,
        )

    plot_signals(
        df,
        signals,
        passes,
        peaks,
        args.output_dir / "video_gait_phenotype_signals.png",
    )
    save_pose_contact_sheet(
        args.video,
        df,
        passes,
        args.output_dir / "patient_pose_contact_sheet.png",
    )
    print(phenotypes.to_string(index=False))
    print(f"Wrote patient video analysis to {args.output_dir}")


if __name__ == "__main__":
    main()

