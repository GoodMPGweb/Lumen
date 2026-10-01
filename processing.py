"""Image processing for Lumen. All geometry is stored in original-image pixels."""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageOps


@dataclass(frozen=True)
class CubeLUT:
    size: int
    table: np.ndarray  # .cube order: blue, green, red, output RGB
    domain_min: np.ndarray
    domain_max: np.ndarray
    pillow_filter: object | None = None


def load_photo(path: str) -> Image.Image:
    with Image.open(path) as source:
        if source.format not in ("JPEG", "PNG"):
            raise ValueError("Please choose a JPG or PNG image.")
        image = ImageOps.exif_transpose(source)
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        profile = image.info.get("icc_profile")
        if profile:
            try:
                alpha = image.convert("RGBA").getchannel("A") if has_alpha else None
                image = ImageCms.profileToProfile(
                    image.convert("RGB"), io.BytesIO(profile), ImageCms.createProfile("sRGB"),
                    outputMode="RGB",
                )
                if alpha is not None:
                    image.putalpha(alpha)
            except (ImageCms.PyCMSError, OSError, ValueError):
                image = image.convert("RGBA" if has_alpha else "RGB")
        else:
            image = image.convert("RGBA" if has_alpha else "RGB")
        image.load()
        return image.copy()


def load_cube(path: str) -> CubeLUT:
    size = None
    domain_min = np.zeros(3, dtype=np.float32)
    domain_max = np.ones(3, dtype=np.float32)
    entries = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0].upper()
        try:
            if key == "TITLE":
                continue
            if key == "LUT_3D_SIZE":
                size = int(parts[1])
                if not 2 <= size <= 65:
                    raise ValueError("Supported .cube sizes are 2 through 65.")
            elif key == "LUT_1D_SIZE":
                raise ValueError("This version supports 3D .cube LUTs, not 1D LUTs.")
            elif key == "DOMAIN_MIN":
                domain_min = np.array([float(v) for v in parts[1:4]], dtype=np.float32)
            elif key == "DOMAIN_MAX":
                domain_max = np.array([float(v) for v in parts[1:4]], dtype=np.float32)
            elif len(parts) == 3:
                entries.append([float(v) for v in parts])
            else:
                raise ValueError(f"Unrecognized .cube line {number}: {line[:60]}")
        except (IndexError, TypeError) as exc:
            raise ValueError(f"Invalid .cube line {number}.") from exc
    if size is None or len(entries) != size ** 3 or np.any(domain_max <= domain_min):
        raise ValueError("Incomplete or invalid 3D .cube file.")
    table = np.asarray(entries, dtype=np.float32).reshape(size, size, size, 3)
    if not np.isfinite(table).all():
        raise ValueError("The .cube file contains invalid numbers.")
    fast_filter = None
    if np.array_equal(domain_min, np.zeros(3)) and np.array_equal(domain_max, np.ones(3)):
        fast_filter = ImageFilter.Color3DLUT(size, table.reshape(-1, 3).tolist())
    return CubeLUT(size, table, domain_min, domain_max, fast_filter)


def _apply_lut(pixels: np.ndarray, lut: CubeLUT) -> np.ndarray:
    # Break the interpolation into pieces so a full-resolution export has bounded memory.
    flat = pixels.reshape(-1, 3)
    result = np.empty_like(flat)
    for start in range(0, flat.shape[0], 120_000):
        end = min(start + 120_000, flat.shape[0])
        coords = np.clip(
            (flat[start:end] - lut.domain_min) / (lut.domain_max - lut.domain_min), 0, 1
        ) * (lut.size - 1)
        lo = np.floor(coords).astype(np.int32)
        hi = np.minimum(lo + 1, lut.size - 1)
        weight = coords - lo
        r0, g0, b0 = lo.T
        r1, g1, b1 = hi.T
        wr, wg, wb = weight.T
        table = lut.table
        lower = (table[b0, g0, r0] * (1-wr)[:, None] * (1-wg)[:, None] +
                 table[b0, g0, r1] * wr[:, None] * (1-wg)[:, None] +
                 table[b0, g1, r0] * (1-wr)[:, None] * wg[:, None] +
                 table[b0, g1, r1] * wr[:, None] * wg[:, None])
        upper = (table[b1, g0, r0] * (1-wr)[:, None] * (1-wg)[:, None] +
                 table[b1, g0, r1] * wr[:, None] * (1-wg)[:, None] +
                 table[b1, g1, r0] * (1-wr)[:, None] * wg[:, None] +
                 table[b1, g1, r1] * wr[:, None] * wg[:, None])
        result[start:end] = lower * (1-wb)[:, None] + upper * wb[:, None]
    return result.reshape(pixels.shape)


def crop_bounds(image: Image.Image, crop) -> tuple[int, int, int, int]:
    if crop is None:
        return (0, 0, image.width, image.height)
    x0, y0, x1, y1 = (int(round(v)) for v in crop)
    x0, x1 = sorted((max(0, min(image.width, x0)), max(0, min(image.width, x1))))
    y0, y1 = sorted((max(0, min(image.height, y0)), max(0, min(image.height, y1))))
    if x1 <= x0 or y1 <= y0:
        raise ValueError("The crop has no area.")
    return x0, y0, x1, y1


