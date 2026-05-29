#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image
except ModuleNotFoundError:
    Image = None  # type: ignore[assignment]


CELL_WIDTH = 192
CELL_HEIGHT = 208
ATLAS_COLUMNS = 8
ATLAS_ROWS = 9
FRAME_WIDTH = 72
FRAME_HEIGHT = 78
TRANSPARENT_SWAP565 = 0x1FF8
PLACEHOLDER_BODY = (237, 248, 255, 255)
PLACEHOLDER_BODY_DARK = (140, 191, 210, 255)
PLACEHOLDER_OUTLINE = (21, 39, 54, 255)
PLACEHOLDER_ACCENT = (38, 214, 191, 255)
PLACEHOLDER_ACCENT_DARK = (12, 142, 156, 255)
PLACEHOLDER_WARN = (255, 202, 73, 255)
PLACEHOLDER_FAIL = (239, 83, 80, 255)
PLACEHOLDER_SHADOW = (36, 57, 73, 180)


@dataclass(frozen=True)
class RowSpec:
    name: str
    row: int
    columns: int
    durations: tuple[int, ...]


ROWS = (
    RowSpec("idle", 0, 6, (280, 110, 110, 140, 140, 320)),
    RowSpec("running_right", 1, 8, (120, 120, 120, 120, 120, 120, 120, 220)),
    RowSpec("running_left", 2, 8, (120, 120, 120, 120, 120, 120, 120, 220)),
    RowSpec("waving", 3, 4, (140, 140, 140, 280)),
    RowSpec("jumping", 4, 5, (140, 140, 140, 140, 280)),
    RowSpec("failed", 5, 8, (140, 140, 140, 140, 140, 140, 140, 240)),
    RowSpec("waiting", 6, 6, (150, 150, 150, 150, 150, 260)),
    RowSpec("running", 7, 6, (120, 120, 120, 120, 120, 220)),
    RowSpec("review", 8, 6, (150, 150, 150, 150, 150, 280)),
)


def swap565(pixel: tuple[int, int, int, int]) -> int:
    r, g, b, alpha = pixel
    if alpha < 48:
        return TRANSPARENT_SWAP565
    if alpha < 255:
        r = (r * alpha) // 255
        g = (g * alpha) // 255
        b = (b * alpha) // 255
    rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return ((rgb565 & 0x00FF) << 8) | (rgb565 >> 8)


def swap565_to_rgba(value: int) -> tuple[int, int, int, int]:
    if value == TRANSPARENT_SWAP565:
        return (0, 0, 0, 0)
    rgb565 = ((value & 0x00FF) << 8) | (value >> 8)
    r = (rgb565 >> 8) & 0xF8
    g = (rgb565 >> 3) & 0xFC
    b = (rgb565 << 3) & 0xF8
    return (r | (r >> 5), g | (g >> 6), b | (b >> 5), 255)


def resize_cell(cell: Image.Image) -> Image.Image:
    alpha = cell.getchannel("A")
    mask = alpha.point(lambda value: 255 if value >= 48 else 0)
    bbox = mask.getbbox()
    if bbox is not None:
        left, top, right, bottom = bbox
        pad = 8
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(cell.width, right + pad)
        bottom = min(cell.height, bottom + pad)
        cell = cell.crop((left, top, right, bottom))

    resampling = getattr(Image, "Resampling", Image).LANCZOS
    cell.thumbnail((FRAME_WIDTH, FRAME_HEIGHT), resampling)
    canvas = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
    x = (FRAME_WIDTH - cell.width) // 2
    y = (FRAME_HEIGHT - cell.height) // 2
    canvas.alpha_composite(cell, (x, y))
    return canvas


