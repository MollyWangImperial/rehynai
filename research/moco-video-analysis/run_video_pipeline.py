from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path


PINNED_MOCO_COMMIT = "492c0d08eef1b267ac9875579968b72c0f6d0fe8"
MOCO_RAW_ROOT = (
    "https://raw.githubusercontent.com/opensim-org/opensim-moco/"
    f"{PINNED_MOCO_COMMIT}/Moco/Examples/C%2B%2B/example2DWalking"
)
MODEL_ASSETS = {
    "2D_gait.osim": f"{MOCO_RAW_ROOT}/2D_gait.osim",
    "referenceCoordinates.sto": f"{MOCO_RAW_ROOT}/referenceCoordinates.sto",
}


def run(command: list[str]) -> None:
    print("\n>", subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, check=True)


def download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            temporary.write_bytes(response.read())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def resolve_model_assets(
    project_dir: Path,
    model: Path | None,
    generic_reference: Path | None,
) -> tuple[Path, Path]:
    if (model is None) != (generic_reference is None):
        raise ValueError(
            "--model and --generic-reference must be supplied together."
        )
    if model is not None and generic_reference is not None:
        if not model.exists():
            raise FileNotFoundError(model)
        if not generic_reference.exists():
            raise FileNotFoundError(generic_reference)
        return model.resolve(), generic_reference.resolve()

    vendored_example = (
        project_dir
        / "third_party"
        / "opensim-moco"
        / "Moco"
        / "Examples"
        / "C++"
        / "example2DWalking"
    )
    if (vendored_example / "2D_gait.osim").exists():
        return (
            (vendored_example / "2D_gait.osim").resolve(),
            (vendored_example / "referenceCoordinates.sto").resolve(),
        )

    model_dir = project_dir / "models"
    for filename, url in MODEL_ASSETS.items():
        destination = model_dir / filename
        if not destination.exists():
            print(f"Downloading pinned OpenSim example asset: {filename}")
            download_file(url, destination)
    return (
        (model_dir / "2D_gait.osim").resolve(),
        (model_dir / "referenceCoordinates.sto").resolve(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run video pose extraction, movement-phenotype screening, two Moco "
            "counterfactual solves, and a Chinese functional-issue report."
        )
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", default=Path("outputs/run"), type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--generic-reference", type=Path)
    parser.add_argument("--mesh-intervals", type=int, default=8)
    parser.add_argument(
        "--reuse-solutions",
        action="store_true",
        help="Reuse existing Moco solution files under the output directory.",
    )
    args = parser.parse_args()

    if not args.video.is_file():
        raise FileNotFoundError(args.video)
    if args.video.suffix.lower() not in {".mp4", ".mov", ".avi", ".mkv"}:
        raise ValueError(f"Unsupported video extension: {args.video.suffix}")

    project_dir = Path(__file__).resolve().parent
    output_dir = args.output_dir.resolve()
    pose_dir = output_dir / "pose"
    phenotype_dir = output_dir / "phenotypes"
    patient_dir = output_dir / "moco_video_informed"
    baseline_dir = output_dir / "moco_matched_template"
    report_dir = output_dir / "report"
    for directory in (
        pose_dir,
        phenotype_dir,
        patient_dir,
        baseline_dir,
        report_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    model, generic_reference = resolve_model_assets(
        project_dir,
        args.model,
        args.generic_reference,
    )
    python = sys.executable

    run(
        [
            python,
            str(project_dir / "extract_mediapipe_pose.py"),
            "--video",
            str(args.video.resolve()),
            "--output-dir",
            str(pose_dir),
        ]
    )
    landmarks = pose_dir / "mediapipe_pose_landmarks.csv"
    run(
        [
            python,
            str(project_dir / "analyze_patient_video.py"),
            "--video",
            str(args.video.resolve()),
            "--landmarks",
            str(landmarks),
            "--output-dir",
            str(phenotype_dir),
        ]
    )

    shared_moco_args = [
        "--model",
        str(model),
        "--generic-reference",
        str(generic_reference),
        "--patient-cycle",
        str(phenotype_dir / "selected_patient_gait_cycle.csv"),
        "--phenotypes",
        str(phenotype_dir / "movement_phenotypes.csv"),
        "--reference-mode",
        "half",
        "--mesh-intervals",
        str(args.mesh_intervals),
    ]
    reuse = ["--skip-solve"] if args.reuse_solutions else []
    run(
        [
            python,
            str(project_dir / "run_patient_informed_moco.py"),
            *shared_moco_args,
            "--output-dir",
            str(patient_dir),
            "--knee-mode",
            "patient",
            *reuse,
        ]
    )
    run(
        [
            python,
            str(project_dir / "run_patient_informed_moco.py"),
            *shared_moco_args,
            "--output-dir",
            str(baseline_dir),
            "--knee-mode",
            "generic",
            *reuse,
        ]
    )
    run(
        [
            python,
            str(project_dir / "compare_patient_moco.py"),
            "--patient-dir",
            str(patient_dir),
            "--baseline-dir",
            str(baseline_dir),
            "--phenotypes",
            str(phenotype_dir / "movement_phenotypes.csv"),
            "--output-dir",
            str(report_dir),
        ]
    )

    report = report_dir / "患者视频_Moco分析报告.md"
    if not report.exists():
        raise RuntimeError(f"Chinese report was not generated: {report}")
    print("\nAnalysis complete.")
    print(f"Chinese report: {report}")
    print(f"Activation plot: {report_dir / 'moco_activation_patient_vs_template.png'}")
    print(f"Force plot: {report_dir / 'moco_force_patient_vs_template.png'}")


if __name__ == "__main__":
    main()

