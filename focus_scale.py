#!/usr/bin/env python3
"""
Helicoid focus scale generator.

GUI for helicoid / lens params; scale rendering matches the design in
focusing/distance_markers.py (PIL strip, ticks, label alignment, DPI sizing).

Optics: infinity at full retract when error=0. Beyond infinity,
δ = f² / (u − f). Positive error → infinity before retract (unreachable).
"""

from __future__ import annotations

import math
import os
import platform
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageDraw, ImageFont, ImageTk
from tkinter import colorchooser

DEFAULT_TARGET_DISTANCES = [
    0.8, 0.9, 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 13, 20, 40,
]

MARK_MODES = ("fixed", "dynamic")

# Portrait width × height in mm
PAGE_SIZES_MM = {
    "Letter": (215.9, 279.4),
    "A4": (210.0, 297.0),
}
PAGE_MARGIN_MM = 10.0
STRIPE_MM = 5.0  # non-scale glue tab on the right of continuing rows
LEFT_LABEL_MM = 5.0  # letter sits left of the scale (not on it)
ROW_GAP_MM = 14.0  # vertical gap between tiled rows (room for row index)
WRAP_GAP_MM = 3.0  # air gap so wrap markers never touch the scale
WRAP_MARKER_MM = 8.0  # detached wrap indicator width

DEFAULT_TEXT_COLOR = "#FFFFFF"
DEFAULT_TICK_COLOR = "#FFFFFF"
DEFAULT_STRIPE_COLOR = "#E53935"
DEFAULT_FONT_SIZE = 18
DEFAULT_FONT_NAME = "Helvetica Neue"
FALLBACK_FONT_NAME = "Arial"


@dataclass(frozen=True)
class FontRef:
    path: str
    index: int = 0


@dataclass
class FontFamily:
    name: str
    regular: FontRef
    bold: Optional[FontRef] = None


_FONT_CATALOG: Optional[dict[str, FontFamily]] = None


def _system_font_dirs() -> list[Path]:
    home = Path.home()
    system = platform.system()
    dirs: list[Path] = []
    if system == "Darwin":
        dirs.extend(
            [
                Path("/System/Library/Fonts"),
                Path("/System/Library/Fonts/Supplemental"),
                Path("/Library/Fonts"),
                home / "Library/Fonts",
            ]
        )
    elif system == "Windows":
        windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs.extend(
            [
                windir / "Fonts",
                home / "AppData/Local/Microsoft/Windows/Fonts",
            ]
        )
    else:
        dirs.extend(
            [
                Path("/usr/share/fonts"),
                Path("/usr/local/share/fonts"),
                home / ".fonts",
                home / ".local/share/fonts",
            ]
        )
    # Deduplicate while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for d in dirs:
        try:
            key = d.resolve()
        except OSError:
            key = d
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _iter_font_files() -> list[Path]:
    exts = {".ttf", ".otf", ".ttc", ".otc"}
    files: list[Path] = []
    seen: set[Path] = set()
    for root in _system_font_dirs():
        if not root.is_dir():
            continue
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in exts:
                    continue
                try:
                    key = path.resolve()
                except OSError:
                    key = path
                if key in seen:
                    continue
                seen.add(key)
                files.append(path)
        except OSError:
            continue
    return files


def _style_is_italic(style: str) -> bool:
    s = style.lower()
    return "italic" in s or "oblique" in s


def _style_is_bold(style: str) -> bool:
    s = style.lower()
    return any(
        token in s
        for token in ("bold", "black", "heavy", "semibold", "semi bold", "demibold")
    )


def _regular_score(style: str) -> int:
    """Higher is better for the regular (non-bold) slot."""
    s = (style or "Regular").strip()
    low = s.lower()
    if _style_is_italic(low):
        return -10
    if _style_is_bold(low):
        return -5
    if low in ("regular", "book", "roman", "normal", "medium", "plain", ""):
        return 20
    return 8


def _bold_score(style: str) -> int:
    """Higher is better for the bold slot."""
    s = (style or "").strip()
    low = s.lower()
    if _style_is_italic(low):
        return -10
    if not _style_is_bold(low):
        return -5
    if low in ("bold", "bold mt"):
        return 20
    if "semibold" in low or "demi" in low:
        return 10
    return 12


def _probe_font_faces(path: Path) -> list[tuple[str, str, int]]:
    """Return (family, style, collection_index) faces inside a font file."""
    faces: list[tuple[str, str, int]] = []
    max_index = 64 if path.suffix.lower() in {".ttc", ".otc"} else 1
    for index in range(max_index):
        try:
            font = ImageFont.truetype(str(path), 12, index=index)
        except (OSError, ValueError, SyntaxError):
            break
        try:
            family, style = font.getname()
        except Exception:
            continue
        family = (family or "").strip()
        style = (style or "Regular").strip() or "Regular"
        if family:
            faces.append((family, style, index))
    return faces


def get_font_catalog() -> dict[str, FontFamily]:
    """Scan installed fonts once; map family name → regular/bold file refs."""
    global _FONT_CATALOG
    if _FONT_CATALOG is not None:
        return _FONT_CATALOG

    regular_best: dict[str, tuple[int, FontRef]] = {}
    bold_best: dict[str, tuple[int, FontRef]] = {}

    for path in _iter_font_files():
        for family, style, index in _probe_font_faces(path):
            ref = FontRef(str(path), index)
            r_score = _regular_score(style)
            if r_score > regular_best.get(family, (-999, ref))[0]:
                regular_best[family] = (r_score, ref)
            b_score = _bold_score(style)
            if b_score > bold_best.get(family, (-999, ref))[0]:
                bold_best[family] = (b_score, ref)

    catalog: dict[str, FontFamily] = {}
    for name, (_score, regular) in regular_best.items():
        bold_ref = None
        if name in bold_best and bold_best[name][0] > 0:
            bold_ref = bold_best[name][1]
        catalog[name] = FontFamily(name=name, regular=regular, bold=bold_ref)

    # Families that only expose a bold cut — still usable
    for name, (_score, bold_ref) in bold_best.items():
        if name not in catalog and _score > 0:
            catalog[name] = FontFamily(name=name, regular=bold_ref, bold=bold_ref)

    _FONT_CATALOG = catalog
    return catalog


def resolve_font_family(preferred: str) -> Optional[str]:
    """Match a family name case-insensitively against the catalog."""
    catalog = get_font_catalog()
    if preferred in catalog:
        return preferred
    low = preferred.lower()
    for name in catalog:
        if name.lower() == low:
            return name
    return None


def pick_default_font_family() -> str:
    """Helvetica Neue → Arial → other common sans → first installed."""
    catalog = get_font_catalog()
    for name in (
        DEFAULT_FONT_NAME,
        FALLBACK_FONT_NAME,
        "Helvetica",
        "Liberation Sans",
        "DejaVu Sans",
        "Noto Sans",
        "FreeSans",
        "Segoe UI",
        "Calibri",
    ):
        resolved = resolve_font_family(name)
        if resolved:
            return resolved
    if catalog:
        return sorted(catalog, key=str.lower)[0]
    return DEFAULT_FONT_NAME


def load_truetype_font(
    family: str,
    size: int,
    *,
    bold: bool = False,
) -> ImageFont.ImageFont:
    """Load a PIL font for family, with Helvetica Neue → Arial → default fallbacks."""
    size = max(1, int(size))
    catalog = get_font_catalog()
    tried: set[tuple[str, int]] = set()

    def try_ref(ref: FontRef) -> Optional[ImageFont.ImageFont]:
        key = (ref.path, ref.index)
        if key in tried:
            return None
        tried.add(key)
        try:
            return ImageFont.truetype(ref.path, size, index=ref.index)
        except (OSError, ValueError, SyntaxError):
            return None

    def try_family(name: str) -> Optional[ImageFont.ImageFont]:
        resolved = resolve_font_family(name)
        if not resolved:
            return None
        face = catalog[resolved]
        if bold and face.bold is not None:
            font = try_ref(face.bold)
            if font is not None:
                return font
        return try_ref(face.regular)

    for name in (family, DEFAULT_FONT_NAME, FALLBACK_FONT_NAME):
        font = try_family(name)
        if font is not None:
            return font

    # Last-resort hard-coded paths across platforms
    hard = [
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    for path in hard:
        if not Path(path).is_file():
            continue
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError, SyntaxError):
            continue
    return ImageFont.load_default()


def fuzzy_match_score(query: str, candidate: str) -> Optional[float]:
    """
    Rank how well candidate matches query (higher is better).
    None means no match. Supports subsequence fuzzy matching
    (e.g. 'hlv' → 'Helvetica', 'neue' → 'Helvetica Neue').
    """
    q = query.strip().lower()
    if not q:
        return 0.0
    c = candidate.lower()
    if c == q:
        return 10_000.0
    if c.startswith(q):
        return 9_000.0 - len(c) * 0.01
    if q in c:
        return 8_000.0 - c.find(q) * 0.5 - len(c) * 0.01

    # Word-prefix: each query token starts a word in the name
    q_words = [w for w in q.replace("-", " ").replace("_", " ").split() if w]
    c_words = [w for w in c.replace("-", " ").replace("_", " ").split() if w]
    if q_words and all(
        any(cw.startswith(qw) for cw in c_words) for qw in q_words
    ):
        return 7_500.0 - len(c) * 0.01

    # Subsequence match with bonuses for consecutive / word-boundary hits
    qi = 0
    score = 0.0
    prev = -99
    consecutive = 0
    for ci, ch in enumerate(c):
        if qi >= len(q):
            break
        if ch != q[qi]:
            continue
        score += 10.0
        if ci == prev + 1:
            consecutive += 1
            score += 8.0 * consecutive
        else:
            consecutive = 0
        if ci == 0 or c[ci - 1] in " -_./":
            score += 20.0
        prev = ci
        qi += 1
    if qi < len(q):
        return None
    score -= len(c) * 0.15
    return score


