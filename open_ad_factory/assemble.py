"""Frame and audio helpers for building the final ad: vertical canvases, captions, end card, concatenation.

Images follow the ComfyUI layout [frames, height, width, 3] float in 0..1.
Audio follows the ComfyUI AUDIO dict: {"waveform": [batch, channels, samples], "sample_rate": int}.
"""
import os

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw, ImageFont


def _resize(img, width, height):
    # img: [N, H, W, C] -> [N, height, width, C]
    return F.interpolate(img.movedim(-1, 1), size=(height, width), mode="bilinear", align_corners=False, antialias=True).movedim(1, -1)


def cover(img, width, height):
    """Scale to fill width x height and center crop."""
    h, w = img.shape[1:3]
    scale = max(width / w, height / h)
    nw, nh = max(width, round(w * scale)), max(height, round(h * scale))
    img = _resize(img, nw, nh)
    x, y = (nw - width) // 2, (nh - height) // 2
    return img[:, y:y + height, x:x + width]


def contain(img, width, height):
    h, w = img.shape[1:3]
    scale = min(width / w, height / h)
    return _resize(img, max(1, round(w * scale)), max(1, round(h * scale)))


def product_canvas(img, width, height, fill=0.82, background="blur"):
    """Place a product photo centered on a vertical canvas with a soft blurred backdrop or a flat color."""
    img = img[:1, ..., :3]
    if background == "auto":
        # Studio packshots sit on white; extend that white instead of blurring it gray
        border = torch.cat([img[:, :4].flatten(1, 2), img[:, -4:].flatten(1, 2), img[:, :, :4].flatten(1, 2), img[:, :, -4:].flatten(1, 2)], dim=1)
        background = "white" if border.mean() > 0.93 and border.std() < 0.05 else "blur"
    if background == "blur":
        bg = cover(img, width // 8, height // 8)
        bg = F.avg_pool2d(bg.movedim(-1, 1), 5, stride=1, padding=2, count_include_pad=False).movedim(1, -1)
        bg = _resize(bg, width, height) * 0.55 + 0.2
    elif background == "dark":
        # Vertical gradient from near black to deep violet
        t = torch.linspace(0, 1, height, dtype=img.dtype).view(1, height, 1, 1)
        bg = (torch.tensor([0.04, 0.04, 0.06], dtype=img.dtype) * (1 - t) + torch.tensor([0.16, 0.10, 0.30], dtype=img.dtype) * t).expand(1, height, width, 3).clone()
    else:
        value = 1.0 if background == "white" else 0.0
        bg = torch.full((1, height, width, 3), value, dtype=img.dtype)
    fg = contain(img, round(width * fill), round(height * fill))
    fh, fw = fg.shape[1:3]
    y, x = (height - fh) // 2, (width - fw) // 2
    bg[:, y:y + fh, x:x + fw] = fg
    return bg.clamp(0, 1)


DEFAULT_FONT = os.path.join(os.path.dirname(__file__), "fonts", "Anton-Regular.ttf")


def _font(size, font_path=""):
    return ImageFont.truetype(font_path or DEFAULT_FONT, size)


def _wrap(draw, text, font, max_width):
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def text_layer(width, height, text, center_y, size_ratio=0.055, font_path="", fill=(255, 255, 255, 255), pill=None):
    """Render centered, wrapped, outlined text onto a transparent RGBA layer. Returns (rgb, alpha) tensors."""
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    size = max(12, round(height * size_ratio))
    font = _font(size, font_path)
    lines = _wrap(draw, text, font, width * 0.86)
    spacing = round(size * 0.25)
    block = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=spacing, align="center")
    bw, bh = block[2] - block[0], block[3] - block[1]
    x, y = (width - bw) / 2 - block[0], center_y * height - bh / 2 - block[1]
    if pill:
        pad = size * 0.6
        draw.rounded_rectangle((x + block[0] - pad, y + block[1] - pad * 0.6, x + block[2] + pad, y + block[3] + pad * 0.6), radius=size, fill=pill)
        stroke = 0
    else:
        stroke = max(2, size // 12)
    draw.multiline_text((x, y), "\n".join(lines), font=font, fill=fill, spacing=spacing, align="center", stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    arr = np.asarray(layer, dtype=np.float32) / 255.0
    return torch.from_numpy(arr[..., :3]), torch.from_numpy(arr[..., 3:4])


def composite(frames, layer):
    rgb, alpha = layer
    rgb, alpha = rgb.to(frames), alpha.to(frames)
    return frames * (1 - alpha) + rgb * alpha


def end_card(product, width, height, frames, headline, cta, font_path=""):
    canvas = product_canvas(product, width, height, fill=0.66, background="dark")
    canvas = composite(canvas, text_layer(width, height, headline.upper(), 0.14, 0.07, font_path))
    canvas = composite(canvas, text_layer(width, height, cta.upper(), 0.86, 0.045, font_path, fill=(20, 20, 20, 255), pill=(240, 255, 79, 255)))
    return canvas.expand(frames, -1, -1, -1).clone()


def fit_audio(audio, sample_rate, channels, seconds):
    """Return a [channels, samples] waveform of exactly `seconds`, resampled, padded or trimmed."""
    samples = round(seconds * sample_rate)
    if audio is None:
        return torch.zeros(channels, samples)
    wave = audio["waveform"][0].float()
    if audio["sample_rate"] != sample_rate:
        new_len = round(wave.shape[-1] * sample_rate / audio["sample_rate"])
        wave = F.interpolate(wave.unsqueeze(0), size=new_len, mode="linear", align_corners=False).squeeze(0)
    if wave.shape[0] != channels:
        wave = wave.mean(0, keepdim=True).expand(channels, -1)
    if wave.shape[-1] < samples:
        wave = F.pad(wave, (0, samples - wave.shape[-1]))
    return wave[:, :samples]


def concat(segments, fps, sample_rate=None, channels=None):
    """segments: list of (images, audio_or_None). All images are resized to the first segment's size.
    Audio of each segment is fitted to that segment's frame duration so picture and sound never drift."""
    height, width = segments[0][0].shape[1:3]
    audios = [a for _, a in segments if a is not None]
    sample_rate = sample_rate or (audios[0]["sample_rate"] if audios else 48000)
    channels = channels or (audios[0]["waveform"].shape[1] if audios else 2)
    frames, waves = [], []
    for images, audio in segments:
        if images.shape[1:3] != (height, width):
            images = cover(images, width, height)
        frames.append(images[..., :3])
        waves.append(fit_audio(audio, sample_rate, channels, images.shape[0] / fps))
    return torch.cat(frames), {"waveform": torch.cat(waves, dim=-1).unsqueeze(0), "sample_rate": sample_rate}
