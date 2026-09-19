from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


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


def activation_column(frame: pd.DataFrame, muscle_name: str) -> str:
    return next(
        column
        for column in frame.columns
        if column.endswith(f"/{muscle_name}/activation")
    )


def force_column(frame: pd.DataFrame, muscle_name: str) -> str:
    return next(
        column
        for column in frame.columns
        if muscle_name in column and column.endswith("|tendon_force")
    )


def normalized_time(frame: pd.DataFrame) -> np.ndarray:
    time = frame["time"].to_numpy()
    return 100.0 * (time - time[0]) / (time[-1] - time[0])


def interpolate_to_percent(
    frame: pd.DataFrame, column: str, percent: np.ndarray
) -> np.ndarray:
    return np.interp(percent, normalized_time(frame), frame[column].to_numpy())


def read_storage_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if stripped == "endheader":
                break
            if "=" in stripped:
                key, value = stripped.split("=", 1)
                metadata[key] = value
    return metadata


def compare_conditions(
    patient_solution: pd.DataFrame,
    patient_forces: pd.DataFrame,
    baseline_solution: pd.DataFrame,
    baseline_forces: pd.DataFrame,
) -> pd.DataFrame:
    percent = np.linspace(10.0, 95.0, 86)
    rows: list[dict[str, float | str]] = []
    for muscle in PAIR_NAMES:
        name = f"{muscle}_r"
        patient_activation = interpolate_to_percent(
            patient_solution,
            activation_column(patient_solution, name),
            percent,
        )
        baseline_activation = interpolate_to_percent(
            baseline_solution,
            activation_column(baseline_solution, name),
            percent,
        )
        patient_force = interpolate_to_percent(
            patient_forces,
            force_column(patient_forces, name),
            percent,
        )
        baseline_force = interpolate_to_percent(
            baseline_forces,
            force_column(baseline_forces, name),
            percent,
        )
        rows.append(
            {
                "right_muscle_group": muscle,
                "patient_mean_activation": float(np.mean(patient_activation)),
                "template_mean_activation": float(np.mean(baseline_activation)),
                "delta_mean_activation": float(
                    np.mean(patient_activation - baseline_activation)
                ),
                "patient_peak_activation": float(np.max(patient_activation)),
                "template_peak_activation": float(np.max(baseline_activation)),
                "delta_peak_activation": float(
                    np.max(patient_activation) - np.max(baseline_activation)
                ),
                "patient_mean_force_n": float(np.mean(patient_force)),
                "template_mean_force_n": float(np.mean(baseline_force)),
                "delta_mean_force_n": float(
                    np.mean(patient_force - baseline_force)
                ),
                "patient_peak_force_n": float(np.max(patient_force)),
                "template_peak_force_n": float(np.max(baseline_force)),
                "delta_peak_force_n": float(
                    np.max(patient_force) - np.max(baseline_force)
                ),
            }
        )
    return pd.DataFrame(rows)


