"""
Generate a font-comparison test plate STL.

Hardcoded list of 6 candidate fonts; each row shows the font name (in its own font)
plus digits and the '+' sign at production font-size. Print once, pick the most
readable font, set it as default for the main utility.

Not part of the tagforge3d CLI — this is a one-off dev script. After font selection,
this file stays in the repo as historical context.
"""

from __future__ import annotations
import sys
import time
from pathlib import Path

import cadquery as cq

# -- Config ---------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
FONTS_DIR = REPO / "fonts"
OUT_DIR = REPO / "out"

# (short label shown on the plate, ttf filename in fonts/)
CANDIDATES: list[tuple[str, str]] = [
    ("DejaVu Mono",  "DejaVuSansMono-Bold.ttf"),
    ("JetBrains",    "JetBrainsMono-Bold.ttf"),
    ("Source Pro",   "SourceCodePro-Bold.ttf"),
    ("Inconsolata",  "Inconsolata-Bold.ttf"),
    ("Roboto Mono",  "RobotoMono-Bold.ttf"),
    ("DejaVu Sans",  "DejaVuSans-Bold.ttf"),  # proportional control
]

TEST_GLYPHS = "  1234567890 +"   # leading double-space separates label from test glyphs

# Production parameters (must mirror real jeton defaults so the test is meaningful)
FONT_SIZE = 8.0           # mm, em size
LAYER_HEIGHT = 0.2        # mm
INSCRIPTION_LAYERS = 2    # → 0.4 mm visible relief
BASE_LAYERS = 2           # → 0.4 mm base, just enough to bind rows on one piece

# Layout-only (test plate, not jeton)
PADDING = 3.0             # mm, breathing room around content
ROW_SPACING = 12.0        # mm between row centers (8 mm glyph + 4 mm gap)

BASE_THICKNESS = BASE_LAYERS * LAYER_HEIGHT
INSCRIPTION_HEIGHT = INSCRIPTION_LAYERS * LAYER_HEIGHT


# -- Build ----------------------------------------------------------------

def build_row(label: str, ttf_filename: str):
    """Build a row: '<label>  1234567890 +' extruded, left edge at x=0."""
    ttf_path = FONTS_DIR / ttf_filename
    if not ttf_path.is_file():
        raise FileNotFoundError(f"font not found: {ttf_path}")
    full_text = f"{label}{TEST_GLYPHS}"
    return (
        cq.Workplane("XY")
        .text(
            full_text,
            FONT_SIZE,
            INSCRIPTION_HEIGHT,
            fontPath=str(ttf_path),
            halign="left",
            valign="center",
        )
    )


def main() -> int:
    t0 = time.time()
    print(f"[font-test] generating {len(CANDIDATES)}-row plate", file=sys.stderr)

    rows = []
    max_width = 0.0
    for label, ttf in CANDIDATES:
        shape = build_row(label, ttf)
        bb = shape.val().BoundingBox()
        rows.append((label, shape, bb))
        max_width = max(max_width, bb.xlen)
        print(f"[font-test]   {label:14s}  width={bb.xlen:6.2f} mm", file=sys.stderr)

    plate_width = max_width + 2 * PADDING
    plate_height = len(CANDIDATES) * ROW_SPACING + 2 * PADDING
    plate_z = BASE_THICKNESS + INSCRIPTION_HEIGHT
    print(
        f"[font-test] plate: {plate_width:.1f} x {plate_height:.1f} x {plate_z:.1f} mm",
        file=sys.stderr,
    )

    # Base plate, top face at z = BASE_THICKNESS
    plate = (
        cq.Workplane("XY")
        .box(plate_width, plate_height, BASE_THICKNESS, centered=(True, True, False))
    )

    # Build the inscriptions as a SEPARATE body — caller can colour it differently
    # in the slicer (multi-material print). Position so it sits exactly on top of
    # the plate; shared coordinate system means the two STLs snap together when
    # loaded as parts of one print.
    inscriptions = None
    for i, (label, shape, bb) in enumerate(rows):
        # Left-align: shift so the row's left edge sits at x = -plate_width/2 + PADDING
        x = -plate_width / 2 + PADDING - bb.xmin
        # Vertical center of row at: top - padding - (i + 0.5) * row_spacing
        row_center_y = plate_height / 2 - PADDING - (i + 0.5) * ROW_SPACING
        # Compensate for text's own bbox y-offset (halign=valign=center still has font-metric offsets)
        y = row_center_y - (bb.ymin + bb.ymax) / 2
        # Lift onto base top
        z = BASE_THICKNESS
        translated = shape.translate((x, y, z))
        inscriptions = translated if inscriptions is None else inscriptions.union(translated)
        print(f"[font-test]   placed {label!r}", file=sys.stderr)

    OUT_DIR.mkdir(exist_ok=True)
    base_path = OUT_DIR / "font-test-base.stl"
    text_path = OUT_DIR / "font-test-inscriptions.stl"
    cq.exporters.export(plate, str(base_path))
    cq.exporters.export(inscriptions, str(text_path))
    base_kb = base_path.stat().st_size / 1024
    text_kb = text_path.stat().st_size / 1024
    print(
        f"[font-test] wrote {base_path.name} ({base_kb:.0f} KB)"
        f" + {text_path.name} ({text_kb:.0f} KB) in {time.time() - t0:.1f} s",
        file=sys.stderr,
    )
    print(
        f"[font-test] load both in slicer as parts of one print — they share coords",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
