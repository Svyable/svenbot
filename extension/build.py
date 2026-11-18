"""Reproducible stdlib-only Chrome MV3 companion zip builder."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent / "companion"
FILES = ["manifest.json", "background.js", "reader.js", "panel.html", "panel.css", "panel.js"]


def build(output: str | Path) -> Path:
    manifest = json.loads((ROOT / "manifest.json").read_text())
    assert manifest["manifest_version"] == 3
    assert "<all_urls>" not in json.dumps(manifest)
    assert "http://127.0.0.1/*" in manifest["optional_host_permissions"]
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(out, "w") as target:
        for name in FILES:
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (0o644 & 0xFFFF) << 16
            target.writestr(info, (ROOT / name).read_bytes())
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="dist/svenbot-companion-alpha.zip")
    args = p.parse_args()
    print(build(args.output))
