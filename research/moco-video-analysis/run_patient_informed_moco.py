from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator
from scipy.signal import savgol_filter


PAIR_NAMES = [
    "hamstrings",
    "bifemsh",
    "glut_max",
    "iliopsoas",
    "rect_fem",
    "vasti",
    "gastroc",
    "soleus",
    "tib_ant",
]


def configure_opensim_dll_search() -> object | None:
    if os.name != "nt":
        return None
    spec = importlib.util.find_spec("opensim")
    if spec is None or spec.origin is None:
        return None
    package_dir = str(Path(spec.origin).resolve().parent)
    os.environ["PATH"] = package_dir + os.pathsep + os.environ.get("PATH", "")
    os.environ["CASADIPATH"] = package_dir
    return os.add_dll_directory(package_dir)


_OPENSIM_DLL_DIRECTORY = configure_opensim_dll_search()

import opensim as osim


def table_to_dataframe(path: Path) -> pd.DataFrame:
    table = osim.TimeSeriesTable(str(path))
    labels = list(table.getColumnLabels())
    frame = pd.DataFrame(table.getMatrix().to_numpy(), columns=labels)
    frame.insert(0, "time", list(table.getIndependentColumn()))
    return frame


def build_full_generic_cycle(reference_path: Path) -> pd.DataFrame:
    first = table_to_dataframe(reference_path)
    duration = float(first["time"].iloc[-1] - first["time"].iloc[0])
    second = first.iloc[1:].copy()
    second["time"] = second["time"] + duration
    second["/jointset/groundPelvis/pelvis_tx/value"] += float(
        first["/jointset/groundPelvis/pelvis_tx/value"].iloc[-1]
    )
    for joint in ("hip_flexion", "knee_angle", "ankle_angle"):
        left = f"/jointset/{joint.split('_')[0]}_l/{joint}_l/value"
        right = f"/jointset/{joint.split('_')[0]}_r/{joint}_r/value"
        if joint == "hip_flexion":
            left = "/jointset/hip_l/hip_flexion_l/value"
            right = "/jointset/hip_r/hip_flexion_r/value"
        elif joint == "knee_angle":
            left = "/jointset/knee_l/knee_angle_l/value"
            right = "/jointset/knee_r/knee_angle_r/value"
        elif joint == "ankle_angle":
            left = "/jointset/ankle_l/ankle_angle_l/value"
            right = "/jointset/ankle_r/ankle_angle_r/value"
        original_left = second[left].copy()
        second[left] = second[right].to_numpy()
        second[right] = original_left.to_numpy()
    return pd.concat([first, second], ignore_index=True)


