"""Load a dataset config (YAML). Everything dataset-specific lives there, not in code."""

from pathlib import Path

import yaml


def load(path):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg["_path"] = str(path)
    cfg["output_dir"] = Path(cfg["output_dir"])
    return cfg


def in_bbox(lat, lon, bbox):
    """bbox = [lon_min, lat_min, lon_max, lat_max]; None means no spatial filter."""
    if bbox is None:
        return True
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]
