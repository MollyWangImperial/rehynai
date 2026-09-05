from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import mediapipe as mp
import pandas as pd


POSE_LANDMARK_NAMES = [landmark.name.lower() for landmark in mp.solutions.pose.PoseLandmark]


def extract_pose(video_path: Path, output_dir: Path, max_frames: int | None = None) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    rows: list[dict[str, float | int]] = []

    pose = mp.solutions.pose.Pose(
        static_image_mode=False,
        model_complexity=2,
        smooth_landmarks=True,
        enable_segmentation=False,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    frame_idx = 0
    first_overlay_written = False
    while True:
        ok, frame_bgr = cap.read()
        if not ok:
            break
        if max_frames is not None and frame_idx >= max_frames:
            break

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = pose.process(frame_rgb)
        row: dict[str, float | int] = {
            "frame": frame_idx,
            "time": frame_idx / fps,
            "pose_detected": int(result.pose_landmarks is not None),
        }

        if result.pose_landmarks:
            for name, landmark in zip(POSE_LANDMARK_NAMES, result.pose_landmarks.landmark):
                row[f"{name}_x_pxnorm"] = landmark.x
                row[f"{name}_y_pxnorm"] = landmark.y
                row[f"{name}_z_pxnorm"] = landmark.z
                row[f"{name}_visibility"] = landmark.visibility

            if result.pose_world_landmarks:
                for name, landmark in zip(POSE_LANDMARK_NAMES, result.pose_world_landmarks.landmark):
                    row[f"{name}_x_world"] = landmark.x
                    row[f"{name}_y_world"] = landmark.y
                    row[f"{name}_z_world"] = landmark.z

            if not first_overlay_written:
                annotated = frame_bgr.copy()
                mp.solutions.drawing_utils.draw_landmarks(
                    annotated,
                    result.pose_landmarks,
                    mp.solutions.pose.POSE_CONNECTIONS,
                )
                cv2.imwrite(str(output_dir / "first_detected_pose_overlay.png"), annotated)
                first_overlay_written = True

        rows.append(row)
        frame_idx += 1

    cap.release()
    pose.close()
    df = pd.DataFrame(rows)
    csv_path = output_dir / "mediapipe_pose_landmarks.csv"
    df.to_csv(csv_path, index=False)
    return df


def plot_quality(df: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    visibility_cols = [col for col in df.columns if col.endswith("_visibility")]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["time"], df["pose_detected"], label="pose detected", color="#2f6f73", linewidth=1.8)
    if visibility_cols:
        ax.plot(df["time"], df[visibility_cols].mean(axis=1), label="mean landmark visibility", color="#b65f3b", linewidth=1.8)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("score")
    ax.set_ylim(-0.05, 1.05)
    ax.set_title("MediaPipe Pose Tracking Quality")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_dir / "pose_tracking_quality.png", dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("moco_video_analysis/outputs"), type=Path)
    parser.add_argument("--max-frames", type=int)
    args = parser.parse_args()

    df = extract_pose(args.video, args.output_dir, args.max_frames)
    plot_quality(df, args.output_dir)
    detected = int(df["pose_detected"].sum())
    print(f"Processed {len(df)} frames; pose detected in {detected} frames.")
    print(f"Wrote {args.output_dir / 'mediapipe_pose_landmarks.csv'}")
    print(f"Wrote {args.output_dir / 'pose_tracking_quality.png'}")


if __name__ == "__main__":
    main()

