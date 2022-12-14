import copy
from fontTools.ttLib import TTFont
from lxml import etree
from pathlib import Path
from picosvg.geometric_types import Rect
from picosvg.svg import SVG, from_element
from picosvg.svg_meta import ntos, strip_ns, svgns, xlinkns
from picosvg.svg_transform import Affine2D
import re
import subprocess
from textwrap import dedent


_XLINK_HREF_ATTR = f"{{{xlinkns()}}}href"  # ease of use: 10/10


_REPO_ROOT = Path.home() / "oss/fonts"
_HB_SHAPE = Path.home() / "oss/harfbuzz/util/hb-shape"
_PARSE_GLYPH = re.compile(r"^(\d+)(?:@(-?\d+),(-?\d+))?[+](\d+)$")

assert _REPO_ROOT.is_dir()
assert _HB_SHAPE.is_file()


_NEED_SVG = (
    # ("abc", Path(__file__).parent / "build/Font.ttf", "abc.svg", None),
    ("﴿صباغ﴾", _REPO_ROOT / "ofl/arefruqaaink/ArefRuqaaInk-Regular.ttf", "aref.svg", None),
    ("﴾﴿", _REPO_ROOT / "ofl/arefruqaaink/ArefRuqaaInk-Regular.ttf", "ornate-brackets.svg", 4.2),
    # ("🏳️‍⚧️", _REPO_ROOT / "ofl/notocoloremoji/NotoColorEmoji-Regular.ttf", "transgender-flag.svg", 4.2),
    # ("🥭", _REPO_ROOT / "ofl/notocoloremoji/NotoColorEmoji-Regular.ttf", "mango.svg", 4.2),
)


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


def _shape(font_path, text):
    cmd = (_HB_SHAPE, "--no-glyph-names", "--no-clusters", f"--text={text}", font_path)
    result = subprocess.run(
        cmd,
        capture_output=True,
        check=True,
        text=True,
    )

    raw_glyphs = result.stdout.strip()
    assert raw_glyphs.startswith("[") and raw_glyphs.endswith("]")
    raw_glyphs = raw_glyphs[1:-1].split("|")
    # print(text, "in", font_path.name, raw_glyphs)
    # print("  ", " ".join((str(c) for c in cmd)))

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

        yield gid, x, y, advance


def _transform_rect(rect, transform):
    x, y = transform.map_point((rect.x, rect.y))
    x2, y2 = transform.map_point((rect.x + rect.w, rect.y + rect.h))
    result = Rect(
        min(x, x2),
        min(y, y2),
        max(x, x2) - min(x, x2),
        max(y, y2) - min(y, y2)
    )
    return result


def first_not_none(*values):
    for value in values:
        if value is not None:
            return value
    raise ValueError("Only None")


def _bbox(svg, add_markers=False):
    # figure out bbox of the whole mess
    minx = miny = maxx = maxy = None
    bbox_by_id = {}
    for context in svg.breadth_first():
        transforms = [context.transform]
        if context.is_shape():
            shape = from_element(context.element)
            bbox = shape.bounding_box()

            if "id" in context.element.attrib:
                bbox_by_id[context.element.attrib["id"]] = bbox

            # if we're in defs we're done, wait for use to factor in the box
            if "/defs[" in context.path:
                continue

        # if this is a use of a shape take the targets box
        if strip_ns(context.element.tag) == "use":

            assert _XLINK_HREF_ATTR in context.element.attrib, f"No {_XLINK_HREF_ATTR} in {context.element.attrib}"
            use_of = context.element.attrib[_XLINK_HREF_ATTR]
            assert use_of.startswith("#")
            use_of = use_of[1:]
            assert use_of in bbox_by_id, f"picosvg use should be of a shape we see before the <use>, what is {use_of}"
            bbox = bbox_by_id[use_of]

            transform = Affine2D.identity()

            x = float(context.element.attrib.get("x", 0))
            y = float(context.element.attrib.get("y", 0))
            if (x, y) != (0, 0):
                 transform = Affine2D.identity().translate(x, y)
                 print("  ", "mv", (x,y))

            if "transform" in context.element.attrib:
                print("  ", Affine2D.fromstring(context.element.attrib["transform"]))
                transform = Affine2D.compose_ltr((transform, Affine2D.fromstring(context.element.attrib["transform"])))

            if transform != Affine2D.identity():
                transforms.insert(0, transform)
            del transform

        elif not context.is_shape():
            continue  # only shapes and use of shapes consume space

        transform = Affine2D.compose_ltr(transforms)
        bbox = _transform_rect(bbox, transform)

        x, y, w, h = bbox

        minx = min(x, first_not_none(minx, x))
        miny = min(y, first_not_none(miny, y))
        maxx = max(x + w, first_not_none(maxx, x + w))
        maxy = max(y + h, first_not_none(maxy, y + h))

        if add_markers:
            bbox_rect = _svg_rect(bbox)
            bbox_rect.attrib["opacity"] = "0.1"
            svg.svg_root.append(bbox_rect)

        del bbox  # surely nobody would ever accidentally use the wrong box...
    return Rect(minx, miny, maxx - minx, maxy - miny)


