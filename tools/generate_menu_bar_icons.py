#!/usr/bin/env python3
"""Generate Codex Buddy Menu icon assets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "apps" / "codex-buddy-menu" / "assets"
ICONSET = ASSETS / "CodexBuddyMenu.iconset"
SOURCE_SVG = ASSETS / "CodexBuddyMenu.svg"
LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS")


SVG_SOURCE = """<svg t="1780020377976" class="icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" p-id="10402" data-spm-anchor-id="a313x.search_index.0.i4.54883a81VoWBUV" width="200" height="200"><path d="M353.5 518.9c-42.6 0-77.2 34.5-77.2 77.2 0 42.6 34.5 77.2 77.2 77.2s77.2-34.5 77.2-77.2c-0.1-42.7-34.6-77.2-77.2-77.2z m320.1 0c-42.6 0-77.2 34.5-77.2 77.2 0 42.6 34.5 77.2 77.2 77.2 42.6 0 77.2-34.5 77.2-77.2s-34.5-77.2-77.2-77.2z m95.6-245.1H254.8c-19.4 0-38.1 2.9-55.7 8.3V139.8c0-40.7-30.2-73.7-67.6-73.7S64 99.1 64 139.8V767c0 105.4 85.4 190.8 190.8 190.8h514.3C874.6 957.9 960 872.4 960 767V464.6c0-105.4-85.4-190.8-190.8-190.8z m58 455.8c0 42.8-34.7 77.6-77.6 77.6H276.7c-42.8 0-77.6-34.7-77.6-77.6V465.5c0-42.8 34.7-77.6 77.6-77.6h472.9c42.8 0 77.6 34.7 77.6 77.6v264.1z" fill="#bfbfbf" p-id="10403" data-spm-anchor-id="a313x.search_index.0.i3.54883a81VoWBUV" class="selected"></path></svg>
"""


def draw_robot_icon(size: int, *, fill: tuple[int, int, int, int], bg: tuple[int, int, int, int] | None) -> Image.Image:
    scale = size / 1024
    img = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def s(value: float) -> int:
        return round(value * scale)

    # Geometry follows the supplied 1024x1024 SVG glyph. Pillow draws the
    # compound path as explicit primitives so release builds stay dependency-free.
    draw.rounded_rectangle(
        (s(64), s(66), s(199), s(958)),
        radius=s(68),
        fill=fill,
    )
    draw.rounded_rectangle(
        (s(184), s(274), s(960), s(958)),
        radius=s(191),
        fill=fill,
    )
    draw.rounded_rectangle(
        (s(199), s(388), s(827), s(807)),
        radius=s(78),
        fill=bg or (0, 0, 0, 0),
    )
    draw.ellipse((s(276), s(519), s(431), s(674)), fill=fill)
    draw.ellipse((s(596), s(519), s(751), s(674)), fill=fill)
    return img


def draw_app_icon(size: int) -> Image.Image:
    background = (248, 248, 246, 255)
    canvas = Image.new("RGBA", (size, size), background)
    draw = ImageDraw.Draw(canvas)

    def s(value: float) -> int:
        return round(value * size / 128)

    draw.rounded_rectangle(
        (s(10), s(10), s(118), s(118)),
        radius=s(24),
        fill=(250, 250, 248, 255),
        outline=(229, 229, 225, 255),
        width=max(1, s(2)),
    )
    robot = draw_robot_icon(
        size * 4,
        fill=(191, 191, 191, 255),
        bg=(250, 250, 248, 255),
    ).resize((s(84), s(84)), LANCZOS)
    canvas.alpha_composite(robot, (s(22), s(22)))
    return canvas


def draw_tray_icon() -> Image.Image:
    robot = draw_robot_icon(
        256,
        fill=(255, 255, 255, 238),
        bg=None,
    )
    return robot.resize((32, 32), LANCZOS)


def save_iconset() -> None:
    ICONSET.mkdir(parents=True, exist_ok=True)
    specs = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    base = draw_app_icon(1024)
    for filename, size in specs:
        base.resize((size, size), LANCZOS).save(ICONSET / filename)


def save_tray_icon() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    SOURCE_SVG.write_text(SVG_SOURCE, encoding="utf-8")
    tray = draw_tray_icon()
    tray.save(ASSETS / "tray-icon-32.png")
    (ASSETS / "tray-icon-32.rgba").write_bytes(tray.tobytes())


def main() -> None:
    save_iconset()
    save_tray_icon()
    print(ASSETS)


if __name__ == "__main__":
    main()
