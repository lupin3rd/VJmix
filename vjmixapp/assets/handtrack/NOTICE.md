Hand-tracking model notices
===========================

The two `.onnx` files in this directory are THIRD-PARTY works distributed with
VJmix, not part of it:

  palm_detection_mediapipe_2023feb.onnx
  handpose_estimation_mediapipe_2023feb.onnx

Copyright 2023 OpenCV. They are the OpenCV Zoo releases of February 2023,
converted from the MediaPipe Hands model bundle (Copyright Google LLC).

Licence: Apache License, Version 2.0
- full text: ../../../licenses/Apache-2.0.txt (repository root `licenses/`;
  the AppImage ships the same directory at `opt/vjmix/licenses/`)
- the inventory of every third-party component: ../../../THIRD_PARTY_LICENSES.md

Modifications: none by VJmix. The files are used unmodified; VJmix only reads
them with onnxruntime's CPUExecutionProvider. The TFLite -> ONNX conversion was
performed by the OpenCV Zoo project, not by VJmix.

The preprocessing and postprocessing in `vjmixapp/handio.py` is VJmix's own port
to numpy + Pillow of the OpenCV Zoo demo logic (no OpenCV); it is original work
under VJmix's GPL-3.0, not a copy of the demo code.

Sources
-------
- https://huggingface.co/opencv/palm_detection_mediapipe
- https://huggingface.co/opencv/handpose_estimation_mediapipe
- https://github.com/opencv/opencv_zoo/tree/main/models/palm_detection_mediapipe
- https://github.com/opencv/opencv_zoo/tree/main/models/handpose_estimation_mediapipe
- MediaPipe Hands model bundle: https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker
