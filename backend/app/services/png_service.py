"""PNG export helpers for finished runs.

The UI needs one download-friendly image that can be reused for both export and
larger viewing. This service renders the three-panel comparison once and stores
it in the run cache.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont
import ee

from .buildings_service import building_outline_images


RGB_VIS = {"bands": ["B4", "B3", "B2"], "min": 0.02, "max": 0.35, "gamma": 1.2}
PWTT_VIS = {"min": 1.8, "max": 5.0, "palette": ["#f6d743", "#e85d04", "#5f0f40"], "opacity": 0.62}


def _fetch_png(url: str) -> Image.Image:
    """Download one Earth Engine thumbnail and return it as a Pillow image."""

    response = requests.get(url, timeout=180)
    response.raise_for_status()
    return Image.open(BytesIO(response.content)).convert("RGBA")


def _thumbnail_url(image: ee.Image, region: dict[str, Any], width: int) -> str:
    """Build one Earth Engine PNG thumbnail URL for a fixed region."""

    return image.getThumbURL(
        {
            "region": region,
            "dimensions": width,
            "format": "png",
            "crs": "EPSG:4326",
        }
    )


def _panel_image(image: ee.Image, region: dict[str, Any], width: int) -> Image.Image:
    """Render one image panel through Earth Engine's thumbnail endpoint."""

    return _fetch_png(_thumbnail_url(image, region, width))


def _image_to_png_bytes(image: Image.Image) -> bytes:
    """Convert a Pillow image to compressed PNG bytes."""

    buf = BytesIO()
    image.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _fetch_panels(
    aoi: ee.Geometry,
    pre_image: ee.Image,
    post_image: ee.Image,
    pwtt_image: ee.Image,
    buildings_geojson: dict[str, Any] | None = None,
    width: int = 720,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """Download the three comparison panels from Earth Engine exactly once."""

    region = ee.Feature(aoi.bounds(1)).geometry().getInfo()

    pre_panel = _panel_image(pre_image.visualize(**RGB_VIS), region, width)
    post_panel = _panel_image(post_image.visualize(**RGB_VIS), region, width)

    pwtt_panel_image = post_image.visualize(**RGB_VIS).blend(pwtt_image.select("T_statistic").visualize(**PWTT_VIS))
    if buildings_geojson and buildings_geojson.get("features"):
        outlines, damaged_outlines = building_outline_images(buildings_geojson)
        pwtt_panel_image = (
            pwtt_panel_image
            .blend(outlines.visualize(palette=["ffffff"], opacity=0.95))
            .blend(damaged_outlines.visualize(palette=["ff4d2d"], opacity=1.0))
        )
    pwtt_panel = _panel_image(pwtt_panel_image, region, width)

    return pre_panel, post_panel, pwtt_panel


def _compose_triptych(pre: Image.Image, post: Image.Image, pwtt: Image.Image) -> bytes:
    """Lay out three panels and titles in one exportable PNG."""

    panel_width, panel_height = pre.size
    gutter = 18
    title_height = 56
    canvas = Image.new(
        "RGBA",
        (panel_width * 3 + gutter * 4, panel_height + title_height + gutter * 2),
        "#f8f5ef",
    )
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    panels = [("Pre Destruction", pre), ("Post Destruction", post), ("PWTT", pwtt)]

    for index, (title, image) in enumerate(panels):
        x = gutter + index * (panel_width + gutter)
        y = gutter + title_height
        canvas.paste(image, (x, y))
        draw.text((x, gutter + 8), title, fill="#1d2935", font=font)

    buffer = BytesIO()
    canvas.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def render_triptych_png(
    aoi: ee.Geometry,
    pre_image: ee.Image,
    post_image: ee.Image,
    pwtt_image: ee.Image,
    buildings_geojson: dict[str, Any] | None = None,
) -> bytes:
    """Render the cached triptych PNG used for export and larger preview."""

    pre_panel, post_panel, pwtt_panel = _fetch_panels(aoi, pre_image, post_image, pwtt_image, buildings_geojson)
    return _compose_triptych(pre_panel, post_panel, pwtt_panel)


def render_triptych_and_panels(
    aoi: ee.Geometry,
    pre_image: ee.Image,
    post_image: ee.Image,
    pwtt_image: ee.Image,
    buildings_geojson: dict[str, Any] | None = None,
) -> tuple[bytes, dict[str, bytes]]:
    """Render the triptych and return the three panel PNGs individually.

    Fetches each panel from Earth Engine once and produces both the combined
    export image and the individual cached preview files in a single pass.
    """

    pre_panel, post_panel, pwtt_panel = _fetch_panels(aoi, pre_image, post_image, pwtt_image, buildings_geojson)
    triptych = _compose_triptych(pre_panel, post_panel, pwtt_panel)
    panels = {
        "pre": _image_to_png_bytes(pre_panel),
        "post": _image_to_png_bytes(post_panel),
        "pwtt": _image_to_png_bytes(pwtt_panel),
    }
    return triptych, panels
