# ByteTrack core

Source: https://github.com/ifzhang/ByteTrack/tree/d1bf0191adff59bc8fcfeaa0b33d3d1642552a99/yolox/tracker
MIT license retained in LICENSE.

Only tracker/Kalman/base classes are retained. Changes: NumPy 2 dtype compatibility;
remove unused training imports and tensor input branch; NumPy solves instead of
SciPy; bound removed-track history to the current update. Matching uses lapx and
vectorized NumPy IoU (continuous xyxy coordinates), avoiding SciPy/cython_bbox.
No detection model, training framework, or upstream demos are vendored.