def _svg_rect(box: Rect) -> etree.Element:
    svg_rect = etree.Element("rect")
    svg_rect.attrib["x"] = ntos(box.x)
    svg_rect.attrib["y"] = ntos(box.y)
    svg_rect.attrib["width"] = ntos(box.w)
    svg_rect.attrib["height"] = ntos(box.h)
    return svg_rect


def _add_id_prefix(el, prefix):
    for el_with_id in el.xpath("//*[@id]"):
        el_with_id.attrib["id"] = prefix + el_with_id.attrib["id"]

    for use in el.xpath(f"//svg:use", namespaces={"svg": svgns()}):
        href = use.attrib[_XLINK_HREF_ATTR]
        assert href.startswith("#")
        use.attrib[_XLINK_HREF_ATTR] = f"#{prefix}{href[1:]}"

    for filled in el.xpath(f"//*[@fill]"):
        assert "fill" in filled.attrib, filled.attrib.keys()
        fill = filled.attrib["fill"]
        if fill.startswith("url("):
            match = re.match(r"^url[(]#(.+)[)]$", fill)
            assert match, fill
            filled.attrib["fill"] = f"url(#{prefix}{match.group(1)})"


def _svg_of_seq(font_path, text, target_w_to_h):
    font = TTFont(font_path)
    upem = font["head"].unitsPerEm
    assert "SVG " in font

    # Add a bogus use so the xmlns:xlink isn't discarded as unnecessary
    svg = SVG.fromstring(
        """
        <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" 
            viewBox="TBD">
            <defs/>
            <use xlink:href="meh"/>
        </svg>
        """
    )
    defs = svg.xpath_one("//svg:defs")
    svg.svg_root.remove(svg.svg_root[-1])
    container = etree.SubElement(svg.svg_root, "g")

    cum_advance = 0
    added = set()
    for gid, x, y, advance in _shape(font_path, text):

        # We're effectively treating x and advance as font units == svg units
        # but y is flipped. TODO contemplate if just flipping sign is sufficient :)
        y = -y

        cum_advance += advance

        svg_table_entry = [(idx, d) for idx, d in enumerate(font["SVG "].docList) if d.startGlyphID <= gid <= d.endGlyphID]
        if len(svg_table_entry) != 1:
            print(f"WARN unable to find exactly one svg doc for gid {gid}, got {len(svg_table_entry)}")
            continue
        nth_svg_table_entry, svg_table_entry = svg_table_entry[0]

        # things in one doc can share but it's bad if references resolve across documents
        id_prefix = f"svg[{nth_svg_table_entry}]."

        svg_for_gid = SVG.fromstring(svg_table_entry.data)

        # boldly assume we're dealing with a picosvg, there's definitely only one defs

        # don't copy defs repeatedly if we use many glyphs from the same svg table entry
        defs_key = ("defs", svg_table_entry.startGlyphID, svg_table_entry.endGlyphID)
        if defs_key not in added:
            defs_to_copy = svg_for_gid.xpath("//svg:defs")
            for def_el in defs_to_copy:
                def_el = copy.deepcopy(def_el)
                _add_id_prefix(def_el, id_prefix)
                defs.extend(def_el)
            added.add(defs_key)

        el_for_gid = svg_for_gid.xpath_one(f"//svg:g[@id='glyph{gid}']")
        el_for_gid = copy.deepcopy(el_for_gid)
        del el_for_gid.attrib["id"]
        assert "transform" not in el_for_gid.attrib
        el_for_gid.attrib["transform"] = f"translate({x}, {y})"
        _add_id_prefix(el_for_gid, id_prefix)
        container.append(el_for_gid)

    # make a viewBox that fits our shapes. While we're at it, lets make it start from 0,0.
    viewbox = _bbox(svg)
    print(viewbox)

    shift = 0
    w_to_h = viewbox.w / viewbox.h
    if target_w_to_h and target_w_to_h > w_to_h:
        new_w = int(viewbox.w * target_w_to_h / w_to_h)
        shift = (new_w - viewbox.w) / 2
        viewbox = viewbox._replace(w=new_w)

    container.attrib["transform"] = Affine2D.identity().translate(shift - viewbox.x, -viewbox.y).tostring()
    viewbox = _transform_rect(viewbox, Affine2D.identity().translate(-viewbox.x, -viewbox.y))
    assert viewbox[:2] == (0, 0), viewbox
    svg.svg_root.attrib["viewBox"] = " ".join(ntos(v) for v in viewbox)

    _bbox(svg, add_markers=True)
    #viewbox = _bbox(svg)
    #svg.svg_root.insert(1, _svg_rect(viewbox))

    return svg

for text, font_path, dest_file, target_w_to_h in _NEED_SVG:
    dest_svg = _svg_of_seq(font_path, text, target_w_to_h)
    with open(dest_file, "w") as f:
        f.write(dest_svg.tostring(pretty_print=True))
    print(f"Wrote {dest_file} with {text} from {font_path}")