def plot_comparison(
    patient: pd.DataFrame,
    baseline: pd.DataFrame,
    kind: str,
    output_path: Path,
) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(14, 11), sharex=True)
    for axis, muscle in zip(axes.flat, PAIR_NAMES):
        name = f"{muscle}_r"
        patient_column = (
            activation_column(patient, name)
            if kind == "activation"
            else force_column(patient, name)
        )
        baseline_column = (
            activation_column(baseline, name)
            if kind == "activation"
            else force_column(baseline, name)
        )
        axis.plot(
            normalized_time(baseline),
            baseline[baseline_column],
            color="#5b6770",
            linestyle="--",
            label="matched template",
        )
        axis.plot(
            normalized_time(patient),
            patient[patient_column],
            color="#c44536",
            label="video-informed knee",
        )
        axis.axvspan(0, 10, color="#eeeeee", alpha=0.7)
        axis.axvspan(95, 100, color="#eeeeee", alpha=0.7)
        axis.set_title(muscle)
        axis.grid(alpha=0.22)
    axes[0, 0].legend(fontsize=8)
    for axis in axes[-1, :]:
        axis.set_xlabel("Analyzed right-swing step (%)")
    ylabel = "Activation (0-1)" if kind == "activation" else "Tendon force (N)"
    for axis in axes[:, 0]:
        axis.set_ylabel(ylabel)
    fig.suptitle(
        "Right-side Moco activation: video-informed vs matched template"
        if kind == "activation"
        else "Right-side Moco tendon force: video-informed vs matched template"
    )
    fig.tight_layout()
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def update_explanations(
    phenotype_path: Path,
    comparison: pd.DataFrame,
    output_path: Path,
) -> pd.DataFrame:
    phenotypes = pd.read_csv(phenotype_path)
    rows: list[dict[str, str]] = []
    knee_related = comparison[
        comparison["right_muscle_group"].isin(
            ["hamstrings", "bifemsh", "rect_fem", "vasti", "gastroc"]
        )
    ].copy()
    knee_related["magnitude"] = np.abs(knee_related["delta_mean_activation"])
    top = knee_related.sort_values("magnitude", ascending=False).head(3)
    activation_text = "; ".join(
        f"{row.right_muscle_group} dA={row.delta_mean_activation:+.3f}, "
        f"dF={row.delta_mean_force_n:+.1f} N"
        for row in top.itertuples()
    )
    for phenotype in phenotypes.itertuples():
        if phenotype.phenotype_id == "reduced_swing_knee_flexion":
            support = (
                "Counterfactual Moco sensitivity relative to a matched normal-knee "
                f"template: {activation_text}."
            )
            explanation = (
                "The reduced-knee-flexion trajectory changes the required knee "
                "flexor/extensor and plantar-flexor solution. These differences "
                "are model consequences, not proof of weakness or spasticity."
            )
            moco_scope = "tested_in_2d_counterfactual"
        elif phenotype.phenotype_id == "compensatory_foot_clearance":
            support = (
                "Not dynamically represented: the 2D model lacks pelvic hiking "
                "and hip ab/adduction."
            )
            explanation = (
                "Possible hip hiking, circumduction, or increased proximal flexion "
                "to clear the right foot."
            )
            moco_scope = "requires_3d_model"
        elif phenotype.phenotype_id == "lateral_trunk_lean":
            support = (
                "Not dynamically represented: the 2D model lacks frontal-plane "
                "trunk and hip-abductor mechanics."
            )
            explanation = (
                "Possible balance strategy, stance-limb unloading, or hip-abductor "
                "compensation."
            )
            moco_scope = "requires_3d_model"
        else:
            support = "Upper-limb muscles are absent from the current model."
            explanation = (
                "The hand-in-pocket behavior confounds arm-swing interpretation."
            )
            moco_scope = "not_tested"
        rows.append(
            {
                "movement_phenotype": phenotype.phenotype_id,
                "side": phenotype.side,
                "video_evidence": phenotype.video_evidence,
                "moco_result": support,
                "possible_explanation": explanation,
                "confidence": phenotype.confidence,
                "moco_scope": moco_scope,
                "clinical_claim": "screening_hypothesis_not_diagnosis",
            }
        )
    result = pd.DataFrame(rows)
    result.to_csv(output_path, index=False)
    return result


def write_markdown_report(
    explanations: pd.DataFrame,
    comparison: pd.DataFrame,
    kinematics: pd.DataFrame,
    solve_summary: pd.DataFrame,
    output_path: Path,
) -> None:
    selected = comparison[
        [
            "right_muscle_group",
            "delta_mean_activation",
            "delta_mean_force_n",
            "delta_peak_force_n",
        ]
    ].copy()
    with output_path.open("w", encoding="utf-8") as file:
        file.write("# Patient video phenotype and Moco report\n\n")
        file.write(
            "> Screening research output. The Moco analysis is a patient-informed "
            "2D counterfactual, not a patient-specific clinical measurement.\n\n"
        )
        file.write("## Moco solve status\n\n")
        file.write(solve_summary.to_markdown(index=False))
        file.write("\n\n")
        file.write("## Movement phenotypes and possible explanations\n\n")
        file.write(explanations.to_markdown(index=False))
        file.write("\n\n## Moco kinematic counterfactual\n\n")
        file.write(kinematics.to_markdown(index=False, floatfmt=".2f"))
        file.write("\n\n## Right-muscle sensitivity to reduced knee flexion\n\n")
        file.write(selected.to_markdown(index=False, floatfmt=".3f"))
        file.write(
            "\n\nThe first 10% and last 5% of the step are excluded from numerical "
            "summaries because unconstrained endpoint activations can contain "
            "boundary transients.\n"
        )


PHENOTYPE_ZH = {
    "reduced_swing_knee_flexion": "摆动期膝屈曲不足",
    "compensatory_foot_clearance": "疑似代偿性清足",
    "lateral_trunk_lean": "躯干侧倾",
    "reduced_arm_swing": "手臂摆动减少",
}
SIDE_ZH = {"right": "右侧", "left": "左侧", "bilateral": "双侧"}
CONFIDENCE_ZH = {"moderate": "中等", "low": "低", "high": "高"}


def muscle_value(
    comparison: pd.DataFrame,
    muscle: str,
    column: str,
) -> float:
    match = comparison.loc[
        comparison["right_muscle_group"] == muscle,
        column,
    ]
    return float(match.iloc[0]) if not match.empty else float("nan")


