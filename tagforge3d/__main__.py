"""tagforge3d: forge printable STL keychain (жетон) with text.

Outputs TWO STL files per run — base plate and inscriptions — so the user can
assign different filaments in the slicer for multi-material printing. The two
STLs share a coordinate system and snap together when loaded as parts of one
print.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import cadquery as cq

# -- Paths ----------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FONT = REPO / "fonts" / "SourceCodePro-Bold.ttf"

# -- Validation -----------------------------------------------------------

ALLOWED_CHAR = re.compile(r"[0-9A-Za-z+\-() .,_/]")
ALLOWED_DESC = "0-9, A-Z, a-z, '+', '-', '(', ')', '.', ',', '_', '/', space"


def validate_text(text: str) -> None:
    """Raise ValueError if text violates the whitelist or is whitespace-only."""
    if not text.strip():
        raise ValueError("text must contain at least one non-whitespace character")
    for c in text:
        if not ALLOWED_CHAR.fullmatch(c):
            raise ValueError(
                f"character {c!r} (U+{ord(c):04X}) is not supported. "
                f"Allowed: {ALLOWED_DESC}"
            )


def sanitize_filename(text: str) -> str:
    """Replace filesystem-forbidden chars from the whitelist."""
    return text.replace("/", "_")


# -- Logging --------------------------------------------------------------

def log(stage: str, msg: str) -> None:
    print(f"[{stage}] {msg}", file=sys.stderr)


# -- Geometry -------------------------------------------------------------

def build_jeton(
    text: str,
    font_path: Path,
    font_size: float,
    padding: float,
    hole_diameter: float,
    plate_layers: int,
    inscription_layers: int,
    layer_height: float,
):
    """Build plate (with hole) and inscription as two separate CadQuery shapes.

    Layout (top view, origin at plate center):

        ┌──────────────────────────────────────────┐
        │   ⊙       <inscription>                  │  → plate_height = font_size + 2·padding
        └──────────────────────────────────────────┘
         ↑   ↑      ↑                              ↑
         │   │      │                              padding
         │   │      padding
         │   hole_diameter
         plate_thickness  (left wall = invariant)
    """
    plate_thickness = plate_layers * layer_height
    inscription_height = inscription_layers * layer_height

    if hole_diameter > font_size:
        raise ValueError(
            f"hole_diameter ({hole_diameter} mm) > font_size ({font_size} mm); "
            f"hole won't fit with adequate margin. Reduce --hole-diameter or "
            f"increase --font-size."
        )

    # Text shape (extruded along +Z from z=0 to z=inscription_height)
    text_shape = (
        cq.Workplane("XY")
        .text(
            text,
            font_size,
            inscription_height,
            fontPath=str(font_path),
            halign="left",
            valign="center",
        )
    )
    bb = text_shape.val().BoundingBox()
    text_width = bb.xlen
    log("measure", f"text bounds: {text_width:.2f} x {bb.ylen:.2f} mm")

    # Outer border = plate_thickness on all 4 sides (uniform invariant).
    # Internal gap between hole and text = padding (the only configurable spacing).
    border = plate_thickness
    plate_width = border + hole_diameter + padding + text_width + border
    plate_height = bb.ylen + 2 * border
    corner_radius = padding / 2

    log(
        "layout",
        f"plate: {plate_width:.1f} x {plate_height:.1f} x {plate_thickness:.1f} mm "
        f"(border {border:.1f}, hole-text gap {padding:.1f})",
    )

    # Plate: rounded rectangle, then through-hole
    plate = (
        cq.Workplane("XY")
        .rect(plate_width, plate_height)
        .extrude(plate_thickness)
        .edges("|Z")
        .fillet(corner_radius)
    )
    log("geometry", f"plate extruded (rounded rect, corner r={corner_radius:.1f})")

    hole_x = -plate_width / 2 + border + hole_diameter / 2
    plate = (
        plate.faces(">Z")
        .workplane()
        .center(hole_x, 0)
        .circle(hole_diameter / 2)
        .cutThruAll()
    )
    log("geometry", f"hole cut at ({hole_x:.2f}, 0) mm, diameter {hole_diameter:.1f} mm")

    # Inscription: position so left edge sits right of hole zone, Y centered
    inscription_left_x = -plate_width / 2 + border + hole_diameter + padding
    tx = inscription_left_x - bb.xmin
    ty = -(bb.ymin + bb.ymax) / 2
    tz = plate_thickness
    inscription = text_shape.translate((tx, ty, tz))
    log(
        "geometry",
        f"inscription placed at z={tz:.2f}, height {inscription_height:.2f} mm "
        f"({inscription_layers} layers x {layer_height})",
    )

    return plate, inscription


# -- CLI ------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="tagforge3d",
        description="Generate a printable STL keychain (жетон) with text. "
                    "Produces two STLs — plate and inscription — for multi-material printing.",
    )
    p.add_argument("--text", required=True, help="Inscription text (required)")
    p.add_argument(
        "--output",
        default=None,
        type=Path,
        help=(
            "Output stem (no extension). Two files are produced: "
            "'{stem}-plate.stl' and '{stem}-inscription.stl'. "
            "Default: text content with '/' replaced by '_'."
        ),
    )
    p.add_argument("--layer-height", type=float, default=0.2,
                   help="Print layer height in mm (default: 0.2)")
    p.add_argument("--inscription-layers", type=int, default=2,
                   help="Inscription thickness in layers (default: 2 → 0.4 mm)")
    p.add_argument("--plate-layers", type=int, default=4,
                   help="Plate thickness in layers; also sets left-wall width (default: 4 → 0.8 mm)")
    p.add_argument("--font-size", type=float, default=8.0,
                   help="Glyph em-size in mm (default: 8.0)")
    p.add_argument("--font", type=Path, default=DEFAULT_FONT,
                   help=f"TTF font path (default: {DEFAULT_FONT.name})")
    p.add_argument("--padding", type=float, default=2.0,
                   help="Uniform padding inside plate, mm (default: 2.0)")
    p.add_argument("--hole-diameter", type=float, default=3.0,
                   help="Mount hole diameter in mm (default: 3.0)")
    return p.parse_args(argv)


def resolve_output_stem(text: str, output_arg: Path | None) -> tuple[Path, str]:
    """Return (out_dir, stem) given --text and optional --output."""
    if output_arg is None:
        return Path("."), sanitize_filename(text)
    # --output may include a .stl suffix or not — strip it either way
    if output_arg.suffix == ".stl":
        return output_arg.parent, output_arg.stem
    return output_arg.parent, output_arg.name


def main(argv: list[str] | None = None) -> int:
    t0 = time.time()
    args = parse_args(argv)

    try:
        validate_text(args.text)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    log("validate", f"text {args.text!r} OK ({len(args.text)} chars, allowlist match)")

    if not args.font.is_file():
        print(f"Error: font not found: {args.font}", file=sys.stderr)
        return 2
    log("font", f"loaded {args.font.name} from {args.font}")

    try:
        plate, inscription = build_jeton(
            text=args.text,
            font_path=args.font,
            font_size=args.font_size,
            padding=args.padding,
            hole_diameter=args.hole_diameter,
            plate_layers=args.plate_layers,
            inscription_layers=args.inscription_layers,
            layer_height=args.layer_height,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    out_dir, stem = resolve_output_stem(args.text, args.output)
    plate_path = out_dir / f"{stem}-plate.stl"
    inscription_path = out_dir / f"{stem}-inscription.stl"

    log("export", "tessellating to STL")
    cq.exporters.export(plate, str(plate_path))
    cq.exporters.export(inscription, str(inscription_path))
    plate_kb = plate_path.stat().st_size / 1024
    text_kb = inscription_path.stat().st_size / 1024
    log(
        "export",
        f"wrote {plate_path.name} ({plate_kb:.0f} KB) + "
        f"{inscription_path.name} ({text_kb:.0f} KB) in {time.time() - t0:.1f} s",
    )
    log("export", "load both in slicer as parts of one print (Add part / Merge)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
