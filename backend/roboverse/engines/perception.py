"""AI / perception lab modules operating on simulated sensor data.

Outputs are always kept separate from ground truth and scored against it.
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess

import numpy as np


def cluster_scan(x: float, y: float, th: float, angles: np.ndarray, ranges: np.ndarray, r_max: float,
                 gap: float = 0.25, min_pts: int = 2) -> list[dict]:
    """Euclidean clustering of a 2D scan -> detected objects in the world frame (estimated pose)."""
    valid = ranges < r_max - 1e-3
    pts = np.stack([x + ranges * np.cos(th + angles), y + ranges * np.sin(th + angles)], axis=1)[valid]
    if len(pts) == 0:
        return []
    clusters, cur = [], [pts[0]]
    for p in pts[1:]:
        if np.linalg.norm(p - cur[-1]) < gap:
            cur.append(p)
        else:
            clusters.append(cur)
            cur = [p]
    clusters.append(cur)
    if len(clusters) > 1 and np.linalg.norm(clusters[0][0] - clusters[-1][-1]) < gap:
        clusters[0] = clusters[-1] + clusters[0]
        clusters.pop()
    out = []
    for c in clusters:
        if len(c) < min_pts:
            continue
        a = np.array(c)
        ctr = a.mean(axis=0)
        out.append({"x": float(ctr[0]), "y": float(ctr[1]), "points": len(c),
                    "extent": float(np.max(np.linalg.norm(a - ctr, axis=1)))})
    return out


def score_detections(detections: list[dict], truth: list[dict], match_dist: float = 0.6) -> dict:
    """Greedy nearest matching of detected clusters to ground-truth obstacle surfaces within sensor range."""
    used = set()
    tp, errs = 0, []
    for d in detections:
        best, bi = math.inf, None
        for i, t in enumerate(truth):
            if i in used:
                continue
            dist = max(0.0, math.hypot(d["x"] - t["x"], d["y"] - t["y"]) - t.get("radius", 0.0))
            if dist < best:
                best, bi = dist, i
        if bi is not None and best < match_dist:
            used.add(bi)
            tp += 1
            errs.append(best)
    fp = len(detections) - tp
    fn = len(truth) - tp
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
            "mean_position_error_m": float(np.mean(errs)) if errs else None,
            "note": "Perception output vs. simulator ground truth; detections use the estimated (not true) pose."}


def zscore_anomalies(series: list[float], window: int = 50, threshold: float = 4.0) -> list[int]:
    """Indices whose value deviates > threshold sigmas from the trailing window (simple anomaly detector)."""
    x = np.asarray(series, dtype=float)
    idx = []
    for i in range(window, len(x)):
        w = x[i - window:i]
        sd = w.std()
        if sd > 1e-9 and abs(x[i] - w.mean()) > threshold * sd:
            idx.append(i)
    return idx


def compute_capabilities() -> dict:
    """CPU/GPU detection. Never assumes a GPU exists."""
    info = {"cpu_count": os.cpu_count(), "gpu": None, "cuda": False, "opencv": False, "open3d": False, "torch": False}
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0 and out.stdout.strip():
                info["gpu"] = out.stdout.strip().splitlines()
                info["cuda"] = True
        except (OSError, subprocess.TimeoutExpired):
            pass
    for mod, key in (("cv2", "opencv"), ("open3d", "open3d"), ("torch", "torch")):
        try:
            __import__(mod)
            info[key] = True
        except ImportError:
            pass
    return info