def build_functional_issue_rows(
    comparison: pd.DataFrame,
    kinematics: pd.DataFrame,
) -> list[dict[str, str]]:
    patient = kinematics.loc[
        kinematics["condition"] == "video_informed_right_knee"
    ].iloc[0]
    template = kinematics.loc[
        kinematics["condition"] == "matched_template_right_knee"
    ].iloc[0]
    tib_ant = muscle_value(comparison, "tib_ant", "delta_mean_activation")
    iliopsoas = muscle_value(comparison, "iliopsoas", "delta_mean_activation")
    vasti = muscle_value(comparison, "vasti", "delta_mean_activation")
    rect_fem = muscle_value(comparison, "rect_fem", "delta_mean_activation")
    gastroc = muscle_value(comparison, "gastroc", "delta_mean_activation")
    bifemsh = muscle_value(comparison, "bifemsh", "delta_mean_activation")
    return [
        {
            "可能的功能问题": "右侧选择性屈膝能力或关节间协调下降",
            "模型依据": (
                f"视频驱动右膝活动度为 {patient.knee_excursion_deg:.1f}°，"
                f"匹配模板为 {template.knee_excursion_deg:.1f}°；"
                f"股二头肌短头激活变化 {bifemsh:+.3f}。"
            ),
            "需要验证": "主动屈膝、腘绳肌肌力、Fugl-Meyer下肢项目和步态时相。",
        },
        {
            "可能的功能问题": "清足任务困难并采用近端/远端代偿",
            "模型依据": (
                f"胫骨前肌激活变化 {tib_ant:+.3f}，"
                f"髂腰肌激活变化 {iliopsoas:+.3f}；"
                "模型需要更多踝背屈与髋屈贡献完成摆腿。"
            ),
            "需要验证": "踝背屈主动ROM、足下垂、髋屈肌力及三维骨盆抬高/环转。",
        },
        {
            "可能的功能问题": "膝伸肌与跖屈肌需求偏高的僵硬膝候选模式",
            "模型依据": (
                f"vasti {vasti:+.3f}、股直肌 {rect_fem:+.3f}、"
                f"腓肠肌 {gastroc:+.3f}。"
            ),
            "需要验证": "股直肌和腓肠肌动态EMG、Tardieu、被动ROM及踝推蹬。",
        },
    ]


