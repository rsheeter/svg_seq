from fontTools.ttLib import TTFont
from lxml import etree
from pathlib import Path
from picosvg.svg import SVG
import re
import subprocess
from textwrap import dedent


_NEED_SVG = (
    ("﴾صباغ﴿", "ofl/arefruqaaink/ArefRuqaaInk-Regular.ttf", "aref.svg"),
)
_REPO_ROOT = Path.home() / "oss/fonts"
_HB_SHAPE = Path.home() / "oss/harfbuzz/build/util/hb-shape"
_PARSE_GLYPH = re.compile(r"^(\d+)(?:@(-?\d+),(-?\d+))?[+](\d+)$")

assert _REPO_ROOT.is_dir()
assert _HB_SHAPE.is_file()


def _maybe_int(v):
    if v is None:
        return 0
    return int(v)


def _only(iterable):
    it = iter(iterable)
    result = next(it)
    try:
        next(it)
    except StopIteration:
        return result
    raise ValueError("More than one entry")


# Add a bogus use so the xmlns:xlink isn't discarded as unnecessary
dest_svg = SVG.fromstring(
    """
    <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" viewBox="TBD">
        <defs/>
        <use xlink:href="meh"/>
    </svg>
    """
)
dest_defs = dest_svg.xpath_one("//svg:defs")
dest_svg.svg_root.remove(dest_svg.svg_root[-1])

for text, font_path, dest_file in _NEED_SVG:
    font_path = _REPO_ROOT / font_path
    font = TTFont(font_path)
    upem = font["head"].unitsPerEm
    assert "SVG " in font

    # for d in font["SVG "].docList:
    #     print(d.startGlyphID, d.endGlyphID)

    result = subprocess.run(
        (_HB_SHAPE, "--no-glyph-names", "--no-clusters", f"--text='{text}'", font_path),
        capture_output=True,
        check=True,
        text=True,
    )

    raw_glyphs = result.stdout.strip()
    assert raw_glyphs.startswith("[") and raw_glyphs.endswith("]")
    raw_glyphs = raw_glyphs[1:-1].split("|")
    print(raw_glyphs)

    cum_advance = 0
    for raw_glyph in raw_glyphs:
        match = _PARSE_GLYPH.match(raw_glyph)
        assert match, raw_glyph
        gid, x, y, advance = match.groups()
        gid = int(gid)
        advance = int(advance)
        x = _maybe_int(x) + cum_advance
        y = _maybe_int(y)
        cum_advance += advance

        svg_table_entry = [d for d in font["SVG "].docList if d.startGlyphID <= gid <= d.endGlyphID]
        if len(svg_table_entry) != 1:
            print(f"WARN unable to find exactly one svg doc for gid {gid}, got {len(svg_table_entry)}")
            continue

        print(gid, x, y, advance)
        svg_for_gid = SVG.fromstring(svg_table_entry[0].data)

        # boldly assume we're dealing with a picosvg
        defs_to_copy = svg_for_gid.xpath_one("//svg:defs")
        dest_defs.extend(defs_to_copy)

        el_for_gid = svg_for_gid.xpath_one(f"//svg:g[@id='glyph{gid}']")
        del el_for_gid.attrib["id"]
        assert "transform" not in el_for_gid.attrib
        el_for_gid.attrib["transform"] = f"translate({x}, {y})"
        dest_svg.svg_root.append(el_for_gid)

    dest_svg.svg_root.attrib["viewBox"] = f"0 0 {cum_advance} {upem}"
    with open(dest_file, "w") as f:
        f.write(dest_svg.tostring(pretty_print=True))
    print(f"Wrote {dest_file} with {text} from {font_path}")
