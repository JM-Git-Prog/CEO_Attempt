"""Contact sheet builder — the grid is arithmetic, not a wish.

Every attempt to make a diffusion model lay out "exactly nine panels in a 3x3
grid" failed today: asked for 9, got 12; rewrote the prompt naming the count
three separate times, got 6. Generators do not count.

So stop asking. Generate the panels, then place them here. The grid becomes an
addressing operation - row = i // cols, col = i % cols - and the count is
exactly what was requested because a loop cannot miscount.

Usage:
    python tools/contact_sheet.py out.png a.png b.png c.png ...
    python tools/contact_sheet.py out.png --cols 3 --label "Bird's eye" a.png ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def build(
    panels: list[Path],
    out_path: Path,
    cols: int = 3,
    gutter: int = 12,
    margin: int = 12,
    background: tuple[int, int, int] = (14, 14, 14),
    labels: list[str] | None = None,
) -> Path:
    """Lay panels into a grid. Cells are sized to the largest panel."""
    if not panels:
        raise ValueError("no panels given")

    images = [Image.open(p).convert("RGB") for p in panels]
    cell_w = max(im.width for im in images)
    cell_h = max(im.height for im in images)
    rows = (len(images) + cols - 1) // cols

    label_h = 0
    font = None
    if labels:
        try:
            font = ImageFont.truetype("arial.ttf", max(12, cell_h // 28))
        except OSError:
            font = ImageFont.load_default()
        label_h = max(16, cell_h // 22)

    sheet_w = margin * 2 + cols * cell_w + (cols - 1) * gutter
    sheet_h = margin * 2 + rows * (cell_h + label_h) + (rows - 1) * gutter
    sheet = Image.new("RGB", (sheet_w, sheet_h), background)
    draw = ImageDraw.Draw(sheet)

    for index, image in enumerate(images):
        row, col = divmod(index, cols)
        x = margin + col * (cell_w + gutter)
        y = margin + row * (cell_h + label_h + gutter)
        # Centre a smaller panel inside its cell rather than stretching it:
        # a stretched panel is a distorted panel, the same mistake the mesh
        # pipeline makes when it forces geometry into a catalogue box.
        sheet.paste(image, (x + (cell_w - image.width) // 2,
                            y + (cell_h - image.height) // 2))
        if labels and index < len(labels):
            draw.text(
                (x + 4, y + cell_h + 2), labels[index],
                fill=(150, 220, 180), font=font,
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an N-up contact sheet.")
    parser.add_argument("out")
    parser.add_argument("panels", nargs="+")
    parser.add_argument("--cols", type=int, default=3)
    parser.add_argument("--gutter", type=int, default=12)
    parser.add_argument("--label", action="append", default=None)
    args = parser.parse_args()

    paths = [Path(p) for p in args.panels]
    missing = [p for p in paths if not p.is_file()]
    if missing:
        print("missing panels:", *(str(m) for m in missing), sep="\n  ")
        return 1

    out = build(
        paths, Path(args.out), cols=args.cols,
        gutter=args.gutter, labels=args.label,
    )
    sheet = Image.open(out)
    rows = (len(paths) + args.cols - 1) // args.cols
    print(f"wrote {out}")
    print(f"  {len(paths)} panels in {rows} x {args.cols} = {sheet.size[0]}x{sheet.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