def write_chinese_report(
    explanations: pd.DataFrame,
    comparison: pd.DataFrame,
    kinematics: pd.DataFrame,
    solve_summary: pd.DataFrame,
    output_path: Path,
) -> None:
    functional_issues = build_functional_issue_rows(comparison, kinematics)
    selected = comparison[
        [
            "right_muscle_group",
            "delta_mean_activation",
            "delta_mean_force_n",
        ]
    ].copy()
    selected.columns = ["右侧肌群", "平均激活变化", "平均肌腱力变化_N"]

    with output_path.open("w", encoding="utf-8") as file:
        file.write("# 患者视频与 Moco 中文分析报告\n\n")
        file.write(
            "> 本结果用于算法研发和康复筛查，不是临床诊断、实测 EMG "
            "或患者真实绝对肌力。单目视频和通用二维模型不能唯一辨识神经病理机制。\n\n"
        )
        file.write("## 分析流程\n\n")
        file.write(
            "视频输入 → MediaPipe 姿态点 → 步态表型 → "
            "视频驱动与匹配模板的 Moco 对照 → 功能问题假设。\n\n"
        )
        file.write("## 视频动作表型\n\n")
        file.write("| 动作表型 | 侧别 | 视频证据 | 置信度 |\n")
        file.write("|---|---|---|---|\n")
        for row in explanations.itertuples():
            file.write(
                f"| {PHENOTYPE_ZH.get(row.movement_phenotype, row.movement_phenotype)} "
                f"| {SIDE_ZH.get(row.side, row.side)} "
                f"| {row.video_evidence} "
                f"| {CONFIDENCE_ZH.get(row.confidence, row.confidence)} |\n"
            )

        file.write("\n## 可能的功能问题\n\n")
        file.write("| 功能问题假设 | 模型依据 | 康复师需要验证 |\n")
        file.write("|---|---|---|\n")
        for row in functional_issues:
            file.write(
                f"| {row['可能的功能问题']} | {row['模型依据']} "
                f"| {row['需要验证']} |\n"
            )

        file.write("\n## Moco 求解状态\n\n")
        file.write(solve_summary.to_markdown(index=False))
        file.write("\n\n## 右侧肌肉激活和肌力敏感性\n\n")
        file.write(selected.to_markdown(index=False, floatfmt=".3f"))
        file.write("\n\n")
        file.write(
            "这里的变化均为“视频驱动低屈膝条件减去匹配模板条件”。"
            "数值汇总排除了步态段最初 10% 和最后 5% 的边界瞬态。\n\n"
        )
        file.write("![Moco肌肉激活对照](moco_activation_patient_vs_template.png)\n\n")
        file.write("![Moco肌肉力对照](moco_force_patient_vs_template.png)\n\n")
        file.write("## 临床边界\n\n")
        file.write(
            "- 当前模型只有 18 条二维下肢肌肉，不代表人体全部肌肉。\n"
            "- 激活变化是优化模型的动力学解释，不是患者实测神经激活。\n"
            "- 肌力变化受肌肉长度、速度、被动力和通用模型参数影响。\n"
            "- 痉挛、肌无力、挛缩和选择性运动控制障碍必须通过临床检查区分。\n"
            "- 康复方案应结合主动/被动 ROM、肌力、Tardieu/MAS、感觉、"
            "平衡、疼痛和患者目标。\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patient-dir", required=True, type=Path)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--phenotypes", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    patient_solution = table_to_dataframe(
        args.patient_dir / "patient_informed_moco_solution.sto"
    )
    patient_forces = table_to_dataframe(
        args.patient_dir / "patient_informed_muscle_tendon_forces.sto"
    )
    baseline_solution = table_to_dataframe(
        args.baseline_dir / "patient_informed_moco_solution.sto"
    )
    baseline_forces = table_to_dataframe(
        args.baseline_dir / "patient_informed_muscle_tendon_forces.sto"
    )
    patient_metadata = read_storage_metadata(
        args.patient_dir / "patient_informed_moco_solution.sto"
    )
    baseline_metadata = read_storage_metadata(
        args.baseline_dir / "patient_informed_moco_solution.sto"
    )
    solve_summary = pd.DataFrame(
        [
            {
                "condition": "video_informed_right_knee",
                "status": patient_metadata.get("status", "unknown"),
                "iterations": patient_metadata.get("num_iterations", ""),
                "objective": patient_metadata.get("objective", ""),
                "state_tracking": patient_metadata.get(
                    "objective_state_tracking", ""
                ),
                "control_effort": patient_metadata.get(
                    "objective_control_effort", ""
                ),
                "solver_duration_s": patient_metadata.get("solver_duration", ""),
            },
            {
                "condition": "matched_template_right_knee",
                "status": baseline_metadata.get("status", "unknown"),
                "iterations": baseline_metadata.get("num_iterations", ""),
                "objective": baseline_metadata.get("objective", ""),
                "state_tracking": baseline_metadata.get(
                    "objective_state_tracking", ""
                ),
                "control_effort": baseline_metadata.get(
                    "objective_control_effort", ""
                ),
                "solver_duration_s": baseline_metadata.get("solver_duration", ""),
            },
        ]
    )
    solve_summary.to_csv(
        args.output_dir / "moco_solve_summary.csv", index=False
    )
    comparison = compare_conditions(
        patient_solution,
        patient_forces,
        baseline_solution,
        baseline_forces,
    )
    comparison.to_csv(
        args.output_dir / "moco_patient_vs_template_summary.csv", index=False
    )
    percent = np.linspace(10.0, 95.0, 86)
    knee_column = "/jointset/knee_r/knee_angle_r/value"
    patient_knee = -np.degrees(
        interpolate_to_percent(patient_solution, knee_column, percent)
    )
    baseline_knee = -np.degrees(
        interpolate_to_percent(baseline_solution, knee_column, percent)
    )
    kinematics = pd.DataFrame(
        [
            {
                "condition": "video_informed_right_knee",
                "min_knee_flexion_deg": float(np.min(patient_knee)),
                "max_knee_flexion_deg": float(np.max(patient_knee)),
                "knee_excursion_deg": float(np.ptp(patient_knee)),
            },
            {
                "condition": "matched_template_right_knee",
                "min_knee_flexion_deg": float(np.min(baseline_knee)),
                "max_knee_flexion_deg": float(np.max(baseline_knee)),
                "knee_excursion_deg": float(np.ptp(baseline_knee)),
            },
        ]
    )
    kinematics.to_csv(
        args.output_dir / "moco_kinematic_comparison.csv", index=False
    )
    explanations = update_explanations(
        args.phenotypes,
        comparison,
        args.output_dir / "phenotype_moco_explanations.csv",
    )
    plot_comparison(
        patient_solution,
        baseline_solution,
        "activation",
        args.output_dir / "moco_activation_patient_vs_template.png",
    )
    plot_comparison(
        patient_forces,
        baseline_forces,
        "force",
        args.output_dir / "moco_force_patient_vs_template.png",
    )
    write_markdown_report(
        explanations,
        comparison,
        kinematics,
        solve_summary,
        args.output_dir / "patient_video_moco_report.md",
    )
    write_chinese_report(
        explanations,
        comparison,
        kinematics,
        solve_summary,
        args.output_dir / "患者视频_Moco分析报告.md",
    )
    print(explanations.to_string(index=False))
    print(f"Wrote comparison outputs to {args.output_dir}")


if __name__ == "__main__":
    main()

