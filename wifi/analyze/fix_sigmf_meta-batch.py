#!/usr/bin/env python3
import argparse, json, re, time
from pathlib import Path
from typing import Optional, Tuple

def infer_from_json(basename: Path) -> Optional[Tuple[float, float]]:
    """Try sidecar .json with same basename."""
    js = basename.with_suffix(".json")
    if not js.exists():
        return None
    try:
        m = json.loads(js.read_text(encoding="utf-8"))
        sr = float(m.get("sample_rate"))
        cf = float(m.get("center_hz"))
        return cf, sr
    except Exception:
        return None

def infer_from_name(p: Path) -> Optional[Tuple[float, float]]:
    """Try filename patterns for center and rate."""
    s = p.name

    # Pattern 1: ..._<center>Hz_<rate>sps_...
    m = re.search(r"(?P<center>\d{7,})Hz_(?P<rate>\d{6,})sps", s)
    if m:
        return float(m.group("center")), float(m.group("rate"))

    # Pattern 2: ..._<center>_<epoch>... with 10+ digits for center
    m2 = re.search(r"_(?P<center>\d{9,})_", s)
    if m2:
        # rate not found
        return float(m2.group("center")), None

    # Pattern 3: ..._(ch\d+_)?(?P<center>\d{9,})\.(sigmf-data)$
    m3 = re.search(r"(?:ch\d+_)?(?P<center>\d{9,})\.sigmf-data$", s)
    if m3:
        return float(m3.group("center")), None

    return None

def write_meta(meta_path: Path, center: float, rate: float, author: str, desc: str):
    meta = {
        "global": {
            "core:datatype": "cf32_le",
            "core:sample_rate": float(rate),
            "core:version": "1.0.0",
            "core:description": desc,
            "core:author": author,
            "core:hw": "LimeSDR-Mini v2",
            "core:dataset": meta_path.with_suffix(".sigmf-data").name,
            "core:recording_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        },
        "captures": [
            {
                "core:sample_start": 0,
                "core:frequency": float(center)
            }
        ],
        "annotations": []
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser(description="Batch-generate .sigmf-meta for all .sigmf-data that are missing meta.")
    ap.add_argument("root", help="Folder to scan")
    ap.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    ap.add_argument("--default-rate", type=float, help="Fallback sample rate (Hz) if not inferrable")
    ap.add_argument("--default-center", type=float, help="Fallback center (Hz) if not inferrable")
    ap.add_argument("--author", default="wofl", help="Author field")
    ap.add_argument("--desc", default="auto-generated meta (batch)", help="Description field")
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    pattern = "**/*.sigmf-data" if args.recursive else "*.sigmf-data"

    made, skipped, exist = 0, 0, 0
    for data_path in root.glob(pattern):
        base = data_path.with_suffix("")
        meta_path = base.with_suffix(".sigmf-meta")
        if meta_path.exists():
            exist += 1
            continue

        cf_sr = infer_from_json(base)
        if cf_sr is None:
            cf_sr = infer_from_name(data_path)

        center = None
        rate = None
        if cf_sr is not None:
            center, rate = cf_sr

        if center is None:
            center = args.default_center
        if rate is None:
            rate = args.default_rate

        if center is None or rate is None:
            print(f"[skip] cannot infer center/rate for {data_path.name} (use --default-center/--default-rate)")
            skipped += 1
            continue

        try:
            write_meta(meta_path, center, rate, args.author, args.desc)
            print(f"[ok] wrote {meta_path.name}  (center={center:.0f} Hz, rate={rate:.0f} Hz)")
            made += 1
        except Exception as e:
            print(f"[err] {data_path.name}: {e}")
            skipped += 1

    print(f"\nDone. created={made}, skipped={skipped}, already-existed={exist}")

if __name__ == "__main__":
    main()