def fuzzy_filter_fonts(
    query: str,
    families: list[str],
    *,
    limit: int = 60,
) -> list[str]:
    """Return installed font families ranked by fuzzy match to query."""
    if not query.strip():
        return list(families)
    scored: list[tuple[float, str]] = []
    for name in families:
        score = fuzzy_match_score(query, name)
        if score is not None:
            scored.append((score, name))
    scored.sort(key=lambda t: (-t[0], t[1].lower()))
    return [name for _, name in scored[:limit]]


def format_distance_list(distances: list[float]) -> str:
    parts = []
    for d in distances:
        if abs(d - round(d)) < 1e-9:
            parts.append(str(int(round(d))))
        else:
            parts.append(f"{d:g}")
    return ", ".join(parts)


def parse_distance_list(text: str) -> list[float]:
    """
    Parse comma-separated metres. Spaces are ignored.
    Order and duplicates are allowed.
    """
    cleaned = text.replace(" ", "")
    if not cleaned.strip():
        raise ValueError("Distance list is empty")
    parts = [p for p in cleaned.split(",") if p != ""]
    if not parts:
        raise ValueError("Distance list is empty")
    out: list[float] = []
    for part in parts:
        try:
            val = float(part)
        except ValueError as e:
            raise ValueError(
                f"Invalid distance {part!r} — use comma-separated numbers "
                f"(e.g. 0.8, 1, 1.5, 2)"
            ) from e
        if not math.isfinite(val) or val <= 0:
            raise ValueError(f"Distances must be finite and > 0 (got {part!r})")
        out.append(val)
    return out


