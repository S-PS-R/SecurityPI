# First training-image batch

The initial batch collects one raw camera image every two hours. It stops at
12 images or 24 hours after its first image, whichever happens first. The first
image is collected immediately. Normal timing produces 12 images over 22 hours;
the 24-hour cutoff prevents an interrupted run from continuing across more days.

Collection reuses the analyzer's existing frame. It opens no additional camera,
runs no additional detector and saves no green boxes or text into training images.
JPEG quality is 85. No training framework or model weights are installed.

```toml
[dataset]
enabled = true
interval_hours = 2.0
duration_hours = 24.0
max_images = 12
max_mib = 100
```

The feature defaults to disabled in the portable example. It runs while the
existing analyzer is running. Capture timing and completion survive worker
restarts; a completed batch never restarts itself. If the camera is offline,
missed samples are not backfilled and the original deadline is not extended.
The storage budget is an additional stop condition. Existing images and manual
reviews are preserved when any limit is reached.

Ignored local files live under `data/training/`:

- Timestamped `.jpg`: unannotated camera image, with the configured orientation.
- Timestamped `.json`: capture metadata, unverified model suggestions and a review.
- `collection.json`: counts, budget, next capture and batch start/end/completion.
- `review.md`: local image links and review states.
- `review-progress.json`: scheduled review progress and summary state.

Model suggestions are not ground truth. Assistant review can add identifiable
objects the detector missed, but ambiguous tree-covered regions stay flagged.
Boxes use normalized xyxy coordinates and the existing COCO class IDs. Reviews
remain `approved_for_training: false`; there is no automatic label export,
training, deployment or public upload. Images of unchanged parking locations
must not be treated as evidence that a car is present.

The one-day Codex review follow-up inspects new images every two hours. It stays
quiet during routine progress, reports meaningful failures, and gives one final
batch summary before pausing itself. It must not start a second batch. A future
batch requires an explicit new request and deliberate handling of the old data.
