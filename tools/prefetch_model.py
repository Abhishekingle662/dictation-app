from __future__ import annotations

import argparse
from pathlib import Path

from faster_whisper.utils import download_model


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download a faster-whisper model into ./bundle/models/ for installer bundling."
    )
    parser.add_argument(
        "--model",
        default="large-v3-turbo",
        help="Model name (e.g. large-v3-turbo, large-v3, small)",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output directory (default: <repo>/bundle/models)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    out_base = Path(args.out) if args.out else (repo_root / "bundle" / "models")
    out_dir = (out_base / args.model).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Downloading model '{args.model}' to: {out_dir}")
    path = download_model(args.model, output_dir=str(out_dir))
    print(f"Done. Model available at: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
