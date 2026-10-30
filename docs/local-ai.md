# Local AI decision for the 4 GB Pi

The detector already runs locally. Keep YOLO26n/OpenCV responsible for image
boxes, ByteTrack for temporary associations, and the small calibration routines
for curb-row geometry. Learning geometry from observations is different from
training neural-network weights.

A text model such as Qwen could later summarize structured observations or answer
questions about a bounded event history. It cannot inspect camera images by
itself. A vision-language model is a different, generally heavier workload; it
also cannot establish the contents of areas hidden by branches or unseen curb.

The official [Qwen3-0.6B GGUF model](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF)
is a 0.6-billion-parameter causal language model supported by llama.cpp. Its
published Q8_0 [weight file](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/tree/main)
is approximately **639 MB**, versus **9.48 MiB** for our YOLO26n ONNX. RAM also
needs the runtime, compute buffers and context cache; weight size is not peak
RAM. No Qwen weights, Ollama, llama.cpp or training dependencies were installed.
No Qwen tokens/second or latency result has been measured on this Pi.

Recommendation for this project: keep notification wording deterministic for now.
An optional on-demand text summarizer should earn its extra memory and CPU with
a measured improvement over those templates. Avoid running it on every frame.
If tested later, start with one small quantized file, one CPU thread, a context
of at most 1,024 tokens and short outputs; unload when idle. Measure load time,
peak combined RSS, first-token/total latency, disk use, swap, camera frame age
and factual errors against the same events without a language model. These are
proposed test limits, not a demonstrated performance guarantee.

For custom detection, first collect a small, explicitly labelled local dataset
covering the changing camera angle, day/night conditions, reflections and
occlusion. Split by scene/time so near-identical frames do not leak into held-out
evaluation. Keep collection bounded and private. Fine-tune on a separate capable
machine, export one compact model and run the same size/speed/accuracy comparison
on the Pi before replacing anything. The Pi's 4 GB shared with capture and the
phone bridge is a poor place for the training stack. User-confirmed corrections
are more useful than treating the detector's own guesses as ground truth.
