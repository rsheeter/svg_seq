"""Make colorized monochrome examples.

Usage:

    python make_colorful.py
"""

import math
from pathlib import Path
from picosvg.svg import SVG
from picosvg.svg_meta import ntos
import subprocess


_HB_VIW = Path.home() / "oss/harfbuzz/util/hb-view"
_REPO_ROOT = Path.home() / "oss/fonts"


assert _REPO_ROOT.is_dir()
assert _HB_VIW.is_file()


def _blues(nth):
    return f"rgb(25%, 0%, {int(100 * math.sin(nth / 5 % 10))}%)"


_NEED_SVG = (
    ("Am I not colorful", _REPO_ROOT / "ofl/lobster/Lobster-Regular.ttf", "am-i-not-colorful.svg", _blues),
)


def _strip_pt(dim):
    return ntos(math.ceil(float(dim[:-2])))


def _svg_of_seq(font_path, text):
    cmd = (_HB_VIW, "-O", "svg", font_path, text)
    result = subprocess.run(
        cmd,
        capture_output=True,
        check=True,
        text=True,
    )

    raw_svg = result.stdout.strip()
    return SVG.fromstring(raw_svg)


for text, font_path, dest_file, color_fn in _NEED_SVG:
    svg = _svg_of_seq(font_path, text)

    for idx, el in enumerate(svg.xpath("//svg:g/svg:use")):
        el.attrib["fill"] = color_fn(idx)

    for dim in ("width", "height"):
        svg.svg_root.attrib[dim] = _strip_pt(svg.svg_root.attrib[dim]) 

    # delete the backdrop rect
    bd = svg.xpath_one("//svg:g[@id='surface1']/svg:rect")
    bd.getparent().remove(bd)

    with open(dest_file, "w") as f:
        f.write(svg.tostring(pretty_print=True))
    print(f"Wrote {dest_file} with {text} from {font_path}")