class FocusingScaleGenerator:
    """Focus scale strip — visual design aligned with distance_markers.py."""

    def __init__(
        self,
        focal_length: float,
        diameter: float,
        max_extension: float,
        throw_deg: float,
        error: float = 0.0,
        ffd: float = 0.0,
        dpi: int = 300,
        height: float = 3.0,
        tick_length: float = 0.5,
        padding: float = 0.3,
        vertical_offset: float = 0.5,
        target_distances: Optional[list[float]] = None,
        page_size: str = "Letter",
        mark_mode: str = "fixed",
        min_gap_mm: float = 3.5,
        min_rel: float = 0.08,
        min_abs_m: float = 0.05,
        text_color: str = DEFAULT_TEXT_COLOR,
        tick_color: str = DEFAULT_TICK_COLOR,
        color_stripe: bool = True,
        stripe_color: str = DEFAULT_STRIPE_COLOR,
        font_name: str = "Helvetica Neue",
        font_size: int = DEFAULT_FONT_SIZE,
        font_bold: bool = False,
        wrap_buffer_mm: float = 5.0,
    ):
        self.focal_length = focal_length
        self.diameter = diameter
        self.max_extension = max_extension
        if throw_deg <= 0:
            raise ValueError("Throw must be > 0 degrees (may exceed 360)")
        self.throw_deg = throw_deg
        self.error = error
        self.ffd = ffd
        self.dpi = dpi
        self.height = height
        self.tick_length = tick_length
        self.padding = padding
        self.vertical_offset = vertical_offset
        self.target_distances = target_distances or list(DEFAULT_TARGET_DISTANCES)
        if page_size not in PAGE_SIZES_MM:
            raise ValueError(f"page_size must be one of {list(PAGE_SIZES_MM)}")
        self.page_size = page_size
        if mark_mode not in MARK_MODES:
            raise ValueError(f"mark_mode must be one of {MARK_MODES}")
        self.mark_mode = mark_mode
        self.min_gap_mm = min_gap_mm
        self.min_rel = min_rel
        self.min_abs_m = min_abs_m
        self.text_color = text_color
        self.tick_color = tick_color
        self.color_stripe = color_stripe
        self.stripe_color = stripe_color
        self.font_name = font_name
        self.font_size = max(1, int(font_size))
        self.font_bold = font_bold
        if wrap_buffer_mm < 0:
            raise ValueError("Wrap buffer must be ≥ 0 mm")
        self.wrap_buffer_mm = wrap_buffer_mm

        self.circumference = math.pi * diameter
        if self.wrap_buffer_mm >= self.circumference:
            raise ValueError(
                f"Wrap buffer ({wrap_buffer_mm:g} mm) must be less than "
                f"circumference ({self.circumference:.2f} mm)"
            )
        self.wrap_segment_mm = self.circumference - self.wrap_buffer_mm
        # Physical helicoid travel (retract → full extension)
        self.throw_arc = self.circumference * throw_deg / 360.0
        if max_extension <= 0:
            raise ValueError("Helicoid extension must be > 0 mm")
        self.arc_per_mm = self.throw_arc / max_extension
        # Positive error: infinity lies before retract. Print a pre-buffer so ∞
        # and far marks remain on the strip; align helicoid retract to retract_x.
        self.scale_ext_min = -max(0.0, self.error)
        self.pre_buffer_arc = -self.scale_ext_min * self.arc_per_mm
        self.retract_x = self.pre_buffer_arc
        self.scale_length = (
            self.max_extension - self.scale_ext_min
        ) * self.arc_per_mm
        self.last_scale_factor = 1.0
        self.last_landscape = False
        self.last_row_count = 1
        self.last_page_count = 1
        self.last_wrap_count = max(
            1, int(math.ceil(self.scale_length / self.wrap_segment_mm))
        )

    # --- optics (error shifts the infinity position) ---

    def infinity_extension(self) -> float:
        """Helicoid extension from retract at which focus is infinity."""
        return -self.error

    def extension_beyond_infinity(self, helicoid_extension: float) -> float:
        return helicoid_extension - self.infinity_extension()

    def object_distance_from_extension(self, helicoid_extension: float) -> float:
        """Object distance in metres. inf if at/past infinity."""
        delta = self.extension_beyond_infinity(helicoid_extension)
        if delta <= 0:
            return float("inf")
        f = self.focal_length
        return (f * (f + delta)) / (1000.0 * delta)

    def extension_from_object_distance(self, distance_m: float) -> Optional[float]:
        """Helicoid extension from retract for a focus distance in metres."""
        if distance_m == float("inf"):
            return self.infinity_extension()
        denominator = 1000.0 * distance_m - self.focal_length
        if denominator <= 0:
            return None
        delta = (self.focal_length**2) / denominator
        return self.infinity_extension() + delta

    def _extension_on_scale(self, extension: float) -> bool:
        """True if this helicoid extension falls on the printed strip."""
        return self.scale_ext_min - 1e-9 <= extension <= self.max_extension + 1e-9

    def _x_from_extension(self, extension: float) -> float:
        """Scale X (mm from strip start) for a helicoid extension."""
        return (extension - self.scale_ext_min) * self.arc_per_mm

    def _x_for_distance(self, distance_m: float) -> Optional[float]:
        """Scale position (mm) for a focus distance, or None if off the strip."""
        extension = self.extension_from_object_distance(distance_m)
        if extension is None or not self._extension_on_scale(extension):
            return None
        return self._x_from_extension(extension)

    def _nice_distance_candidates(self, near_m: float, far_m: float) -> list[float]:
        """
        Round, photographer-friendly focus distances spanning the usable range
        (excluding the near tip, which gets its own terminal mark).
        """
        if far_m == float("inf"):
            far_cap = max(100.0, near_m * 80.0)
        else:
            far_cap = far_m

        # Dense near the camera, coarser farther out — all "round" values.
        palette = [
            *[round(0.05 * i, 2) for i in range(4, 20)],  # 0.20 … 0.95
            *[round(0.1 * i, 1) for i in range(10, 30)],  # 1.0 … 2.9
            3, 3.5, 4, 4.5, 5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40, 50, 60, 70, 80,
            100, 120, 150, 200, 300, 500,
        ]
        return [d for d in palette if near_m + 1e-6 < d < far_cap - 1e-9]

    def _dynamic_target_distances(self) -> list[float]:
        """
        Choose marks from nice distances using:
          - minimum physical spacing along the scale (label room)
          - minimum focus-distance delta (relative or absolute)
        Far marks are placed first so the cramped infinity end isn't overcrowded.
        """
        near_m = self.object_distance_from_extension(self.max_extension)
        if near_m == float("inf"):
            return []
        # Far end of the *printed* strip (∞ when positive error adds a pre-buffer)
        far_m = self.object_distance_from_extension(self.scale_ext_min)

        # Tunable thresholds (GUI sliders)
        min_gap_mm = self.min_gap_mm
        min_rel = self.min_rel
        min_abs = self.min_abs_m

        candidates = self._nice_distance_candidates(near_m, far_m)
        placed_x: list[float] = []
        placed_d: list[float] = []

        # Reserve space for infinity (if present) and the terminal tip
        e_inf = self.infinity_extension()
        reserved: list[float] = []
        if self._extension_on_scale(e_inf):
            reserved.append(self._x_from_extension(e_inf))
        reserved.append(self.scale_length)

        for d in sorted(candidates, reverse=True):  # far → near
            x = self._x_for_distance(d)
            if x is None:
                continue
            if any(abs(x - rx) < min_gap_mm for rx in reserved):
                continue
            if any(abs(x - px) < min_gap_mm for px in placed_x):
                continue
            if placed_d:
                # Compare to physically nearest already-placed mark
                nearest_d = min(
                    placed_d,
                    key=lambda pd: abs((self._x_for_distance(pd) or 0.0) - x),
                )
                abs_delta = abs(d - nearest_d)
                rel_delta = abs_delta / max(nearest_d, d, 1e-6)
                if rel_delta < min_rel and abs_delta < min_abs:
                    continue
            placed_x.append(x)
            placed_d.append(d)

        return sorted(placed_d)

    def _mark_distances(self) -> list[float]:
        if self.mark_mode == "dynamic":
            return self._dynamic_target_distances()
        return list(self.target_distances)

    def _calculate_scale_positions(self) -> tuple[list[float], list[float]]:
        """X positions (mm along strip) and distances (m) for marks."""
        positions: list[float] = []
        distances: list[float] = []

        e_inf = self.infinity_extension()
        if self._extension_on_scale(e_inf):
            positions.append(self._x_from_extension(e_inf))
            distances.append(float("inf"))

        for distance in self._mark_distances():
            extension = self.extension_from_object_distance(distance)
            if extension is None or not self._extension_on_scale(extension):
                continue
            x = self._x_from_extension(extension)
            if any(abs(x - p) < 0.25 for p in positions):
                continue
            positions.append(x)
            distances.append(distance)

        # Always put a terminal mark at full extension (rounded to 0.01 m)
        near_m = self.object_distance_from_extension(self.max_extension)
        if near_m != float("inf"):
            end_m = round(near_m * 100.0) / 100.0
            kept_p: list[float] = []
            kept_d: list[float] = []
            for p, d in zip(positions, distances):
                if p < self.scale_length - 1.0:
                    kept_p.append(p)
                    kept_d.append(d)
            positions = kept_p
            distances = kept_d
            positions.append(self.scale_length)
            distances.append(end_m)

        order = sorted(zip(positions, distances), key=lambda t: t[0])
        return [p for p, _ in order], [d for _, d in order]

    # --- drawing (copied layout rules from distance_markers.py) ---

    def _mm_to_pixels(self, mm: float) -> int:
        # round() (not truncating int) so printed mm stay faithful at the given DPI
        return max(1, int(round(mm * self.dpi / 25.4))) if mm > 0 else 0

    def _format_distance_text(self, distance: float) -> str:
        if distance == float("inf"):
            return "∞"
        if distance < 1.0:
            formatted = f"{distance:.2f}"
        else:
            formatted = (
                f"{distance:.1f}" if distance != int(distance) else f"{int(distance)}"
            )
        return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted

    def _load_font(self, font_size: Optional[int] = None) -> ImageFont.ImageFont:
        size = font_size if font_size is not None else self.font_size
        return load_truetype_font(self.font_name, size, bold=self.font_bold)

    def _calculate_text_position(
        self, x_pixel: int, text_width: int, index: int, total_positions: int
    ) -> int:
        padding_px = self._mm_to_pixels(self.padding)
        if index == 0:
            return x_pixel + padding_px
        if index == total_positions - 1:
            return x_pixel - text_width - padding_px
        return x_pixel - text_width // 2

    def _draw_tick_and_text(
        self,
        draw: ImageDraw.ImageDraw,
        font: ImageFont.ImageFont,
        x_positions: list[float],
        distances: list[float],
        image_dims: tuple[int, int],
    ) -> None:
        width_px, height_px = image_dims
        tick_length_px = self._mm_to_pixels(self.tick_length)
        vertical_offset_px = self._mm_to_pixels(self.vertical_offset)

        for i, (x_mm, distance) in enumerate(zip(x_positions, distances)):
            stroke = 2
            max_x = width_px - 1 - stroke // 2
            x_px = min(self._mm_to_pixels(x_mm), max_x)
            if x_px < 0:
                continue

            y_bottom = height_px - 1
            y_top = max(0, y_bottom - tick_length_px)
            draw.line(
                [(x_px, y_bottom), (x_px, y_top)],
                fill=self.tick_color,
                width=stroke,
            )

            text = self._format_distance_text(distance)
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            text_x = self._calculate_text_position(
                x_px, text_width, i, len(x_positions)
            )
            text_x = max(0, min(text_x, width_px - text_width))
            text_y = (height_px - text_height) // 2 - vertical_offset_px
            draw.text((text_x, text_y), text, fill=self.text_color, font=font)

    def create_scale(self) -> Image.Image:
        """Full continuous scale strip at 1:1 (width = printed scale length)."""
        width_mm = self.scale_length
        width_px = self._mm_to_pixels(width_mm)
        height_px = self._mm_to_pixels(self.height)

        img = Image.new("RGB", (width_px, height_px), "black")
        draw = ImageDraw.Draw(img)

        # Unreachable pre-buffer (positive error): faint hatch + dotted retract line.
        # Align helicoid retract to the dotted boundary.
        if self.pre_buffer_arc > 0.05:
            pre_px = min(width_px, self._mm_to_pixels(self.pre_buffer_arc))
            if pre_px > 0:
                # ~30% opacity white diagonal stripes over black
                hatch = Image.new("RGBA", (pre_px, height_px), (0, 0, 0, 0))
                hdraw = ImageDraw.Draw(hatch)
                stripe = (255, 255, 255, int(round(255 * 0.30)))
                step = max(3, self._mm_to_pixels(1.2))
                line_w = max(1, self._mm_to_pixels(0.25))
                for i in range(-height_px * 2, pre_px + height_px * 2, step):
                    hdraw.line(
                        [(i, 0), (i + height_px, height_px)],
                        fill=stripe,
                        width=line_w,
                    )
                base = img.convert("RGBA")
                overlay = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
                overlay.paste(hatch, (0, 0))
                img = Image.alpha_composite(base, overlay).convert("RGB")
                draw = ImageDraw.Draw(img)
            rx = min(width_px - 1, self._mm_to_pixels(self.retract_x))
            dash = max(2, self._mm_to_pixels(0.45))
            gap = max(1, self._mm_to_pixels(0.35))
            y = 0
            while y < height_px:
                y_end = min(height_px - 1, y + dash - 1)
                draw.line([(rx, y), (rx, y_end)], fill=self.tick_color, width=1)
                y = y_end + 1 + gap

        font = self._load_font(self.font_size)

        x_positions, distances = self._calculate_scale_positions()
        if not x_positions:
            raise ValueError(
                "No focus marks fall within helicoid travel. "
                "Check focal length, extension, throw, and error."
            )
        self._draw_tick_and_text(draw, font, x_positions, distances, (width_px, height_px))
        return img

    def _page_dims_mm(self, landscape: bool) -> tuple[float, float]:
        w, h = PAGE_SIZES_MM[self.page_size]
        return (h, w) if landscape else (w, h)

    def _usable_mm(self, landscape: bool) -> tuple[float, float]:
        page_w, page_h = self._page_dims_mm(landscape)
        return page_w - 2 * PAGE_MARGIN_MM, page_h - 2 * PAGE_MARGIN_MM

    def _layout_plan(self) -> tuple[bool, float, int]:
        """
        Returns (landscape, content_mm_per_row, row_count).
        Rows break for page width and at each helicoid circumference − wrap buffer.
        """
        strip_w = self.scale_length
        row_h = self.height
        wrap_seg = self.wrap_segment_mm

        for landscape in (False, True):
            usable_w, usable_h = self._usable_mm(landscape)
            if (
                strip_w <= usable_w + 1e-6
                and strip_w <= wrap_seg + 1e-6
                and row_h <= usable_h + 1e-6
            ):
                return landscape, strip_w, 1

        landscape = True
        usable_w, _ = self._usable_mm(landscape)
        left_oh = max(LEFT_LABEL_MM, WRAP_MARKER_MM + WRAP_GAP_MM)
        right_oh = max(STRIPE_MM, WRAP_MARKER_MM + WRAP_GAP_MM)
        overhead = left_oh + right_oh
        page_budget = usable_w - overhead
        if page_budget < 20:
            landscape = False
            usable_w, _ = self._usable_mm(landscape)
            page_budget = usable_w - overhead
        if page_budget <= 1:
            raise ValueError("Page is too narrow for a 1:1 scale row")
        content_per_row = min(page_budget, wrap_seg)
        row_count = int(math.ceil(strip_w / content_per_row))
        return landscape, content_per_row, row_count

    def _content_px_for_page(self, landscape: bool, multi_row: bool) -> int:
        """Max scale pixels per row from page usable width (excludes label/stripe)."""
        page_w_mm, _ = self._page_dims_mm(landscape)
        page_w = self._mm_to_pixels(page_w_mm)
        margin_px = self._mm_to_pixels(PAGE_MARGIN_MM)
        usable = page_w - 2 * margin_px
        if not multi_row:
            return min(self._mm_to_pixels(self.scale_length), usable)
        left_px = self._mm_to_pixels(max(LEFT_LABEL_MM, WRAP_MARKER_MM + WRAP_GAP_MM))
        right_px = self._mm_to_pixels(max(STRIPE_MM, WRAP_MARKER_MM + WRAP_GAP_MM))
        return max(1, usable - left_px - right_px)

    def _row_segments(
        self, total_px: int, page_content_px: int
    ) -> list[tuple[int, int, bool, int]]:
        """
        Split the strip into rows.
        Returns (start_px, end_px, is_wrap_boundary, wrap_lap_1based).
        Wrap boundaries occur every (circumference − wrap_buffer) of scale length.
        Page width may add extra breaks inside a lap.
        """
        wrap_px = max(1, self._mm_to_pixels(self.wrap_segment_mm))
        page_px = max(1, page_content_px)
        segments: list[tuple[int, int, bool, int]] = []
        pos = 0
        while pos < total_px:
            lap = pos // wrap_px
            next_wrap = (lap + 1) * wrap_px
            end = min(total_px, next_wrap, pos + page_px)
            if end <= pos:
                end = min(total_px, pos + 1)
            is_wrap = end < total_px and end == next_wrap
            wrap_lap = lap + 1 if is_wrap else 0
            segments.append((pos, end, is_wrap, wrap_lap))
            pos = end
        return segments

    def _join_label(self, index: int) -> str:
        """A, B, … Z, AA, … for in-lap page joins."""
        label = ""
        n = index
        while True:
            label = chr(ord("A") + (n % 26)) + label
            n = n // 26 - 1
            if n < 0:
                break
        return label

    def _wrap_label(self, lap: int) -> str:
        """Special indicator at a full-circumference wrap break."""
        return f"W{lap}"

    def _left_gutter_px(self) -> int:
        return self._mm_to_pixels(max(LEFT_LABEL_MM, WRAP_MARKER_MM + WRAP_GAP_MM))

    def _draw_label_badge(
        self,
        draw: ImageDraw.ImageDraw,
        label: str,
        cx: int,
        cy: int,
        font: ImageFont.ImageFont,
    ) -> None:
        """Letter on a solid rectangle so it stays readable on stripes / page."""
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = max(1, self._mm_to_pixels(0.4))
        x0 = cx - tw // 2 - pad
        y0 = cy - th // 2 - pad
        x1 = cx + (tw + 1) // 2 + pad
        y1 = cy + (th + 1) // 2 + pad
        draw.rectangle([x0, y0, x1, y1], fill="white", outline="black", width=1)
        # textbbox origin isn't always (0,0); offset by bbox mins
        draw.text(
            (cx - tw // 2 - bbox[0], cy - th // 2 - bbox[1]),
            label,
            fill="black",
            font=font,
        )

    def _draw_left_gutter(
        self,
        kind: Optional[str],
        label: Optional[str],
        height_px: int,
    ) -> Image.Image:
        """
        Fixed-width left gutter so multi-row scales align.
        kind 'join' → letter badge near the scale (page glue match).
        kind 'wrap' → detached wrap marker with air gap before the scale.
        """
        w = self._left_gutter_px()
        img = Image.new("RGB", (w, height_px), "white")
        if kind == "wrap" and label:
            marker = self._draw_wrap_marker(label, height_px)
            gap = self._mm_to_pixels(WRAP_GAP_MM)
            # Marker on the outer (left) side; gap touches the scale edge
            img.paste(marker, (max(0, w - marker.width - gap), 0))
        elif kind == "join" and label:
            draw = ImageDraw.Draw(img)
            font = self._load_font(max(8, int(height_px * 0.55)))
            # Keep letter close to the scale (right side of gutter)
            cx = w - self._mm_to_pixels(LEFT_LABEL_MM) // 2
            self._draw_label_badge(draw, label, cx, height_px // 2, font)
        return img

    def _draw_gap(self, height_px: int) -> Image.Image:
        return Image.new("RGB", (self._mm_to_pixels(WRAP_GAP_MM), height_px), "white")

    def _draw_wrap_marker(self, label: str, height_px: int) -> Image.Image:
        """
        Detached wrap indicator — not a glue tab, never touches the scale.
        Dashed outline + chevron, distinct from A/B striped tabs.
        """
        w = self._mm_to_pixels(WRAP_MARKER_MM)
        img = Image.new("RGB", (w, height_px), "white")
        draw = ImageDraw.Draw(img)
        ink = "#222222"
        # Inset dashed frame
        inset = max(1, self._mm_to_pixels(0.35))
        x0, y0, x1, y1 = inset, inset, w - 1 - inset, height_px - 1 - inset
        dash = max(2, self._mm_to_pixels(0.7))
        gap = max(1, self._mm_to_pixels(0.45))
        # Top / bottom dashes
        x = x0
        while x <= x1:
            x_end = min(x1, x + dash - 1)
            draw.line([(x, y0), (x_end, y0)], fill=ink, width=1)
            draw.line([(x, y1), (x_end, y1)], fill=ink, width=1)
            x += dash + gap
        # Left / right dashes
        y = y0
        while y <= y1:
            y_end = min(y1, y + dash - 1)
            draw.line([(x0, y), (x0, y_end)], fill=ink, width=1)
            draw.line([(x1, y), (x1, y_end)], fill=ink, width=1)
            y += dash + gap
        # Small chevron pointing onward (wrap continues)
        mid_y = height_px // 2
        ch_x = w - self._mm_to_pixels(1.8)
        ch = max(2, self._mm_to_pixels(1.1))
        draw.line([(ch_x - ch, mid_y - ch), (ch_x, mid_y)], fill=ink, width=2)
        draw.line([(ch_x, mid_y), (ch_x - ch, mid_y + ch)], fill=ink, width=2)
        font = self._load_font(max(7, int(height_px * 0.48)))
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = max(inset + 1, (w - tw) // 2 - self._mm_to_pixels(0.6))
        ty = (height_px - th) // 2 - bbox[1]
        draw.text((tx, ty), label, fill=ink, font=font)
        return img

    def _draw_stripe_tab(self, label: str, height_px: int) -> Image.Image:
        """5 mm striped glue tab for page-width joins — not used for wraps."""
        w = self._mm_to_pixels(STRIPE_MM)
        img = Image.new("RGB", (w, height_px), "white")
        draw = ImageDraw.Draw(img)
        hatch = self.stripe_color if self.color_stripe else "#888888"
        step = max(4, self._mm_to_pixels(1.4))
        line_w = max(1, self._mm_to_pixels(0.35))
        for i in range(-height_px * 2, w + height_px * 2, step):
            draw.line(
                [(i, 0), (i + height_px, height_px)],
                fill=hatch,
                width=line_w,
            )
        draw.rectangle([0, 0, w - 1, height_px - 1], outline=hatch, width=1)
        font = self._load_font(max(7, int(height_px * 0.5)))
        self._draw_label_badge(draw, label, w // 2, height_px // 2, font)
        return img

    def _build_row_image(
        self,
        strip: Image.Image,
        start_px: int,
        end_px: int,
        left_kind: Optional[str],
        left_label: Optional[str],
        right_kind: Optional[str],
        right_label: Optional[str],
        *,
        pad_left: bool,
    ) -> Image.Image:
        chunk = strip.crop((start_px, 0, end_px, strip.height))
        parts: list[Image.Image] = []
        if pad_left:
            parts.append(self._draw_left_gutter(left_kind, left_label, strip.height))
        parts.append(chunk)
        if right_kind == "join" and right_label is not None:
            parts.append(self._draw_stripe_tab(right_label, strip.height))
        elif right_kind == "wrap" and right_label is not None:
            parts.append(self._draw_gap(strip.height))
            parts.append(self._draw_wrap_marker(right_label, strip.height))

        row_w = sum(p.width for p in parts)
        row = Image.new("RGB", (row_w, strip.height), "white")
        x = 0
        for part in parts:
            row.paste(part, (x, 0))
            x += part.width
        return row

    def create_pages(self) -> list[Image.Image]:
        """One or more Letter/A4 pages with 1:1 rows; stripe tabs on overflows."""
        strip = self.create_scale()
        landscape, _content_mm, _plan_rows = self._layout_plan()
        self.last_scale_factor = 1.0
        self.last_landscape = landscape

        multi = _plan_rows > 1 or self.scale_length > self.wrap_segment_mm + 1e-6
        page_content_px = self._content_px_for_page(landscape, multi)
        # Also cap by wrap segment
        wrap_px = max(1, self._mm_to_pixels(self.wrap_segment_mm))
        page_content_px = min(page_content_px, wrap_px) if multi else page_content_px

        segments = self._row_segments(strip.width, page_content_px)
        row_count = len(segments)
        self.last_row_count = row_count
        self.last_wrap_count = max(
            1, int(math.ceil(self.scale_length / self.wrap_segment_mm))
        )

        page_w_mm, page_h_mm = self._page_dims_mm(landscape)
        page_w = self._mm_to_pixels(page_w_mm)
        page_h = self._mm_to_pixels(page_h_mm)
        margin_px = self._mm_to_pixels(PAGE_MARGIN_MM)
        gap_px = self._mm_to_pixels(ROW_GAP_MM)
        caption_reserve = self._mm_to_pixels(12)
        pad_left = row_count > 1

        rows: list[Image.Image] = []
        scale_px_accounted = 0
        letter_i = 0
        prev_right_kind: Optional[str] = None
        prev_right_label: Optional[str] = None
        for i, (start, end, is_wrap, wrap_lap) in enumerate(segments):
            scale_px_accounted += end - start
            continues = end < strip.width
            if i == 0:
                left_kind, left_label = None, None
            else:
                left_kind, left_label = prev_right_kind, prev_right_label
            if continues:
                if is_wrap:
                    right_kind, right_label = "wrap", self._wrap_label(wrap_lap)
                else:
                    right_kind, right_label = "join", self._join_label(letter_i)
                    letter_i += 1
            else:
                right_kind, right_label = None, None
            prev_right_kind, prev_right_label = right_kind, right_label
            rows.append(
                self._build_row_image(
                    strip,
                    start,
                    end,
                    left_kind,
                    left_label,
                    right_kind,
                    right_label,
                    pad_left=pad_left,
                )
            )
        if scale_px_accounted != strip.width:
            raise RuntimeError(
                f"Scale length not preserved: accounted {scale_px_accounted}px "
                f"of {strip.width}px ({self.scale_length:.3f} mm)"
            )


        pages: list[Image.Image] = []
        y = margin_px + self._mm_to_pixels(12)
        page = Image.new("RGB", (page_w, page_h), "white")
        caption_font = self._load_font(max(10, self._mm_to_pixels(2.2)))
        orient = "landscape" if landscape else "portrait"

        def finish_page(p: Image.Image) -> None:
            if row_count > 1:
                wraps = max(0, self.last_wrap_count - 1)
                join_note = (
                    f"A/B… striped tab = page glue join; "
                    f"detached WN = wrap after {self.wrap_segment_mm:.0f} mm"
                )
                if wraps:
                    join_note += f" · {wraps} wrap{'s' if wraps != 1 else ''}"
            else:
                join_note = "single row"
            note = (
                f"{self.page_size} {orient}  ·  1:1  ·  "
                f"{row_count} row{'s' if row_count != 1 else ''}  ·  "
                f"{join_note}  ·  print at 100%"
            )
            d = ImageDraw.Draw(p)
            bbox = d.textbbox((0, 0), note, font=caption_font)
            tw = bbox[2] - bbox[0]
            d.text(
                ((page_w - tw) // 2, page_h - margin_px - self._mm_to_pixels(5)),
                note,
                fill="#333333",
                font=caption_font,
            )
            pages.append(p)

        # Flush with left margin; width is capped to usable area
        row_x = margin_px
        row_on_page_start = 0
        for idx, row in enumerate(rows):
            # Safety: never paste past the right margin
            max_w = page_w - 2 * margin_px
            if row.width > max_w:
                raise RuntimeError(
                    f"Row width {row.width}px exceeds usable {max_w}px — layout bug"
                )
            need_h = row.height + gap_px
            if y + row.height + caption_reserve > page_h - margin_px and idx > row_on_page_start:
                finish_page(page)
                page = Image.new("RGB", (page_w, page_h), "white")
                y = margin_px + self._mm_to_pixels(12)
                row_on_page_start = idx
            page.paste(row, (row_x, y))
            d = ImageDraw.Draw(page)
            d.text(
                (row_x, y - self._mm_to_pixels(3.5)),
                f"{idx + 1}/{row_count}",
                fill="#888888",
                font=self._load_font(max(8, self._mm_to_pixels(1.8))),
            )
            y += need_h

        finish_page(page)
        self.last_page_count = len(pages)
        return pages

    def create_page(self) -> Image.Image:
        """First page (compat). Prefer create_pages() for full output."""
        return self.create_pages()[0]

    def suggested_filename(self, ext: str = ".pdf") -> str:
        """Encode major helicoid/lens params into a filesystem-safe basename."""

        def num(v: float) -> str:
            if abs(v - round(v)) < 1e-9:
                return str(int(round(v)))
            return f"{v:g}"

        parts = [
            "focus_scale",
            f"f{num(self.focal_length)}",
            f"d{num(self.diameter)}",
            f"t{num(self.throw_deg)}",
            f"e{num(self.max_extension)}",
        ]
        if abs(self.error) > 1e-9:
            err = num(self.error)
            parts.append(f"err{err}" if err.startswith("-") else f"err+{err}")
        if self.ffd:
            parts.append(f"ffd{num(self.ffd)}")
        parts.append(self.mark_mode)
        name = "_".join(parts)
        if not ext.startswith("."):
            ext = "." + ext
        return name + ext.lower()

    def save(self, path: str) -> Image.Image:
        """Save PNG strip, or multipage PDF at true 1:1."""
        lower = path.lower()
        if lower.endswith(".pdf"):
            pages = self.create_pages()
            if len(pages) == 1:
                pages[0].save(path, "PDF", resolution=float(self.dpi))
            else:
                pages[0].save(
                    path,
                    "PDF",
                    resolution=float(self.dpi),
                    save_all=True,
                    append_images=pages[1:],
                )
            return pages[0]

        img = self.create_scale()
        if not lower.endswith(".png"):
            path = path + ".png"
        img.save(path, dpi=(self.dpi, self.dpi))
        self.last_scale_factor = 1.0
        self.last_landscape = False
        self.last_row_count = 1
        self.last_page_count = 1
        return img

    def preview_summary(self) -> str:
        near = self.object_distance_from_extension(self.max_extension)
        far_retract = self.object_distance_from_extension(0.0)
        far_strip = self.object_distance_from_extension(self.scale_ext_min)
        e_inf = self.infinity_extension()
        near_s = "∞" if near == float("inf") else f"{near:.3f} m"
        far_retract_s = (
            "∞ / past ∞" if far_retract == float("inf") else f"{far_retract:.3f} m"
        )

        landscape, content_mm, row_count = self._layout_plan()
        orient = "landscape" if landscape else "portrait"
        page_note = (
            f"{self.page_size} {orient} · 1:1 · "
            f"{row_count} row{'s' if row_count != 1 else ''}"
        )
        if row_count > 1:
            page_note += (
                f" (~{content_mm:.0f} mm scale + {STRIPE_MM:g} mm striped glue tab)"
            )

        wraps = max(0, self.last_wrap_count - 1)
        lines = [
            f"Throw arc: {self.throw_arc:.2f} mm "
            f"({self.throw_deg:g}° / 360 of Ø{self.diameter:g})",
            f"Printed length: {self.scale_length:.2f} mm "
            f"({self.scale_length:.2f} × {self.height:g} mm @ {self.dpi} DPI)",
            f"Circumference: {self.circumference:.2f} mm · "
            f"wrap every {self.wrap_segment_mm:.2f} mm "
            f"(buffer {self.wrap_buffer_mm:g} mm)",
            f"PDF page: {page_note}",
        ]
        if self.pre_buffer_arc > 0.05:
            lines.append(
                f"Pre-buffer: {self.pre_buffer_arc:.2f} mm "
                f"(align helicoid retract to the dotted line; "
                f"∞ and farther marks are visible but unreachable)"
            )
        if wraps:
            lines.append(
                f"Wraps: {wraps} forced break{'s' if wraps != 1 else ''} "
                f"(W1…W{wraps}) at circumference − buffer"
            )
        lines.extend(
            [
                f"Mark mode: {self.mark_mode} · "
                f"{len(self._calculate_scale_positions()[0])} marks",
                f"Focus at helicoid travel: {near_s} ← → {far_retract_s}",
            ]
        )
        if 0 <= e_inf <= self.max_extension:
            lines.append(f"Infinity at {e_inf:.2f} mm extension")
        elif e_inf < 0:
            lines.append(
                f"Infinity {-e_inf:.2f} mm before retract "
                f"(printed in pre-buffer; unreachable)"
            )
        else:
            lines.append(f"Infinity at {e_inf:.2f} mm (beyond throw)")
        if far_strip == float("inf") and far_retract != float("inf"):
            lines.append(
                f"Focus at retract: {far_retract_s} · strip still shows ∞"
            )
        if self.ffd:
            lines.append(
                f"FFD {self.ffd:g} mm + error {self.error:+g} mm "
                f"→ {self.ffd + self.error:g} mm at retract"
            )
        lines.append(
            "Join: A/B… striped glue tabs for page joins; "
            "detached WN markers (gap from scale) for circumference wraps"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

DEFAULTS = {
    "diameter": "80",
    "extension": "30",
    "ffd": "131.3",
    "throw": "300",
    "focal": "135",
    "scale_height": "3",
    "error": "0",
    "wrap_buffer": "5",
    "page_size": "Letter",
    "mark_mode": "fixed",
    "min_gap_mm": 3.5,
    "min_rel": 0.08,
    "min_abs_m": 0.05,
    "text_color": DEFAULT_TEXT_COLOR,
    "tick_color": DEFAULT_TICK_COLOR,
    "color_stripe": True,
    "stripe_color": DEFAULT_STRIPE_COLOR,
    "font_name": DEFAULT_FONT_NAME,
    "font_size": str(DEFAULT_FONT_SIZE),
    "font_bold": False,
}

FIELDS = [
    ("diameter", "Helicoid diameter", "mm"),
    ("extension", "Helicoid extension", "mm"),
    ("ffd", "Focal flange distance", "mm"),
    ("throw", "Throw", "deg"),
    ("focal", "Focal distance", "mm"),
    ("scale_height", "Scale height", "mm"),
    ("error", "Error", "mm"),
    ("wrap_buffer", "Wrap buffer", "mm"),
]

OPTION_INFO = {
    "diameter": (
        "Outer diameter of the helicoid barrel (mm).\n\n"
        "The printed scale length is (throw° / 360) × π × diameter — "
        "i.e. the arc length of the engraved band."
    ),
    "extension": (
        "How far the helicoid racks out axially over its full throw (mm).\n\n"
        "More extension → closer minimum focus."
    ),
    "ffd": (
        "Focal flange distance (mm): lens-to-film/sensor distance when the "
        "helicoid is fully retracted.\n\n"
        "Shown on the PDF for reference. Focus marks are driven by focal "
        "length, extension, and error."
    ),
    "throw": (
        "Angular rotation of the helicoid from fully retracted to fully "
        "extended (degrees). May exceed 360° for multi-turn helicoids.\n\n"
        "Example: 270° covers 75% of the circumference; 720° is two full turns.\n"
        "When scale length exceeds circumference − wrap buffer, the PDF forces "
        "a row break with a detached W1 / W2 / … marker (not a glue tab)."
    ),
    "wrap_buffer": (
        "Forced line break every (π × diameter − buffer) of scale length (mm).\n\n"
        "Default 5 mm. Gives overlap / glue margin when wrapping past one full "
        "turn. Wrap breaks use a detached dashed WN marker with a gap from the "
        "scale — distinct from A/B… striped page-join glue tabs."
    ),
    "focal": (
        "Lens focal length (mm).\n\n"
        "Focus distance follows δ = f² / (u − f), where δ is extension past "
        "the infinity position."
    ),
    "scale_height": (
        "Height of the printed scale strip (mm).\n\n"
        "This is the physical band height on the PDF at 1:1. Font size is "
        "separate — a tall strip with a small font leaves empty space."
    ),
    "error": (
        "Axial mounting error (mm).\n\n"
        "Positive: helicoid sits too far from the film → infinity is before "
        "retract (unreachable). The scale adds a pre-buffer that still prints ∞ "
        "and far marks; align the helicoid’s retract to the dotted vertical "
        "line so those marks stay visible but unused.\n"
        "Negative: helicoid sits too close → infinity is partway into the throw.\n"
        "Zero: infinity at full retract."
    ),
    "page_size": (
        "Paper size for the PDF (Letter or A4).\n\n"
        "The scale is always 1:1. Long scales tile into rows with glue tabs; "
        "orientation flips to landscape when that fits better."
    ),
    "mark_mode": (
        "fixed: place marks only at the distances you list.\n\n"
        "dynamic: pick nice round distances automatically, then thin them "
        "using min spacing and focus-distance deltas so labels don’t crowd."
    ),
    "reset_mode": (
        "Restore defaults for the current mark mode only.\n\n"
        "fixed → original comma-separated distance list.\n"
        "dynamic → default spacing / relative Δ / absolute Δ sliders."
    ),
    "text_color": "Colour of the distance numbers on the black scale strip.",
    "tick_color": "Colour of the tick marks under each distance.",
    "color_stripe": (
        "When on, the 5 mm glue tab uses your stripe colour (angled hatch).\n"
        "When off, the tab is neutral grey. The tab is never part of the "
        "scale length — glue the next row onto it."
    ),
    "stripe_color": "Hatch / border colour for the glue tab when coloured stripes are enabled.",
    "font_name": (
        "Typeface for distance labels on the scale.\n\n"
        "Type to fuzzy-search any font installed on this computer — matching "
        "names appear in a ranked list to pick from. "
        f"Default is {DEFAULT_FONT_NAME}; if missing, falls back to "
        f"{FALLBACK_FONT_NAME}."
    ),
    "font_size": (
        "Label size in pixels at 300 DPI.\n\n"
        "Independent of scale height. If the font is taller than the strip, "
        "glyphs will clip."
    ),
    "font_bold": "Draw distance labels with the bold cut of the selected font when available.",
    "fixed_distances": (
        "Metres to mark in fixed mode, comma-separated "
        "(e.g. 0.8, 1, 1.5, 2, 5, 10).\n\n"
        "Spaces are ignored. Order and duplicates are fine. "
        "Only distances reachable within your helicoid travel appear. "
        "∞ and the near-limit end mark are always added."
    ),
    "min_gap": (
        "Dynamic mode: minimum physical gap along the strip between marks (mm).\n\n"
        "Higher → fewer marks, less label collision."
    ),
    "min_rel": (
        "Dynamic mode: a candidate mark is kept only if focus distance changed "
        "by at least this percentage from a nearby mark — or the absolute Δ "
        "threshold is met.\n\n"
        "Higher → fewer marks."
    ),
    "min_abs": (
        "Dynamic mode: minimum absolute focus-distance change (metres) vs a "
        "nearby mark.\n\n"
        "A mark is kept if relative Δ or absolute Δ is satisfied. Higher → fewer marks."
    ),
    "preview_zoom": (
        "Uniform magnification of the true 1:1 strip in the preview.\n\n"
        "Does not change the PDF. Use this to inspect label collisions exactly "
        "as they will print."
    ),
}


class Tooltip:
    """Simple hover tooltip."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 450):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._tip: Optional[tk.Toplevel] = None
        self._after: Optional[str] = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _show(self) -> None:
        self._after = None
        if self._tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tip,
            text=self.text,
            justify="left",
            background="#ffffe0",
            foreground="#222",
            relief="solid",
            borderwidth=1,
            font=("", 10),
            padx=8,
            pady=6,
            wraplength=360,
        )
        label.pack()
        self._tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Helicoid Focus Scale")
        self.minsize(720, 640)

        self._preview_job = None
        self._photo: Optional[ImageTk.PhotoImage] = None

        pad = {"padx": 8, "pady": 3}
        root = ttk.Frame(self, padding=12)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(4, weight=1)

        # --- parameters ---
        frm = ttk.Frame(root)
        frm.grid(row=0, column=0, sticky="ew")
        frm.columnconfigure(1, weight=1)

        ttk.Label(frm, text="Focus scale parameters", font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )

        self.vars: dict[str, tk.StringVar] = {}
        for i, (key, label, unit) in enumerate(FIELDS, start=1):
            self._option_label(frm, label, key).grid(
                row=i, column=0, sticky="w", **pad
            )
            var = tk.StringVar(value=DEFAULTS[key])
            self.vars[key] = var
            ttk.Entry(frm, textvariable=var, width=14).grid(
                row=i, column=1, sticky="w", **pad
            )
            ttk.Label(frm, text=unit).grid(row=i, column=2, sticky="w", **pad)

        opts_row = len(FIELDS) + 1
        self._option_label(frm, "PDF page size", "page_size").grid(
            row=opts_row, column=0, sticky="w", **pad
        )
        self.page_size = tk.StringVar(value=str(DEFAULTS["page_size"]))
        ttk.Combobox(
            frm,
            textvariable=self.page_size,
            values=list(PAGE_SIZES_MM.keys()),
            state="readonly",
            width=12,
        ).grid(row=opts_row, column=1, sticky="w", **pad)

        self._option_label(frm, "Mark mode", "mark_mode").grid(
            row=opts_row + 1, column=0, sticky="w", **pad
        )
        mode_row = ttk.Frame(frm)
        mode_row.grid(row=opts_row + 1, column=1, columnspan=2, sticky="ew", **pad)
        self.mark_mode = tk.StringVar(value=str(DEFAULTS["mark_mode"]))
        ttk.Combobox(
            mode_row,
            textvariable=self.mark_mode,
            values=list(MARK_MODES),
            state="readonly",
            width=12,
        ).pack(side="left")
        reset_btn = ttk.Button(
            mode_row, text="Reset mode defaults", command=self.reset_mode
        )
        reset_btn.pack(side="left", padx=(12, 0))
        self._info_icon(mode_row, "reset_mode").pack(side="left", padx=(4, 0))

        # --- appearance ---
        appearance = ttk.LabelFrame(root, text="Appearance", padding=8)
        appearance.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.text_color = tk.StringVar(value=str(DEFAULTS["text_color"]))
        self.tick_color = tk.StringVar(value=str(DEFAULTS["tick_color"]))
        self.stripe_color = tk.StringVar(value=str(DEFAULTS["stripe_color"]))
        self.color_stripe = tk.BooleanVar(value=bool(DEFAULTS["color_stripe"]))
        self.font_name = tk.StringVar(value=str(DEFAULTS["font_name"]))
        self.font_size = tk.StringVar(value=str(DEFAULTS["font_size"]))
        self.font_bold = tk.BooleanVar(value=bool(DEFAULTS["font_bold"]))

        r0 = ttk.Frame(appearance)
        r0.grid(row=0, column=0, sticky="ew")
        self._option_label(r0, "Text colour", "text_color").pack(side="left")
        ttk.Entry(r0, textvariable=self.text_color, width=10).pack(
            side="left", padx=(8, 4)
        )
        ttk.Button(
            r0, text="Pick…", width=6, command=lambda: self._pick_color(self.text_color)
        ).pack(side="left")
        self._option_label(r0, "Tick colour", "tick_color").pack(side="left", padx=(16, 0))
        ttk.Entry(r0, textvariable=self.tick_color, width=10).pack(
            side="left", padx=(8, 4)
        )
        ttk.Button(
            r0, text="Pick…", width=6, command=lambda: self._pick_color(self.tick_color)
        ).pack(side="left")

        r1 = ttk.Frame(appearance)
        r1.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        stripe_cb = ttk.Checkbutton(
            r1,
            text="Colour glue stripes",
            variable=self.color_stripe,
            command=self._on_stripe_toggle,
        )
        stripe_cb.pack(side="left")
        self._info_icon(r1, "color_stripe").pack(side="left", padx=(4, 0))
        self._option_label(r1, "Stripe colour", "stripe_color").pack(
            side="left", padx=(16, 0)
        )
        self._stripe_entry = ttk.Entry(r1, textvariable=self.stripe_color, width=10)
        self._stripe_entry.pack(side="left", padx=(8, 4))
        self._stripe_pick = ttk.Button(
            r1,
            text="Pick…",
            width=6,
            command=lambda: self._pick_color(self.stripe_color),
        )
        self._stripe_pick.pack(side="left")

        r2 = ttk.Frame(appearance)
        r2.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self._option_label(r2, "Font", "font_name").pack(side="left")
        self._font_families = sorted(get_font_catalog(), key=str.lower)
        default_font = pick_default_font_family()
        if resolve_font_family(self.font_name.get()) is None:
            self.font_name.set(default_font)
        else:
            resolved = resolve_font_family(self.font_name.get())
            if resolved:
                self.font_name.set(resolved)
        self._font_popup: Optional[tk.Toplevel] = None
        self._font_listbox: Optional[tk.Listbox] = None
        self._font_matches: list[str] = list(self._font_families)
        self._font_entry = ttk.Entry(r2, textvariable=self.font_name, width=28)
        self._font_entry.pack(side="left", padx=(8, 0))
        self._font_entry.bind("<KeyRelease>", self._on_font_search)
        self._font_entry.bind("<Down>", self._on_font_list_nav)
        self._font_entry.bind("<Up>", self._on_font_list_nav)
        self._font_entry.bind("<Return>", self._on_font_confirm)
        self._font_entry.bind("<Escape>", self._hide_font_popup)
        self._font_entry.bind("<FocusIn>", self._on_font_focus_in)
        self._font_entry.bind("<FocusOut>", self._on_font_focus_out)
        ttk.Button(r2, text="▾", width=3, command=self._toggle_font_popup).pack(
            side="left", padx=(2, 0)
        )
        self._option_label(r2, "Size (px)", "font_size").pack(side="left", padx=(16, 0))
        ttk.Entry(r2, textvariable=self.font_size, width=6).pack(
            side="left", padx=(8, 0)
        )
        bold_cb = ttk.Checkbutton(r2, text="Bold", variable=self.font_bold)
        bold_cb.pack(side="left", padx=(12, 0))
        self._info_icon(r2, "font_bold").pack(side="left", padx=(4, 0))

        # --- mark mode panels ---
        marks = ttk.Frame(root)
        marks.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        marks.columnconfigure(0, weight=1)

        self._fixed_frame = ttk.LabelFrame(
            marks, text="Fixed distances (metres)", padding=8
        )
        self._fixed_frame.grid(row=0, column=0, sticky="ew")
        self._fixed_frame.columnconfigure(0, weight=1)
        title_fixed = ttk.Frame(self._fixed_frame)
        title_fixed.grid(row=0, column=0, sticky="ew")
        ttk.Label(title_fixed, text="Distance list").pack(side="left")
        self._info_icon(title_fixed, "fixed_distances").pack(side="left", padx=(4, 0))
        self.fixed_distances = tk.StringVar(
            value=format_distance_list(DEFAULT_TARGET_DISTANCES)
        )
        ttk.Entry(self._fixed_frame, textvariable=self.fixed_distances).grid(
            row=1, column=0, sticky="ew", pady=(4, 0)
        )
        ttk.Label(
            self._fixed_frame,
            text="Comma-separated. Spaces ignored. Order/dupes OK.",
            foreground="#666",
        ).grid(row=2, column=0, sticky="w", pady=(4, 0))

        self._dyn_frame = ttk.LabelFrame(marks, text="Dynamic mark tuning", padding=8)
        self._dyn_frame.grid(row=1, column=0, sticky="ew")
        self._dyn_frame.columnconfigure(1, weight=1)

        self.min_gap = tk.DoubleVar(value=float(DEFAULTS["min_gap_mm"]))
        self.min_rel = tk.DoubleVar(value=float(DEFAULTS["min_rel"]) * 100.0)
        self.min_abs = tk.DoubleVar(value=float(DEFAULTS["min_abs_m"]))
        self._gap_label = tk.StringVar()
        self._rel_label = tk.StringVar()
        self._abs_label = tk.StringVar()

        self._option_label(self._dyn_frame, "Min spacing", "min_gap").grid(
            row=0, column=0, sticky="w", **pad
        )
        self._gap_scale = ttk.Scale(
            self._dyn_frame,
            from_=1.0,
            to=12.0,
            variable=self.min_gap,
            command=lambda _v: self._on_slider(),
        )
        self._gap_scale.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Label(self._dyn_frame, textvariable=self._gap_label, width=10).grid(
            row=0, column=2, sticky="e", **pad
        )

        self._option_label(self._dyn_frame, "Min relative Δ", "min_rel").grid(
            row=1, column=0, sticky="w", **pad
        )
        self._rel_scale = ttk.Scale(
            self._dyn_frame,
            from_=0.0,
            to=30.0,
            variable=self.min_rel,
            command=lambda _v: self._on_slider(),
        )
        self._rel_scale.grid(row=1, column=1, sticky="ew", **pad)
        ttk.Label(self._dyn_frame, textvariable=self._rel_label, width=10).grid(
            row=1, column=2, sticky="e", **pad
        )

        self._option_label(self._dyn_frame, "Min absolute Δ", "min_abs").grid(
            row=2, column=0, sticky="w", **pad
        )
        self._abs_scale = ttk.Scale(
            self._dyn_frame,
            from_=0.0,
            to=0.5,
            variable=self.min_abs,
            command=lambda _v: self._on_slider(),
        )
        self._abs_scale.grid(row=2, column=1, sticky="ew", **pad)
        ttk.Label(self._dyn_frame, textvariable=self._abs_label, width=10).grid(
            row=2, column=2, sticky="e", **pad
        )
        ttk.Label(
            self._dyn_frame,
            text="Higher spacing / deltas → fewer marks.",
            foreground="#666",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- status + buttons ---
        bar = ttk.Frame(root)
        bar.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self.status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.status, wraplength=700, foreground="#333").pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(bar, text="Generate…", command=self.save_scale).pack(side="right")

        # --- live preview ---
        prev = ttk.LabelFrame(
            root,
            text="Live preview (exact print proportions — uniform zoom only)",
            padding=8,
        )
        prev.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        prev.columnconfigure(0, weight=1)
        prev.rowconfigure(1, weight=1)

        zoom_row = ttk.Frame(prev)
        zoom_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        zoom_row.columnconfigure(1, weight=1)
        self._option_label(zoom_row, "Zoom", "preview_zoom").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self.preview_zoom = tk.DoubleVar(value=4.0)
        self._zoom_label = tk.StringVar(value="400%")
        ttk.Scale(
            zoom_row,
            from_=1.0,
            to=8.0,
            variable=self.preview_zoom,
            command=lambda _v: self._on_zoom(),
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(zoom_row, textvariable=self._zoom_label, width=6).grid(
            row=0, column=2, sticky="e", padx=(8, 0)
        )

        self.preview_canvas = tk.Canvas(
            prev, height=80, background="#bbb", highlightthickness=0
        )
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self._preview_scroll = ttk.Scrollbar(
            prev, orient="horizontal", command=self.preview_canvas.xview
        )
        self._preview_scroll.grid(row=2, column=0, sticky="ew")
        self.preview_canvas.configure(xscrollcommand=self._preview_scroll.set)

        self._sync_slider_labels()
        self._on_stripe_toggle()
        self._update_mode_panels()
        self._bind_live_updates()
        self.after(50, self.refresh_preview)

    def _info_icon(self, parent: tk.Widget, key: str) -> tk.Label:
        """Small ⓘ with hover tooltip only."""
        icon = tk.Label(
            parent,
            text="ⓘ",
            fg="#5a7a9a",
            font=("", 11),
            padx=2,
            pady=0,
        )
        tip = OPTION_INFO.get(key, "")
        if tip:
            Tooltip(icon, tip)
        return icon

    def _on_font_focus_in(self, _event: Optional[tk.Event] = None) -> None:
        self._refresh_font_popup(force_show=True)

    def _on_font_focus_out(self, _event: Optional[tk.Event] = None) -> None:
        # Delay so a listbox click can take focus / select first
        self.after(120, self._font_focus_out_commit)

    def _font_focus_out_commit(self) -> None:
        if self._font_popup is not None:
            try:
                focus = self.focus_get()
            except KeyError:
                focus = None
            if focus is self._font_listbox or focus is self._font_popup:
                return
            if focus is self._font_entry:
                return
            try:
                x, y = self.winfo_pointerxy()
                widget = self.winfo_containing(x, y)
                if widget is not None and self._font_popup is not None:
                    pop_path = str(self._font_popup)
                    if widget == self._font_listbox or str(widget).startswith(pop_path):
                        return
            except tk.TclError:
                pass
        self._hide_font_popup()
        self._commit_font_choice(allow_fuzzy_best=True)

    def _toggle_font_popup(self) -> None:
        if self._font_popup is not None and self._font_popup.winfo_exists():
            self._hide_font_popup()
        else:
            self._font_entry.focus_set()
            self._refresh_font_popup(force_show=True)

    def _hide_font_popup(self, _event: Optional[tk.Event] = None) -> str:
        if self._font_popup is not None:
            try:
                self._font_popup.destroy()
            except tk.TclError:
                pass
        self._font_popup = None
        self._font_listbox = None
        return "break"

    def _refresh_font_popup(self, *, force_show: bool = False) -> None:
        query = self.font_name.get()
        matches = fuzzy_filter_fonts(query, self._font_families)
        if not matches and query.strip():
            # No fuzzy hits — still show a browseable slice when forced open
            if not force_show:
                self._hide_font_popup()
                return
            matches = list(self._font_families[:60])
        elif not matches:
            matches = list(self._font_families)
        self._font_matches = matches
        self._ensure_font_popup()
        assert self._font_listbox is not None
        self._font_listbox.delete(0, tk.END)
        for name in matches:
            self._font_listbox.insert(tk.END, name)
        if matches:
            self._font_listbox.selection_clear(0, tk.END)
            self._font_listbox.selection_set(0)
            self._font_listbox.activate(0)
            self._font_listbox.see(0)

    def _ensure_font_popup(self) -> None:
        if self._font_popup is not None and self._font_popup.winfo_exists():
            self._position_font_popup()
            return
        pop = tk.Toplevel(self)
        pop.withdraw()
        pop.overrideredirect(True)
        pop.attributes("-topmost", True)
        frame = ttk.Frame(pop, borderwidth=1, relief="solid")
        frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical")
        lb = tk.Listbox(
            frame,
            height=12,
            width=36,
            activestyle="dotbox",
            exportselection=False,
            yscrollcommand=scroll.set,
        )
        scroll.config(command=lb.yview)
        scroll.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        lb.bind("<ButtonRelease-1>", self._on_font_list_click)
        lb.bind("<Double-Button-1>", self._on_font_list_click)
        lb.bind("<Return>", self._on_font_confirm)
        lb.bind("<Escape>", self._hide_font_popup)
        self._font_popup = pop
        self._font_listbox = lb
        self._position_font_popup()
        pop.deiconify()

    def _position_font_popup(self) -> None:
        if self._font_popup is None:
            return
        self.update_idletasks()
        x = self._font_entry.winfo_rootx()
        y = self._font_entry.winfo_rooty() + self._font_entry.winfo_height()
        w = max(self._font_entry.winfo_width(), 280)
        self._font_popup.geometry(f"{w}x220+{x}+{y}")

    def _on_font_search(self, event: Optional[tk.Event] = None) -> None:
        if event is not None and event.keysym in (
            "Up",
            "Down",
            "Return",
            "Escape",
            "Tab",
        ):
            return
        self._refresh_font_popup(force_show=True)

    def _on_font_list_nav(self, event: tk.Event) -> str:
        self._refresh_font_popup(force_show=True)
        if self._font_listbox is None:
            return "break"
        size = self._font_listbox.size()
        if size <= 0:
            return "break"
        cur = self._font_listbox.curselection()
        idx = int(cur[0]) if cur else 0
        if event.keysym == "Down":
            idx = min(size - 1, idx + 1)
        else:
            idx = max(0, idx - 1)
        self._font_listbox.selection_clear(0, tk.END)
        self._font_listbox.selection_set(idx)
        self._font_listbox.activate(idx)
        self._font_listbox.see(idx)
        return "break"

    def _on_font_list_click(self, _event: Optional[tk.Event] = None) -> None:
        # Defer so Listbox updates selection before we read it
        self.after_idle(self._on_font_confirm)

    def _on_font_confirm(self, _event: Optional[tk.Event] = None) -> str:
        chosen: Optional[str] = None
        if self._font_listbox is not None:
            sel = self._font_listbox.curselection()
            if sel:
                chosen = self._font_listbox.get(sel[0])
            else:
                try:
                    idx = self._font_listbox.index(tk.ACTIVE)
                    if 0 <= idx < self._font_listbox.size():
                        chosen = self._font_listbox.get(idx)
                except tk.TclError:
                    pass
        if chosen is None and self._font_matches:
            chosen = self._font_matches[0]
        if chosen is not None:
            self.font_name.set(chosen)
        self._hide_font_popup()
        self._commit_font_choice(allow_fuzzy_best=False)
        self._font_entry.focus_set()
        return "break"

    def _commit_font_choice(self, *, allow_fuzzy_best: bool) -> None:
        """Snap entry text to an installed family name."""
        typed = self.font_name.get().strip()
        resolved = resolve_font_family(typed) if typed else None
        if resolved is None and typed and allow_fuzzy_best:
            matches = fuzzy_filter_fonts(typed, self._font_families, limit=1)
            resolved = matches[0] if matches else None
        if resolved is None:
            resolved = pick_default_font_family()
        if self.font_name.get() != resolved:
            self.font_name.set(resolved)
        self.schedule_preview()

    def _option_label(self, parent: tk.Widget, text: str, key: str) -> ttk.Frame:
        row = ttk.Frame(parent)
        ttk.Label(row, text=text).pack(side="left")
        if key in OPTION_INFO:
            self._info_icon(row, key).pack(side="left", padx=(3, 0))
        return row

    def _pick_color(self, var: tk.StringVar) -> None:
        _rgb, hex_color = colorchooser.askcolor(
            color=var.get(), title="Choose colour", parent=self
        )
        if hex_color:
            var.set(hex_color)
            self.schedule_preview()

    def _on_stripe_toggle(self) -> None:
        state = "normal" if self.color_stripe.get() else "disabled"
        self._stripe_entry.configure(state=state)
        self._stripe_pick.configure(state=state)
        self.schedule_preview()

    def _sync_slider_labels(self) -> None:
        self._gap_label.set(f"{self.min_gap.get():.1f} mm")
        self._rel_label.set(f"{self.min_rel.get():.0f} %")
        self._abs_label.set(f"{self.min_abs.get():.2f} m")

    def _on_slider(self) -> None:
        self._sync_slider_labels()
        self.schedule_preview()

    def _on_zoom(self) -> None:
        self._zoom_label.set(f"{self.preview_zoom.get() * 100:.0f}%")
        self.schedule_preview()

    def _update_mode_panels(self) -> None:
        if self.mark_mode.get() == "dynamic":
            self._fixed_frame.grid_remove()
            self._dyn_frame.grid()
        else:
            self._dyn_frame.grid_remove()
            self._fixed_frame.grid()

    def _bind_live_updates(self) -> None:
        for var in self.vars.values():
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.page_size.trace_add("write", lambda *_: self.schedule_preview())
        self.mark_mode.trace_add("write", lambda *_: self._on_mark_mode())
        self.fixed_distances.trace_add("write", lambda *_: self.schedule_preview())
        for var in (
            self.text_color,
            self.tick_color,
            self.stripe_color,
            self.font_name,
            self.font_size,
        ):
            var.trace_add("write", lambda *_: self.schedule_preview())
        self.font_bold.trace_add("write", lambda *_: self.schedule_preview())
        self.color_stripe.trace_add("write", lambda *_: self._on_stripe_toggle())

    def _on_mark_mode(self) -> None:
        self._update_mode_panels()
        self.schedule_preview()

    def reset_mode(self) -> None:
        if self.mark_mode.get() == "dynamic":
            self.min_gap.set(float(DEFAULTS["min_gap_mm"]))
            self.min_rel.set(float(DEFAULTS["min_rel"]) * 100.0)
            self.min_abs.set(float(DEFAULTS["min_abs_m"]))
            self._sync_slider_labels()
        else:
            self.fixed_distances.set(format_distance_list(DEFAULT_TARGET_DISTANCES))
        self.schedule_preview()

    def schedule_preview(self, *_args) -> None:
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(150, self.refresh_preview)

    def _generator(self) -> FocusingScaleGenerator:
        def num(key: str) -> float:
            return float(self.vars[key].get().strip())

        if self.mark_mode.get() == "fixed":
            distances = parse_distance_list(self.fixed_distances.get())
        else:
            distances = list(DEFAULT_TARGET_DISTANCES)

        try:
            font_size = int(float(self.font_size.get().strip()))
        except ValueError as e:
            raise ValueError("Font size must be a number") from e
        if font_size < 1:
            raise ValueError("Font size must be ≥ 1")

        return FocusingScaleGenerator(
            focal_length=num("focal"),
            diameter=num("diameter"),
            max_extension=num("extension"),
            throw_deg=num("throw"),
            error=num("error"),
            ffd=num("ffd"),
            height=num("scale_height"),
            page_size=self.page_size.get(),
            mark_mode=self.mark_mode.get(),
            min_gap_mm=float(self.min_gap.get()),
            min_rel=float(self.min_rel.get()) / 100.0,
            min_abs_m=float(self.min_abs.get()),
            dpi=300,
            tick_length=0.5,
            padding=0.3,
            vertical_offset=0.5,
            target_distances=distances,
            text_color=self.text_color.get().strip() or DEFAULT_TEXT_COLOR,
            tick_color=self.tick_color.get().strip() or DEFAULT_TICK_COLOR,
            color_stripe=self.color_stripe.get(),
            stripe_color=self.stripe_color.get().strip() or DEFAULT_STRIPE_COLOR,
            font_name=self.font_name.get(),
            font_size=font_size,
            font_bold=self.font_bold.get(),
            wrap_buffer_mm=num("wrap_buffer"),
        )

    def refresh_preview(self) -> None:
        self._preview_job = None
        try:
            gen = self._generator()
            strip = gen.create_scale()
        except Exception as e:
            self.status.set(f"Preview: {e}")
            self.preview_canvas.delete("all")
            return

        zoom = max(1.0, float(self.preview_zoom.get()))
        disp_w = max(1, int(round(strip.width * zoom)))
        disp_h = max(1, int(round(strip.height * zoom)))
        preview = (
            strip
            if zoom == 1.0
            else strip.resize((disp_w, disp_h), Image.Resampling.NEAREST)
        )

        self._photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        self.preview_canvas.configure(
            scrollregion=(0, 0, disp_w, disp_h + 8),
            height=min(max(disp_h + 12, 40), 220),
        )
        self.preview_canvas.create_image(0, 4, anchor="nw", image=self._photo)

        n_marks = len(gen._calculate_scale_positions()[0])
        near = gen.object_distance_from_extension(gen.max_extension)
        near_s = "∞" if near == float("inf") else f"{near:.2f} m"
        wraps = max(0, gen.last_wrap_count - 1)
        wrap_bit = f" · {wraps} wrap{'s' if wraps != 1 else ''}" if wraps else ""
        pre_bit = (
            f" · pre-buffer {gen.pre_buffer_arc:.1f} mm"
            if gen.pre_buffer_arc > 0.05
            else ""
        )
        self.status.set(
            f"{gen.scale_length:.1f} mm × {gen.height:g} mm @ 300 DPI · "
            f"{n_marks} marks · mode={gen.mark_mode} · near={near_s}"
            f"{pre_bit}{wrap_bit} · zoom {zoom * 100:.0f}% (uniform)"
        )

    def save_scale(self) -> None:
        try:
            gen = self._generator()
        except Exception as e:
            messagebox.showerror("Invalid input", str(e))
            return

        path = filedialog.asksaveasfilename(
            title="Save focus scale",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("PNG", "*.png")],
            initialfile=gen.suggested_filename(".pdf"),
        )
        if not path:
            return

        try:
            img = gen.save(path)
        except Exception as e:
            messagebox.showerror("Save error", str(e))
            return

        self.status.set(
            f"Saved {img.size[0]}×{img.size[1]}px @ {gen.dpi} DPI → {path}\n"
            + gen.preview_summary()
        )
        messagebox.showinfo("Done", f"Saved:\n{path}")
        self.schedule_preview()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