def render(image: Image.Image, state: dict, lut: CubeLUT | None, max_side: int | None = None) -> Image.Image:
    bounds = crop_bounds(image, state.get("crop"))
    result = image.crop(bounds)
    if max_side and max(result.size) > max_side:
        result.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    rgba = result.mode == "RGBA"
    array = np.asarray(result, dtype=np.uint8)
    rgb = array[..., :3].astype(np.float32) / 255.0
    exposure = state.get("exposure", 0)
    if exposure:
        # Exposure is measured in stops and therefore acts on linear light.
        linear = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
        linear = np.clip(linear * (2.0 ** (exposure / 100)), 0, 1)
        rgb = np.where(linear <= .0031308, linear * 12.92,
                       1.055 * np.power(linear, 1 / 2.4) - .055)
    brightness = state.get("brightness", 0)
    if brightness:
        rgb = np.clip(rgb + brightness / 100 * .3, 0, 1)
    contrast = state.get("contrast", 0)
    if contrast:
        rgb = np.clip(.5 + (rgb - .5) * (1 + contrast / 100), 0, 1)
    highlights, shadows = state.get("highlights", 0), state.get("shadows", 0)
    if highlights or shadows:
        luma = np.sum(rgb * np.array([.2126, .7152, .0722], dtype=np.float32), axis=2, keepdims=True)
        if highlights:
            t = np.clip((luma - .35) / .65, 0, 1)
            mask = t * t * (3 - 2 * t)
            rgb = np.clip(rgb + highlights / 100 * .35 * mask, 0, 1)
        if shadows:
            t = np.clip((.65 - luma) / .65, 0, 1)
            mask = t * t * (3 - 2 * t)
            rgb = np.clip(rgb + shadows / 100 * .3 * mask, 0, 1)
    manual = np.array([1 + state.get(k, 0) / 100 for k in ("red", "green", "blue")], dtype=np.float32)
    neutral = np.array(state.get("neutral_gains", [1, 1, 1]), dtype=np.float32)
    rgb = np.clip(rgb * manual * neutral, 0, 1)
    saturation = max(0, 1 + state.get("saturation", 0) / 100)
    luma = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2, keepdims=True)
    rgb = np.clip(luma + (rgb - luma) * saturation, 0, 1)
    if lut is not None and state.get("lut_intensity", 100) > 0:
        amount = np.clip(state["lut_intensity"] / 100.0, 0, 1)
        if lut.pillow_filter is not None:
            lut_image = Image.fromarray(np.uint8(np.rint(rgb * 255)), "RGB").filter(lut.pillow_filter)
            post_lut = np.asarray(lut_image, dtype=np.float32) / 255.0
        else:
            post_lut = _apply_lut(rgb, lut)
        rgb = np.clip(rgb * (1 - amount) + post_lut * amount, 0, 1)
    out = np.uint8(np.rint(rgb * 255))
    if rgba:
        out = np.dstack((out, array[..., 3]))
    finished = Image.fromarray(out, "RGBA" if rgba else "RGB")
    strokes = state.get("strokes", [])
    if strokes:
        draw = ImageDraw.Draw(finished)
        scale = finished.width / (bounds[2] - bounds[0])
        for stroke in strokes:
            points = [(round((x - bounds[0]) * scale), round((y - bounds[1]) * scale))
                      for x, y in stroke["points"]]
            width = max(1, round(stroke["width"] * scale))
            if len(points) == 1:
                x, y = points[0]
                draw.ellipse((x-width//2, y-width//2, x+width//2, y+width//2), fill=stroke["color"])
            elif len(points) > 1:
                draw.line(points, fill=stroke["color"], width=width, joint="curve")
    return finished


def neutral_gains(image: Image.Image, x: float, y: float) -> list[float]:
    radius = max(3, round(min(image.size) * .003))
    box = (max(0, int(x)-radius), max(0, int(y)-radius),
           min(image.width, int(x)+radius+1), min(image.height, int(y)+radius+1))
    pixels = np.asarray(image.crop(box).convert("RGB"), dtype=np.float32).reshape(-1, 3)
    mean = np.mean(pixels, axis=0)
    if min(mean) < 5 or max(mean) > 250:
        raise ValueError("Choose a neutral area with visible detail, away from pure black or clipped white.")
    target = float(np.mean(mean))
    return np.clip(target / mean, .5, 2).tolist()


def parade(image: Image.Image, width: int = 256) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sample = image.convert("RGB")
    sample.thumbnail((width, 512), Image.Resampling.BILINEAR)
    data = np.asarray(sample)
    height, cols, _ = data.shape
    output = []
    for channel in range(3):
        density = np.zeros((256, cols), dtype=np.float32)
        xs = np.broadcast_to(np.arange(cols), (height, cols))
        np.add.at(density, (255 - data[..., channel], xs), 1)
        density = np.log1p(density)
        peak = density.max()
        if peak:
            density /= peak
        output.append(density)
    return tuple(output)
