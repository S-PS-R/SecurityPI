# SecurityPI training and evaluation plan

Prepared November 2, 2026. This is a bounded pilot, not an accuracy claim or an
automatic model deployment. Use the user's Windows 11 / i7-12700K / RTX 3060
computer for training. Its dedicated GPU memory is 12 GB; shared system memory
does not increase that dedicated VRAM budget. No training software is installed
on the Pi and the existing model remains active.

## Prepared data

- Training: 11 human-approved raw 1280×720 JPEGs, 39 car boxes, one person box and
  one user-approved truncated bicycle-tire box. The glare-obscured image is excluded.
- Full frames retained as requested. No review boxes/text are burned into inputs.
- YOLO labels use normalized center-x, center-y, width, height. Original COCO
  IDs and all 80 class names remain unchanged: person=0, bicycle=1, car=2.
- Occlusion/truncation, raw/review/label hashes and timestamps live in the manifest.
- All 11 pilot frames stay in training. Validation and test directories are
  deliberately empty; `training_ready` is false, not papered over by train=val.
- Private data stays under ignored `data/`. Transfer directly to the user's own
  computer, not to a public GitHub repository or hosted training service.

The [official dataset format](https://docs.ultralytics.com/datasets/detect/) supports
these labels. The dataset YAML omits `path`, so split paths resolve relative to
the YAML itself, including after extraction on Windows. Source:
[Ultralytics path resolution](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/data/utils.py).

Reproduce the private export from the repository, using a new output directory:

```bash
.venv/bin/python -m securitypi.training_export \
  --source data/training --output data/training-exports/pilot-v1 \
  --plan docs/training-plan.md --recipe deploy/training/rtx3060.yaml
```

This rejects pending reviews, changed approved boxes, invalid coordinates,
escaping image names, corrupt/wrong-size JPEGs and existing output directories.
It excludes preview images, secrets, weights and the rejected glare sample.
`SHA256SUMS` and a private ZIP accompany the export. No model/camera worker runs.

## Evaluation split: avoid learning the answers

These frames repeatedly show the same curb and parked cars. An 80/20 random
split would overstate generalization. Keep this entire camera-day pilot together.
Treat a parked vehicle's continuous stay and each pedestrian passage as a group;
neither adjacent frames, crops nor augmentations of one group cross splits.
A new day alone is insufficient if the same parked vehicles remain: inspect
vehicle/event overlap manually before assigning the split. Group assignments
must be recorded alongside image hashes.

Five existing, widely spaced person-event snapshots from November 2 are staged
privately as **validation candidates only**. Their originals and housekeeping are
untouched. No labels or validation approval are inferred from their track names.
They must be visually graded before use. Triggered snapshots are biased toward
what the current detector already notices; they are not a representative test.

Before a serious training run:

1. Grade independent validation examples. Start with those five candidates;
   aim for at least 30 frames across changed vehicles and lighting. This is a
   practical pilot target, not a statistical sample-size guarantee.
2. Reserve a separate, untouched test set, ideally at least 30 additional frames
   from other vehicle/event groups and sessions: visible and occluded cars,
   people, passing vehicles and empty/background scenes. Include at least 20
   occluded-car instances and 10 person instances if available; report actual
   denominators and any unmet coverage. Static frames cannot test track timing.
3. No new automatic collection has been started. A new finite collection or
   physical walk-through needs its own instruction. Existing snapshot candidates
   do not provide unbiased negative or missed-person examples.
4. Before promoting a person-alert model, add a bounded, fully labeled replay
   subset for people and the supported vehicle classes to training on the PC.
   One person label cannot protect person recall. Initially target roughly equal
   numbers of street and replay frames, not an enormous COCO download. Replay
   images belong to training only; keep their licenses/provenance and avoid
   test overlap. No replay data has been downloaded yet.

An experimental fine-tune may begin once independent validation is reviewed and
its GPU environment works. Without replay or sufficient test coverage it remains
an exploratory candidate, never an automatic replacement. Do not select a model
using the locked test set. A future fixed-view success also does not establish
performance after moving the camera.

## Windows GPU setup, not Pi setup

Use a dedicated Python 3.12 environment on the PC. The proposed paired CUDA 12.6
wheels below are listed for Windows by
[PyTorch's official installation table](https://pytorch.org/get-started/previous-versions/).
Check the installed NVIDIA driver and CUDA availability before training. The
wheel supplies its runtime; installing the full CUDA toolkit is not the first step.

PowerShell, in a new private working directory on the PC:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install ultralytics==8.4.198 onnx==1.23.2 onnxruntime==1.31.1
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -c "import torch; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0)); print(round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2))"
.\.venv\Scripts\python.exe -m pip freeze > environment-lock.txt
```

Versions are a proposed starting environment, not tested on this user's PC yet.
Check Python/driver compatibility and keep the resulting lock file with the run.
Training dependencies may use several GB on the PC. Keep installation caches and
training outputs off the Pi. No cloud upload is needed.

## First training experiment

Fine-tune the official COCO-pretrained **YOLO26n `.pt` checkpoint** on the PC.
The deployed `.onnx` inference file is not a trainable PyTorch checkpoint.
Keep the same nano architecture and 80-class head; do not renumber car to zero.
Class filtering at inference does not turn the head into a two-class model.
[Official training/checkpoint documentation](https://docs.ultralytics.com/modes/train/).

Proposed settings are in `deploy/training/rtx3060.yaml`: 640-pixel input, batch 8,
workers 0 for an uncomplicated Windows start, 20 epochs maximum, seed 20261102,
first 10 modules frozen, explicitly selected AdamW at 0.0001 learning rate,
early stopping on validation, no mosaic/mixup/cutmix, mild brightness/scale changes.
Verify the freeze list and unchanged 80-class head in the training startup log.
These are conservative starting hypotheses, not empirically optimal settings.
[Configuration reference](https://docs.ultralytics.com/usage/cfg/).

After real validation data is present, copy the config beside `dataset.yaml`, then:

```powershell
.\.venv\Scripts\yolo.exe detect train cfg=rtx3060.yaml
```

If VRAM is insufficient, reduce batch to 4, preserving input size. Keep only
best/last checkpoints, metrics, config, environment lock and model hashes. Do not
launch a parameter sweep on this tiny pilot. Freeze the experiment recipe before
using the test set. Check the pretrained checkpoint hash and record its source.

## Export and acceptance

Export the selected checkpoint as a separate FP32 ONNX candidate, never overwrite
the pinned baseline. Fixed batch=1, 640×640, dynamic=false, NMS-free head selected
with nms=false, simplify=false initially, opset=17. The Pi expects one float32
`[1,3,640,640]` input and one output; YOLO26's six-column output must preserve
COCO IDs. Recheck the output contract, don't infer it from the filename.
[Export arguments](https://docs.ultralytics.com/modes/export/).

```powershell
.\.venv\Scripts\yolo.exe export model=runs/securitypi/pilot-01/weights/best.pt format=onnx imgsz=640 batch=1 dynamic=False nms=False simplify=False opset=17 device=cpu
```

Use identical raw inputs, hashes, thresholds and preprocessing for baseline and
candidate. Ultralytics' default padding differs from SecurityPI's top-left square
letterbox: acceptance runs must use SecurityPI's actual `Detector`, not just a
desktop preview. Compare PyTorch/ONNX box agreement as an additional export check.

| Check | Predeclared pilot gate |
|---|---|
| Occluded cars | Higher recall at IoU≥0.5 and confidence 0.15; show TP/FP/FN and denominators. Also report at IoU≥0.75 because coarse approved boxes can affect IoU. |
| Visible cars / people | No additional misses in the locked pilot set; insufficient instances means inconclusive, not passing. |
| False positives | No increase on the fixed test images; additionally measure false notifications/hour on a bounded negative/live test before promotion. |
| Broad quality | Per-class AP50/AP50–95 on the GPU toolchain, with sample counts. This is distinct from SecurityPI's fixed-threshold precision/recall helper. |
| CPU speed | Same Pi ORT version, 2 threads, 640 input, settings and comparable temperature; warm up, ≥30 repeated timings/image, sequential models. Candidate p95 latency ≤baseline×1.10. |
| Memory/size | Peak service RAM ≤baseline+32 MiB and within existing service cap; candidate ≤12 MiB for the first same-architecture trial. No extra runtime. |
| Live behavior | Fresh frames, stable camera release, HA API/camera, person tracking/10-second alerts and snapshot thresholds regressions. Phone receipt only after user confirms. |

Benchmark models sequentially, with any conflicting analyzer paused and reliably
restored; never start another camera worker. Isolated synthetic tests send no real
phone messages. Keep only one candidate on the Pi, baseline for rollback, and a
small Markdown/JSON result. Quantization or a smaller model is a separate measured
experiment after accuracy/export parity, not combined with the first fine-tune.

## Current readiness

Export and Windows recipe prepared. Training is not started. Missing: GPU/driver
verification on the PC, reviewed independent validation, locked test coverage and
person replay before any production promotion. All private candidate data stays
local until transferred directly by the user.