def load_frames(atlas_path: Path) -> tuple[list[list[int]], dict[str, list[int]]]:
    if Image is None:
        raise SystemExit(
            "Pillow is required to generate pet sprites. "
            "Install it with: python3 -m pip install Pillow"
        )
    atlas = Image.open(atlas_path).convert("RGBA")
    expected_size = (CELL_WIDTH * ATLAS_COLUMNS, CELL_HEIGHT * ATLAS_ROWS)
    if atlas.size != expected_size:
        raise ValueError(f"unexpected atlas size {atlas.size}, expected {expected_size}")

    frames: list[list[int]] = []
    sequences: dict[str, list[int]] = {}
    for row_spec in ROWS:
        sequence: list[int] = []
        for column in range(row_spec.columns):
            left = column * CELL_WIDTH
            top = row_spec.row * CELL_HEIGHT
            cell = atlas.crop((left, top, left + CELL_WIDTH, top + CELL_HEIGHT))
            resized = resize_cell(cell)
            values = [swap565(pixel) for pixel in resized.getdata()]
            sequence.append(len(frames))
            frames.append(values)
        sequences[row_spec.name] = sequence
    return frames, sequences


def blank_frame() -> list[int]:
    return [TRANSPARENT_SWAP565] * (FRAME_WIDTH * FRAME_HEIGHT)


def set_pixel(frame: list[int], x: int, y: int, color: tuple[int, int, int, int]) -> None:
    if 0 <= x < FRAME_WIDTH and 0 <= y < FRAME_HEIGHT:
        frame[y * FRAME_WIDTH + x] = swap565(color)


def draw_rect(
    frame: list[int],
    left: int,
    top: int,
    right: int,
    bottom: int,
    color: tuple[int, int, int, int],
) -> None:
    for y in range(top, bottom):
        for x in range(left, right):
            set_pixel(frame, x, y, color)


def draw_outline_rect(
    frame: list[int],
    left: int,
    top: int,
    right: int,
    bottom: int,
    color: tuple[int, int, int, int],
) -> None:
    draw_rect(frame, left, top, right, top + 2, color)
    draw_rect(frame, left, bottom - 2, right, bottom, color)
    draw_rect(frame, left, top, left + 2, bottom, color)
    draw_rect(frame, right - 2, top, right, bottom, color)