def smooth_cycle_endpoint(values: np.ndarray) -> np.ndarray:
    values = savgol_filter(values, min(15, len(values) // 2 * 2 - 1), 3)
    mismatch = values[-1] - values[0]
    return values - np.linspace(0.0, mismatch, len(values))


def construct_patient_reference(
    generic_reference: Path,
    patient_cycle_path: Path,
    output_path: Path,
    reference_mode: str,
    knee_mode: str,
) -> tuple[pd.DataFrame, dict[str, float]]:
    patient = pd.read_csv(patient_cycle_path)
    patient_duration = float(patient["time_from_start_s"].iloc[-1])
    if reference_mode == "full":
        generic = build_full_generic_cycle(generic_reference)
        target_duration = patient_duration
        target_time = np.linspace(0.0, target_duration, 81)
    else:
        generic = table_to_dataframe(generic_reference)
        for joint, coordinate in (
            ("hip", "hip_flexion"),
            ("knee", "knee_angle"),
            ("ankle", "ankle_angle"),
        ):
            left = f"/jointset/{joint}_l/{coordinate}_l/value"
            right = f"/jointset/{joint}_r/{coordinate}_r/value"
            original_left = generic[left].copy()
            generic[left] = generic[right].to_numpy()
            generic[right] = original_left.to_numpy()
        target_duration = patient_duration / 2.0
        target_time = np.linspace(0.0, target_duration, 41)
    generic_phase = (
        generic["time"].to_numpy() - generic["time"].iloc[0]
    ) / (generic["time"].iloc[-1] - generic["time"].iloc[0])
    target_phase = target_time / target_duration

    reference = pd.DataFrame({"time": target_time})
    for column in generic.columns:
        if column == "time":
            continue
        reference[column] = PchipInterpolator(
            generic_phase, generic[column].to_numpy()
        )(target_phase)

    knee_metrics: dict[str, float] = {}
    generic_stance_flexion_deg = 8.0
    if reference_mode == "full":
        patient_phase = patient["gait_cycle_percent"].to_numpy() / 100.0
        for side in ("left", "right"):
            measured = PchipInterpolator(
                patient_phase,
                patient[f"{side}_knee_flexion_deg"].to_numpy(),
            )(target_phase)
            measured = smooth_cycle_endpoint(measured)
            relative = measured - np.percentile(measured, 5)
            model_flexion_deg = generic_stance_flexion_deg + relative
            column = f"/jointset/knee_{side[0]}/knee_angle_{side[0]}/value"
            reference[column] = -np.radians(model_flexion_deg)
            knee_metrics[f"{side}_knee_flexion_min_deg"] = float(
                np.min(model_flexion_deg)
            )
            knee_metrics[f"{side}_knee_flexion_max_deg"] = float(
                np.max(model_flexion_deg)
            )
    elif knee_mode == "patient":
        measured_right = patient["right_knee_flexion_deg"].to_numpy()
        measured_excursion = float(
            np.percentile(measured_right, 95)
            - np.percentile(measured_right, 5)
        )
        right_column = "/jointset/knee_r/knee_angle_r/value"
        generic_right_flexion = -np.degrees(reference[right_column].to_numpy())
        generic_relative = generic_right_flexion - np.min(generic_right_flexion)
        generic_relative /= max(float(np.max(generic_relative)), 1e-6)
        model_flexion_deg = (
            generic_stance_flexion_deg + measured_excursion * generic_relative
        )
        reference[right_column] = -np.radians(model_flexion_deg)
        knee_metrics["right_knee_flexion_min_deg"] = float(
            np.min(model_flexion_deg)
        )
        knee_metrics["right_knee_flexion_max_deg"] = float(
            np.max(model_flexion_deg)
        )
        left_column = "/jointset/knee_l/knee_angle_l/value"
        knee_metrics["left_knee_flexion_min_deg"] = float(
            np.min(-np.degrees(reference[left_column]))
        )
        knee_metrics["left_knee_flexion_max_deg"] = float(
            np.max(-np.degrees(reference[left_column]))
        )
    else:
        for side in ("left", "right"):
            column = f"/jointset/knee_{side[0]}/knee_angle_{side[0]}/value"
            flexion = -np.degrees(reference[column])
            knee_metrics[f"{side}_knee_flexion_min_deg"] = float(
                np.min(flexion)
            )
            knee_metrics[f"{side}_knee_flexion_max_deg"] = float(
                np.max(flexion)
            )

    write_storage(reference, output_path, "patient_informed_coordinates")
    return reference, knee_metrics


def write_storage(frame: pd.DataFrame, path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as file:
        file.write(f"name {name}\n")
        file.write(f"nRows={len(frame)}\n")
        file.write(f"nColumns={len(frame.columns)}\n")
        file.write("inDegrees=no\n")
        file.write("endheader\n")
        frame.to_csv(file, sep="\t", index=False, lineterminator="\n")


def add_state_bounds(problem: osim.MocoProblem, reference: pd.DataFrame) -> None:
    bounds = {
        "/jointset/groundPelvis/pelvis_tilt/value": (-0.70, 0.35),
        "/jointset/groundPelvis/pelvis_tx/value": (
            float(reference["/jointset/groundPelvis/pelvis_tx/value"].min() - 0.2),
            float(reference["/jointset/groundPelvis/pelvis_tx/value"].max() + 0.2),
        ),
        "/jointset/groundPelvis/pelvis_ty/value": (0.70, 1.20),
        "/jointset/hip_l/hip_flexion_l/value": (-0.70, 1.40),
        "/jointset/hip_r/hip_flexion_r/value": (-0.70, 1.40),
        "/jointset/knee_l/knee_angle_l/value": (-1.75, 0.10),
        "/jointset/knee_r/knee_angle_r/value": (-1.75, 0.10),
        "/jointset/ankle_l/ankle_angle_l/value": (-0.80, 0.80),
        "/jointset/ankle_r/ankle_angle_r/value": (-0.80, 0.80),
        "/jointset/lumbar/lumbar/value": (-0.45, 0.70),
    }
    for state_name, state_bounds in bounds.items():
        problem.setStateInfo(state_name, state_bounds)


def add_full_cycle_periodicity(
    problem: osim.MocoProblem, model: osim.Model
) -> None:
    periodicity = osim.MocoPeriodicityGoal("full_cycle_periodicity")
    coordinate_names = [
        "pelvis_tilt",
        "pelvis_tx",
        "pelvis_ty",
        "hip_flexion_l",
        "hip_flexion_r",
        "knee_angle_l",
        "knee_angle_r",
        "ankle_angle_l",
        "ankle_angle_r",
        "lumbar",
    ]
    coordinate_paths = {
        "pelvis_tilt": "/jointset/groundPelvis/pelvis_tilt",
        "pelvis_tx": "/jointset/groundPelvis/pelvis_tx",
        "pelvis_ty": "/jointset/groundPelvis/pelvis_ty",
        "hip_flexion_l": "/jointset/hip_l/hip_flexion_l",
        "hip_flexion_r": "/jointset/hip_r/hip_flexion_r",
        "knee_angle_l": "/jointset/knee_l/knee_angle_l",
        "knee_angle_r": "/jointset/knee_r/knee_angle_r",
        "ankle_angle_l": "/jointset/ankle_l/ankle_angle_l",
        "ankle_angle_r": "/jointset/ankle_r/ankle_angle_r",
        "lumbar": "/jointset/lumbar/lumbar",
    }
    for coordinate_name in coordinate_names:
        path = coordinate_paths[coordinate_name]
        if coordinate_name != "pelvis_tx":
            periodicity.addStatePair(osim.MocoPeriodicityGoalPair(f"{path}/value"))
        periodicity.addStatePair(osim.MocoPeriodicityGoalPair(f"{path}/speed"))
    for index in range(model.getMuscles().getSize()):
        muscle = model.getMuscles().get(index)
        periodicity.addStatePair(
            osim.MocoPeriodicityGoalPair(
                f"/forceset/{muscle.getName()}/activation"
            )
        )
    problem.addGoal(periodicity)


def solve_moco(
    model_path: Path,
    reference_path: Path,
    reference: pd.DataFrame,
    output_dir: Path,
    mesh_intervals: int,
    enforce_periodicity: bool,
) -> Path:
    track = osim.MocoTrack()
    track.setName("patient_informed_video_moco")
    track.setModel(osim.ModelProcessor(str(model_path)))
    track.setStatesReference(osim.TableProcessor(str(reference_path)))
    track.set_states_global_tracking_weight(10.0)
    track.set_allow_unused_references(True)
    track.set_track_reference_position_derivatives(True)
    track.set_apply_tracked_states_to_guess(True)
    track.set_control_effort_weight(1.0)
    track.set_initial_time(float(reference["time"].iloc[0]))
    track.set_final_time(float(reference["time"].iloc[-1]))

    study = track.initialize()
    problem = study.updProblem()
    model = osim.Model(str(model_path))
    add_state_bounds(problem, reference)
    if enforce_periodicity:
        add_full_cycle_periodicity(problem, model)

    solver = osim.MocoCasADiSolver.safeDownCast(study.updSolver())
    solver.set_num_mesh_intervals(mesh_intervals)
    solver.set_optim_solver("ipopt")
    solver.set_optim_convergence_tolerance(1e-3)
    solver.set_optim_constraint_tolerance(1e-3)
    solver.set_optim_max_iterations(600)

    solution = study.solve()
    output_path = output_dir / "patient_informed_moco_solution.sto"
    solution.write(str(output_path))
    return output_path


def analyze_forces(
    model_path: Path, solution_path: Path, output_path: Path
) -> pd.DataFrame:
    model = osim.Model(str(model_path))
    trajectory = osim.MocoTrajectory(str(solution_path))
    output_paths = osim.StdVectorString()
    output_paths.append(".*tendon_force")
    table = osim.analyzeMocoTrajectory(model, trajectory, output_paths)
    osim.STOFileAdapter.write(table, str(output_path))
    return table_to_dataframe(output_path)


def activation_column(frame: pd.DataFrame, muscle_name: str) -> str:
    candidates = [
        column
        for column in frame.columns
        if column.endswith(f"/{muscle_name}/activation")
    ]
    if not candidates:
        raise KeyError(f"No activation state for {muscle_name}")
    return candidates[0]


def force_column(frame: pd.DataFrame, muscle_name: str) -> str:
    candidates = [
        column
        for column in frame.columns
        if muscle_name in column and "tendon_force" in column
    ]
    if not candidates:
        raise KeyError(f"No tendon force output for {muscle_name}")
    return candidates[0]


def summarize_muscles(
    solution: pd.DataFrame, forces: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for base in PAIR_NAMES:
        side_values: dict[str, dict[str, float]] = {}
        for side in ("l", "r"):
            name = f"{base}_{side}"
            activation = solution[activation_column(solution, name)].to_numpy()
            force = forces[force_column(forces, name)].to_numpy()
            side_values[side] = {
                "mean_activation": float(np.mean(activation)),
                "peak_activation": float(np.max(activation)),
                "mean_force_n": float(np.mean(force)),
                "peak_force_n": float(np.max(force)),
            }
        rows.append(
            {
                "muscle_group": base,
                "left_mean_activation": side_values["l"]["mean_activation"],
                "right_mean_activation": side_values["r"]["mean_activation"],
                "activation_asymmetry_right_minus_left": (
                    side_values["r"]["mean_activation"]
                    - side_values["l"]["mean_activation"]
                ),
                "left_peak_activation": side_values["l"]["peak_activation"],
                "right_peak_activation": side_values["r"]["peak_activation"],
                "left_mean_force_n": side_values["l"]["mean_force_n"],
                "right_mean_force_n": side_values["r"]["mean_force_n"],
                "force_asymmetry_right_minus_left_n": (
                    side_values["r"]["mean_force_n"]
                    - side_values["l"]["mean_force_n"]
                ),
                "left_peak_force_n": side_values["l"]["peak_force_n"],
                "right_peak_force_n": side_values["r"]["peak_force_n"],
            }
        )
    return pd.DataFrame(rows)


def plot_paired_outputs(
    frame: pd.DataFrame,
    kind: str,
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(14, 11), sharex=True)
    time = frame["time"].to_numpy()
    gait_percent = 100.0 * (time - time[0]) / (time[-1] - time[0])
    for axis, base in zip(axes.flat, PAIR_NAMES):
        for side, color, label in (
            ("l", "#2878b5", "left"),
            ("r", "#d14a3a", "right"),
        ):
            name = f"{base}_{side}"
            column = (
                activation_column(frame, name)
                if kind == "activation"
                else force_column(frame, name)
            )
            axis.plot(gait_percent, frame[column], color=color, label=label)
        axis.set_title(base)
        axis.grid(alpha=0.22)
    axes[0, 0].legend()
    for axis in axes[-1, :]:
        axis.set_xlabel("Gait cycle (%)")
    ylabel = "Activation (0-1)" if kind == "activation" else "Tendon force (N)"
    for axis in axes[:, 0]:
        axis.set_ylabel(ylabel)
    title = (
        "Patient-informed Moco muscle activations"
        if kind == "activation"
        else "Patient-informed Moco muscle tendon forces"
    )
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def plot_tracking(
    solution: pd.DataFrame,
    reference: pd.DataFrame,
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for axis, side, color in (
        (axes[0], "l", "#2878b5"),
        (axes[1], "r", "#d14a3a"),
    ):
        column = f"/jointset/knee_{side}/knee_angle_{side}/value"
        solution_deg = -np.degrees(solution[column])
        reference_deg = -np.degrees(reference[column])
        solution_percent = 100 * (
            solution["time"] - solution["time"].iloc[0]
        ) / (solution["time"].iloc[-1] - solution["time"].iloc[0])
        reference_percent = 100 * (
            reference["time"] - reference["time"].iloc[0]
        ) / (reference["time"].iloc[-1] - reference["time"].iloc[0])
        axis.plot(reference_percent, reference_deg, "--", color="#333333", label="video-informed reference")
        axis.plot(solution_percent, solution_deg, color=color, label="Moco solution")
        axis.set_ylabel(f"{side.upper()} knee flexion (deg)")
        axis.grid(alpha=0.22)
        axis.legend()
    axes[-1].set_xlabel("Analyzed right-swing step (%)")
    fig.suptitle("Moco tracking of video-informed knee kinematics")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def build_explanation_table(
    phenotype_path: Path,
    muscle_summary: pd.DataFrame,
    output_path: Path,
) -> pd.DataFrame:
    phenotypes = pd.read_csv(phenotype_path)
    explanations: list[dict[str, str]] = []
    for _, phenotype in phenotypes.iterrows():
        phenotype_id = str(phenotype["phenotype_id"])
        if phenotype_id == "reduced_swing_knee_flexion":
            support = (
                "Do not compare left and right mean activation in this half-step: "
                "the limbs are in different gait phases. Use the matched-template "
                "counterfactual in outputs/patient_report."
            )
            mechanism = (
                "Reduced swing knee flexion can reflect reduced knee-flexor "
                "drive, excessive rectus femoris/vasti activity, weak push-off, "
                "or a combination. This solve alone cannot identify which mechanism."
            )
        elif phenotype_id == "compensatory_foot_clearance":
            support = (
                "The 2D Moco model has no hip ab/adduction or pelvic hiking "
                "degrees of freedom, so the observed lateral/proximal strategy "
                "cannot be dynamically reproduced."
            )
            mechanism = (
                "Possible hip hiking, circumduction, or increased hip flexion "
                "used to clear the foot despite reduced knee flexion."
            )
        elif phenotype_id == "lateral_trunk_lean":
            support = (
                "Not testable in the sagittal-only 2D Moco model; a 3D model "
                "with hip abductors and frontal-plane trunk motion is required."
            )
            mechanism = (
                "Possible balance strategy, stance-limb unloading, or hip "
                "abductor compensation."
            )
        else:
            support = "Upper-limb muscles are not represented in the current model."
            mechanism = (
                "Video finding is confounded by hand placement and should not "
                "be assigned a neurological mechanism."
            )
        explanations.append(
            {
                "movement_phenotype": phenotype_id,
                "side": str(phenotype["side"]),
                "video_evidence": str(phenotype["video_evidence"]),
                "moco_support_or_limitation": support,
                "possible_explanation": mechanism,
                "confidence": str(phenotype["confidence"]),
                "clinical_claim": "screening_hypothesis_not_diagnosis",
            }
        )
    result = pd.DataFrame(explanations)
    result.to_csv(output_path, index=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--generic-reference", required=True, type=Path)
    parser.add_argument("--patient-cycle", required=True, type=Path)
    parser.add_argument("--phenotypes", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mesh-intervals", type=int, default=8)
    parser.add_argument("--enforce-periodicity", action="store_true")
    parser.add_argument(
        "--reference-mode",
        choices=("half", "full"),
        default="half",
        help="Use a patient-informed right-swing half-cycle or an experimental full cycle.",
    )
    parser.add_argument(
        "--skip-solve",
        action="store_true",
        help="Reuse patient_informed_moco_solution.sto in the output directory.",
    )
    parser.add_argument(
        "--knee-mode",
        choices=("patient", "generic"),
        default="patient",
        help="Use video-derived right-knee excursion or the matched generic template.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    reference_path = args.output_dir / "patient_informed_coordinates.sto"
    reference, knee_metrics = construct_patient_reference(
        args.generic_reference,
        args.patient_cycle,
        reference_path,
        args.reference_mode,
        args.knee_mode,
    )
    solution_path = args.output_dir / "patient_informed_moco_solution.sto"
    if args.skip_solve:
        if not solution_path.exists():
            raise FileNotFoundError(solution_path)
    else:
        solution_path = solve_moco(
            args.model,
            reference_path,
            reference,
            args.output_dir,
            args.mesh_intervals,
            args.enforce_periodicity,
        )
    solution = table_to_dataframe(solution_path)
    force_path = args.output_dir / "patient_informed_muscle_tendon_forces.sto"
    forces = analyze_forces(args.model, solution_path, force_path)
    muscle_summary = summarize_muscles(solution, forces)
    muscle_summary.to_csv(
        args.output_dir / "moco_muscle_summary.csv", index=False
    )
    explanations = build_explanation_table(
        args.phenotypes,
        muscle_summary,
        args.output_dir / "phenotype_moco_explanations.csv",
    )
    plot_paired_outputs(
        solution,
        "activation",
        args.output_dir / "moco_muscle_activations.png",
    )
    plot_paired_outputs(
        forces,
        "force",
        args.output_dir / "moco_muscle_tendon_forces.png",
    )
    plot_tracking(
        solution,
        reference,
        args.output_dir / "moco_knee_tracking.png",
    )
    with (args.output_dir / "moco_run_metadata.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            {
                "model": str(args.model),
                "reference": str(reference_path),
                "solution": str(solution_path),
                "mesh_intervals": args.mesh_intervals,
                "enforce_periodicity": args.enforce_periodicity,
                "reference_mode": args.reference_mode,
                "knee_mode": args.knee_mode,
                "patient_informed_variables": [
                    "gait_cycle_duration",
                    "left_knee_flexion_waveform",
                    "right_knee_flexion_waveform",
                ],
                "template_variables": [
                    "pelvis_sagittal_kinematics",
                    "hip_flexion",
                    "ankle_flexion",
                    "lumbar_flexion",
                ],
                "knee_metrics": knee_metrics,
                "warning": (
                    "Single-view frontal video cannot provide calibrated 3D "
                    "OpenSim kinematics. Results are patient-informed proxy "
                    "estimates, not patient-specific measured muscle forces."
                ),
            },
            file,
            indent=2,
        )
    print(explanations.to_string(index=False))
    print(f"Wrote patient-informed Moco outputs to {args.output_dir}")


if __name__ == "__main__":
    main()

