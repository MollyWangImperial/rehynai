# Video-to-Moco Rehabilitation Screening

Research pipeline that accepts a walking video and produces:

- MediaPipe pose landmarks and tracking-quality plots;
- interpretable movement-phenotype screening;
- video-informed and matched-template OpenSim Moco solves;
- muscle-activation and tendon-force comparison plots;
- a Chinese report named `患者视频_Moco分析报告.md`;
- possible functional issues and the clinical checks required to verify them.

## Quick start

Create the environment:

```powershell
conda env create -f environment.yml
conda activate moco-video-analysis
```

Run the complete pipeline. The video is the only required input:

```powershell
python run_video_pipeline.py `
  --video "D:\path\to\patient_walking.mp4" `
  --output-dir ".\outputs\patient_001"
```

The main outputs are:

```text
outputs/patient_001/report/患者视频_Moco分析报告.md
outputs/patient_001/report/moco_activation_patient_vs_template.png
outputs/patient_001/report/moco_force_patient_vs_template.png
outputs/patient_001/report/phenotype_moco_explanations.csv
```

The runner downloads two pinned OpenSim Moco example assets when they are not
already available locally. To use a patient-scaled model instead:

```powershell
python run_video_pipeline.py `
  --video "D:\path\to\patient_walking.mp4" `
  --model "D:\path\to\scaled_patient_model.osim" `
  --generic-reference "D:\path\to\reference_coordinates.sto" `
  --output-dir ".\outputs\patient_001"
```

## Pipeline

1. `extract_mediapipe_pose.py` converts video frames to image and world pose
   landmarks.
2. `analyze_patient_video.py` removes the turning interval, separates straight
   walking passes, detects swing events, and calculates knee-flexion,
   foot-clearance, lateral-ankle, trunk-lean, and arm-swing features.
3. `run_patient_informed_moco.py` constructs a video-informed right-swing
   half-step and solves the 18-muscle 2D Moco tracking problem.
4. The same script solves a cadence-matched generic-knee condition.
5. `compare_patient_moco.py` compares the two conditions and generates the
   Chinese report, including possible functional problems and clinical
   verification items.

The comparison excludes the first 10% and final 5% of the modeled step from
numerical summaries to avoid unconstrained endpoint activation transients.

## Individual stages

Each stage can also be run separately:

```powershell
python extract_mediapipe_pose.py `
  --video "D:\path\to\patient_walking.mp4" `
  --output-dir ".\outputs\patient_001\pose"

python analyze_patient_video.py `
  --video "D:\path\to\patient_walking.mp4" `
  --landmarks ".\outputs\patient_001\pose\mediapipe_pose_landmarks.csv" `
  --output-dir ".\outputs\patient_001\phenotypes"
```

See `run_video_pipeline.py` for the exact Moco and report commands.

## Interpretation boundary

This pipeline deliberately separates:

- direct video observations;
- model-dependent biomechanical explanations;
- clinical diagnoses that require therapist examination.

A single-view phone video cannot provide calibrated patient-specific 3D
kinematics, ground-reaction forces, EMG, muscle strength, or passive joint
properties. The included model is a generic 62 kg, sagittal-plane model with 18
lower-limb muscles. Its activation and force differences are counterfactual
model sensitivities, not measured patient EMG or absolute patient muscle force.

The report may support hypotheses such as reduced selective knee flexion,
inter-joint coordination difficulty, or a compensatory foot-clearance strategy.
It must not be used alone to diagnose weakness, spasticity, contracture, or a
neurological lesion.

## Patient privacy

Videos, frame images, pose landmarks, and generated reports are ignored by
Git. Do not commit identifiable patient data. Obtain appropriate consent and
follow local clinical-data governance requirements.

## Third-party assets

The default example model and reference coordinates come from the official
OpenSim Moco repository at a pinned commit. See
[`THIRD_PARTY_NOTICE.md`](THIRD_PARTY_NOTICE.md).

