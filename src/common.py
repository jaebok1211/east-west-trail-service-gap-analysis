from __future__ import annotations

import io
import os
import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


def nfc(value: object) -> str:
    return unicodedata.normalize("NFC", str(value))


def find_file(root: Path, keywords: Iterable[str], suffix: str | None = None) -> Path:
    keys = [nfc(k) for k in keywords]
    candidates: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        name = nfc(p.name)
        if suffix and not name.lower().endswith(suffix.lower()):
            continue
        if all(k in name for k in keys):
            candidates.append(p)
    if not candidates:
        raise FileNotFoundError(f"파일을 찾지 못했습니다: keywords={keys}, suffix={suffix}, root={root}")
    candidates.sort(key=lambda p: (len(p.parts), len(p.name)))
    return candidates[0]


def read_csv_robust(path: Path, **kwargs) -> pd.DataFrame:
    errors: list[str] = []
    for enc in ("cp949", "euc-kr", "utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc, encoding_errors="ignore", low_memory=False, **kwargs)
        except Exception as exc:
            errors.append(f"{enc}: {exc}")
    raise RuntimeError(f"CSV 읽기 실패: {path}\n" + "\n".join(errors))


def read_csv_bytes(data: bytes, **kwargs) -> pd.DataFrame:
    errors: list[str] = []
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(data), encoding=enc, encoding_errors="ignore", low_memory=False, **kwargs)
        except Exception as exc:
            errors.append(f"{enc}: {exc}")
    raise RuntimeError("ZIP 내부 CSV 읽기 실패\n" + "\n".join(errors))


def normalize_key(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", nfc(value)).lower()


def weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return float("nan")
    return float(np.average(values[mask].astype(float), weights=weights[mask].astype(float)))


def weighted_median(values: pd.Series, weights: pd.Series) -> float:
    mask = values.notna() & weights.notna() & (weights > 0)
    if not mask.any():
        return float("nan")
    v = values[mask].astype(float).to_numpy()
    w = weights[mask].astype(float).to_numpy()
    order = np.argsort(v)
    v = v[order]
    w = w[order]
    cutoff = w.sum() / 2
    return float(v[np.searchsorted(np.cumsum(w), cutoff, side="left")])


def haversine_km(lon: float, lat: float, lons: np.ndarray, lats: np.ndarray) -> np.ndarray:
    r = 6371.0088
    lon1 = np.radians(float(lon))
    lat1 = np.radians(float(lat))
    lon2 = np.radians(lons.astype(float))
    lat2 = np.radians(lats.astype(float))
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def parse_combined_gpx(path: Path) -> list[list[tuple[float, float]]]:
    root = ET.parse(path).getroot()
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    tracks: list[list[tuple[float, float]]] = []
    for trk in root.findall("g:trk", ns):
        points: list[tuple[float, float]] = []
        for pt in trk.findall(".//g:trkpt", ns):
            points.append((float(pt.attrib["lon"]), float(pt.attrib["lat"])))
        if points:
            tracks.append(points)
    if not tracks:
        raise ValueError(f"GPX 트랙이 없습니다: {path}")
    return tracks


def geodesic_track_length_km(points: list[tuple[float, float]]) -> float:
    if len(points) < 2:
        return 0.0
    arr = np.asarray(points, dtype=float)
    total = 0.0
    for i in range(len(arr) - 1):
        total += float(haversine_km(arr[i, 0], arr[i, 1], np.array([arr[i + 1, 0]]), np.array([arr[i + 1, 1]]))[0])
    return total


def extract_nested_zip_csv(outer_zip: Path) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    with zipfile.ZipFile(outer_zip) as z:
        for outer_name in z.namelist():
            blob = z.read(outer_name)
            try:
                with zipfile.ZipFile(io.BytesIO(blob)) as nested:
                    for inner_name in nested.namelist():
                        if nfc(inner_name).lower().endswith(".csv"):
                            result[nfc(inner_name)] = read_csv_bytes(nested.read(inner_name))
            except zipfile.BadZipFile:
                if nfc(outer_name).lower().endswith(".csv"):
                    result[nfc(outer_name)] = read_csv_bytes(blob)
    return result