def draw_circle(
    frame: list[int],
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int, int],
) -> None:
    radius_sq = radius * radius
    for y in range(cy - radius, cy + radius + 1):
        for x in range(cx - radius, cx + radius + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= radius_sq:
                set_pixel(frame, x, y, color)


def draw_line(
    frame: list[int],
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int, int],
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        set_pixel(frame, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        err2 = 2 * err
        if err2 >= dy:
            err += dy
            x0 += sx
        if err2 <= dx:
            err += dx
            y0 += sy


def draw_placeholder_pet(row_spec: RowSpec, column: int) -> list[int]:
    frame = blank_frame()
    phase = column % max(1, row_spec.columns)
    bounce_pattern = (0, -1, -2, -1, 0, 1, 0, -1)
    walk_pattern = (0, 2, 4, 2, 0, -2, -4, -2)
    x_shift = 0
    y_shift = 0
    arm_lift = 0
    alert_color = PLACEHOLDER_ACCENT
    eye_color = PLACEHOLDER_ACCENT_DARK

    if row_spec.name == "running_right":
        x_shift = min(5, phase - 2)
        y_shift = bounce_pattern[phase % len(bounce_pattern)]
    elif row_spec.name == "running_left":
        x_shift = -min(5, phase - 2)
        y_shift = bounce_pattern[phase % len(bounce_pattern)]
    elif row_spec.name == "running":
        x_shift = walk_pattern[phase % len(walk_pattern)] // 2
        y_shift = bounce_pattern[phase % len(bounce_pattern)]
    elif row_spec.name == "waving":
        arm_lift = (0, 5, 9, 4)[phase % 4]
        alert_color = PLACEHOLDER_WARN
    elif row_spec.name == "jumping":
        y_shift = (0, -5, -9, -5, 0)[phase % 5]
        alert_color = PLACEHOLDER_WARN
    elif row_spec.name == "failed":
        y_shift = (0, 1, 0, -1, 0, 1, 0, -1)[phase % 8]
        alert_color = PLACEHOLDER_FAIL
        eye_color = PLACEHOLDER_FAIL
    elif row_spec.name == "waiting":
        y_shift = (0, 0, -1, -2, -1, 0)[phase % 6]
        alert_color = PLACEHOLDER_WARN
    elif row_spec.name == "review":
        y_shift = (0, -1, -1, 0, 1, 0)[phase % 6]
        alert_color = PLACEHOLDER_WARN

    cx = 36 + x_shift
    top = 11 + y_shift

    # Shadow
    draw_rect(frame, cx - 18, 69, cx + 18, 72, PLACEHOLDER_SHADOW)

    # Antenna / status cap
    draw_line(frame, cx, top + 3, cx, top - 4, PLACEHOLDER_OUTLINE)
    draw_circle(frame, cx, top - 6, 3, alert_color)
    draw_rect(frame, cx - 18, top + 6, cx + 18, top + 11, PLACEHOLDER_OUTLINE)
    draw_rect(frame, cx - 15, top + 7, cx + 15, top + 10, alert_color)

    # Head
    draw_rect(frame, cx - 18, top + 13, cx + 18, top + 36, PLACEHOLDER_OUTLINE)
    draw_rect(frame, cx - 15, top + 16, cx + 15, top + 33, PLACEHOLDER_BODY)
    draw_rect(frame, cx - 21, top + 20, cx - 17, top + 29, PLACEHOLDER_OUTLINE)
    draw_rect(frame, cx + 17, top + 20, cx + 21, top + 29, PLACEHOLDER_OUTLINE)
    draw_rect(frame, cx - 20, top + 22, cx - 18, top + 27, PLACEHOLDER_ACCENT)
    draw_rect(frame, cx + 18, top + 22, cx + 20, top + 27, PLACEHOLDER_ACCENT)

    blink = row_spec.name == "idle" and phase in {2, 3}
    if blink:
        draw_rect(frame, cx - 10, top + 24, cx - 4, top + 26, eye_color)
        draw_rect(frame, cx + 4, top + 24, cx + 10, top + 26, eye_color)
    else:
        draw_rect(frame, cx - 10, top + 22, cx - 5, top + 28, PLACEHOLDER_OUTLINE)
        draw_rect(frame, cx - 9, top + 23, cx - 6, top + 27, eye_color)
        draw_rect(frame, cx + 5, top + 22, cx + 10, top + 28, PLACEHOLDER_OUTLINE)
        draw_rect(frame, cx + 6, top + 23, cx + 9, top + 27, eye_color)
    draw_rect(frame, cx - 4, top + 31, cx + 5, top + 33, PLACEHOLDER_OUTLINE)

    # Body
    draw_rect(frame, cx - 14, top + 37, cx + 14, top + 60, PLACEHOLDER_OUTLINE)
    draw_rect(frame, cx - 11, top + 40, cx + 11, top + 58, PLACEHOLDER_BODY_DARK)
    draw_rect(frame, cx - 8, top + 42, cx + 8, top + 55, PLACEHOLDER_BODY)
    draw_outline_rect(frame, cx - 5, top + 44, cx + 6, top + 53, alert_color)

    # Arms
    left_arm_y = top + 42
    right_arm_y = top + 42 - arm_lift
    draw_line(frame, cx - 14, top + 42, cx - 24, left_arm_y + 10, PLACEHOLDER_OUTLINE)
    draw_line(frame, cx - 15, top + 43, cx - 24, left_arm_y + 11, alert_color)
    draw_line(frame, cx + 14, top + 42, cx + 24, right_arm_y + 10, PLACEHOLDER_OUTLINE)
    draw_line(frame, cx + 15, top + 43, cx + 24, right_arm_y + 11, alert_color)
    draw_circle(frame, cx - 25, left_arm_y + 12, 3, PLACEHOLDER_OUTLINE)
    draw_circle(frame, cx + 25, right_arm_y + 12, 3, PLACEHOLDER_OUTLINE)

    # Legs
    leg_phase = phase % 4
    left_leg = -3 if leg_phase in {1, 2} else 1
    right_leg = 3 if leg_phase in {1, 2} else -1
    draw_line(frame, cx - 7, top + 60, cx - 12 + left_leg, top + 68, PLACEHOLDER_OUTLINE)
    draw_line(frame, cx + 7, top + 60, cx + 12 + right_leg, top + 68, PLACEHOLDER_OUTLINE)
    draw_rect(frame, cx - 17 + left_leg, top + 67, cx - 8 + left_leg, top + 70, alert_color)
    draw_rect(frame, cx + 8 + right_leg, top + 67, cx + 17 + right_leg, top + 70, alert_color)

    if row_spec.name == "waiting":
        for dot in range(3):
            color = PLACEHOLDER_WARN if dot == phase % 3 else PLACEHOLDER_BODY_DARK
            draw_rect(frame, cx + 23 + dot * 5, top + 18, cx + 26 + dot * 5, top + 21, color)
    if row_spec.name == "review":
        draw_outline_rect(frame, cx + 20, top + 13, cx + 34, top + 27, PLACEHOLDER_WARN)
        draw_rect(frame, cx + 24, top + 20, cx + 31, top + 23, PLACEHOLDER_WARN)

    return frame


def generate_placeholder_frames() -> tuple[list[list[int]], dict[str, list[int]]]:
    frames: list[list[int]] = []
    sequences: dict[str, list[int]] = {}
    for row_spec in ROWS:
        sequence: list[int] = []
        for column in range(row_spec.columns):
            sequence.append(len(frames))
            frames.append(draw_placeholder_pet(row_spec, column))
        sequences[row_spec.name] = sequence
    return frames, sequences


def write_contact_sheet(path: Path, frames: list[list[int]], sequences: dict[str, list[int]]) -> None:
    if Image is None:
        raise SystemExit(
            "Pillow is required to write a contact sheet. "
            "Install it with: python3 -m pip install Pillow"
        )
    width = max(len(seq) for seq in sequences.values()) * FRAME_WIDTH
    height = len(ROWS) * FRAME_HEIGHT
    sheet = Image.new("RGBA", (width, height), (18, 24, 32, 255))
    for row_index, row_spec in enumerate(ROWS):
        for col_index, frame_index in enumerate(sequences[row_spec.name]):
            image = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
            image.putdata([swap565_to_rgba(value) for value in frames[frame_index]])
            sheet.alpha_composite(image, (col_index * FRAME_WIDTH, row_index * FRAME_HEIGHT))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def format_u16_array(values: list[int], indent: str = "  ") -> str:
    chunks = []
    for index in range(0, len(values), 12):
        line = ", ".join(f"0x{value:04X}" for value in values[index : index + 12])
        chunks.append(f"{indent}{line},")
    return "\n".join(chunks)


def format_u8_array(values: list[int], indent: str = "  ") -> str:
    return f"{indent}" + ", ".join(str(value) for value in values) + ","


def write_header(path: Path, frame_count: int, label: str) -> None:
    path.write_text(
        f"""// Generated by tools/generate_pet_sprite_asset.py.
// Repository default pet: {label}.

#pragma once

#include <Arduino.h>
#include <pgmspace.h>

constexpr uint8_t kCodexPetFrameWidth = {FRAME_WIDTH};
constexpr uint8_t kCodexPetFrameHeight = {FRAME_HEIGHT};
constexpr uint16_t kCodexPetFramePixels =
    kCodexPetFrameWidth * kCodexPetFrameHeight;
constexpr uint8_t kCodexPetFrameCount = {frame_count};
constexpr uint16_t kCodexPetTransparentColor = 0x{TRANSPARENT_SWAP565:04X};

extern const uint16_t
    kCodexPetFrames[kCodexPetFrameCount][kCodexPetFramePixels] PROGMEM;

extern const uint8_t kCodexPetIdleFrames[] PROGMEM;
extern const uint16_t kCodexPetIdleDurations[] PROGMEM;
extern const uint8_t kCodexPetRunningRightFrames[] PROGMEM;
extern const uint16_t kCodexPetRunningRightDurations[] PROGMEM;
extern const uint8_t kCodexPetRunningLeftFrames[] PROGMEM;
extern const uint16_t kCodexPetRunningLeftDurations[] PROGMEM;
extern const uint8_t kCodexPetWavingFrames[] PROGMEM;
extern const uint16_t kCodexPetWavingDurations[] PROGMEM;
extern const uint8_t kCodexPetJumpingFrames[] PROGMEM;
extern const uint16_t kCodexPetJumpingDurations[] PROGMEM;
extern const uint8_t kCodexPetFailedFrames[] PROGMEM;
extern const uint16_t kCodexPetFailedDurations[] PROGMEM;
extern const uint8_t kCodexPetWaitingFrames[] PROGMEM;
extern const uint16_t kCodexPetWaitingDurations[] PROGMEM;
extern const uint8_t kCodexPetRunningFrames[] PROGMEM;
extern const uint16_t kCodexPetRunningDurations[] PROGMEM;
extern const uint8_t kCodexPetReviewFrames[] PROGMEM;
extern const uint16_t kCodexPetReviewDurations[] PROGMEM;
""",
        encoding="utf-8",
    )


def write_source(
    path: Path,
    frames: list[list[int]],
    sequences: dict[str, list[int]],
    label: str,
) -> None:
    lines: list[str] = [
        "// Generated by tools/generate_pet_sprite_asset.py.",
        f"// Repository default pet: {label}.",
        '#include "CodexPetSprite.h"',
        "",
        "const uint16_t",
        "    kCodexPetFrames[kCodexPetFrameCount][kCodexPetFramePixels] PROGMEM = {",
    ]
    for frame in frames:
        lines.append("  {")
        lines.append(format_u16_array(frame, "    "))
        lines.append("  },")
    lines.append("};")
    lines.append("")

    for row_spec in ROWS:
        seq = sequences[row_spec.name]
        symbol = "".join(part.capitalize() for part in row_spec.name.split("_"))
        lines.append(f"const uint8_t kCodexPet{symbol}Frames[] PROGMEM = {{")
        lines.append(format_u8_array(seq, "  "))
        lines.append("};")
        lines.append(f"const uint16_t kCodexPet{symbol}Durations[] PROGMEM = {{")
        lines.append(format_u16_array(list(row_spec.durations), "  "))
        lines.append("};")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--spritesheet",
        type=Path,
        default=None,
        help="Codex pet atlas to convert. If omitted, a redistributable placeholder is generated.",
    )
    parser.add_argument(
        "--placeholder",
        action="store_true",
        help="Generate the built-in redistributable placeholder pet.",
    )
    parser.add_argument(
        "--contact-sheet",
        type=Path,
        default=None,
        help="Optional PNG contact sheet for visual review.",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Human-readable label written into generated C++ comments.",
    )
    parser.add_argument(
        "--include",
        type=Path,
        default=Path("firmware/include/CodexPetSprite.h"),
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("firmware/src/CodexPetSprite.cpp"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.placeholder and args.spritesheet is not None:
        raise SystemExit("--placeholder and --spritesheet cannot be used together")
    if args.spritesheet is None:
        frames, sequences = generate_placeholder_frames()
        source_label = "procedural placeholder"
    else:
        frames, sequences = load_frames(args.spritesheet)
        source_label = str(args.spritesheet)
    label = args.label or source_label
    args.include.parent.mkdir(parents=True, exist_ok=True)
    args.source.parent.mkdir(parents=True, exist_ok=True)
    write_header(args.include, len(frames), label)
    write_source(args.source, frames, sequences, label)
    if args.contact_sheet is not None:
        write_contact_sheet(args.contact_sheet, frames, sequences)
    print(f"generated {len(frames)} frames from {source_label}")
    print(args.include)
    print(args.source)
    if args.contact_sheet is not None:
        print(args.contact_sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
