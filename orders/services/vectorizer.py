import base64
import io
import uuid
from pathlib import Path
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape

import cv2
import numpy as np
from django.conf import settings
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    from rembg import new_session, remove as rembg_remove
    _REMBG_SESSION = new_session('u2netp')
    HAS_REMBG = True
except Exception:
    _REMBG_SESSION = None
    rembg_remove = None
    HAS_REMBG = False


WORK_SIZE = 720  # High resolution for smooth curves & fine facial/badge detail


def remove_background(pil_image: Image.Image) -> Tuple[np.ndarray, np.ndarray]:
    """
    Removes background from an uploaded PIL image using the cached `rembg` (`u2netp`)
    AI segmentation session, with an OpenCV fallback if `rembg` is unavailable.
    Returns (rgb_uint8_array, alpha_mask_uint8_array).
    """
    pil_image = ImageOps.exif_transpose(pil_image)

    pil_rgba = pil_image.convert('RGBA')
    target_max_dim = WORK_SIZE - 96
    scale = target_max_dim / float(max(pil_rgba.width, pil_rgba.height, 1))
    new_w = max(1, int(round(pil_rgba.width * scale)))
    new_h = max(1, int(round(pil_rgba.height * scale)))
    pil_rgba = pil_rgba.resize((new_w, new_h), Image.Resampling.LANCZOS)

    canvas = Image.new('RGBA', (WORK_SIZE, WORK_SIZE), (255, 255, 255, 0))
    offset_x = (WORK_SIZE - pil_rgba.width) // 2
    offset_y = (WORK_SIZE - pil_rgba.height) // 2

    # If the uploaded image already has transparency, respect it
    raw_alpha = np.array(pil_rgba)[:, :, 3]
    if np.mean(raw_alpha < 128) > 0.08:
        canvas.paste(pil_rgba, (offset_x, offset_y), pil_rgba)
        arr = np.array(canvas)
        return arr[:, :, :3], arr[:, :, 3]

    # Run rembg AI subject segmentation on the resized image before pasting
    if HAS_REMBG and rembg_remove is not None:
        try:
            cutout_sub = rembg_remove(pil_rgba, session=_REMBG_SESSION)
            canvas.paste(cutout_sub, (offset_x, offset_y), cutout_sub)
            arr = np.array(canvas)
            alpha = arr[:, :, 3]
            # Clean and smooth the AI alpha mask
            alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
            _, alpha = cv2.threshold(alpha, 110, 255, cv2.THRESH_BINARY)
            if np.mean(alpha > 0) > 0.03:
                # Composite RGB over white outside alpha so background color never bleeds into hair edges
                rgb_clean = arr[:, :, :3].copy()
                fg = alpha > 127
                for c in range(3):
                    rgb_clean[:, :, c] = np.where(fg, rgb_clean[:, :, c], 255)
                return rgb_clean, alpha
        except Exception:
            pass

    # Fallback if rembg fails
    canvas.paste(pil_rgba, (offset_x, offset_y), pil_rgba)
    arr_rgba = np.array(canvas)
    rgb = arr_rgba[:, :, :3]
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    mask[offset_y : offset_y + new_h, offset_x : offset_x + new_w] = 255
    return rgb, mask


def _remove_speckles(binary_mask: np.ndarray, min_pixels: int = 16) -> np.ndarray:
    """Removes isolated dust/speckle components smaller than `min_pixels`."""
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary_mask, connectivity=8
    )
    if num_labels <= 1:
        return binary_mask
    sizes = stats[:, cv2.CC_STAT_AREA]
    keep = sizes >= min_pixels
    keep[0] = False
    return np.where(keep[labels], 255, 0).astype(np.uint8)


def _chaikin_smooth_points(pts: np.ndarray, iterations: int = 2) -> np.ndarray:
    """
    Applies Chaikin's corner-cutting subdivision algorithm to a polyline so
    vector contours look like smooth hand-drawn ink curves instead of jagged polygons.
    """
    if len(pts) < 3:
        return pts
    curr = pts.astype(np.float32)
    for _ in range(iterations):
        new_pts = [curr[0]]
        for i in range(len(curr) - 1):
            p0, p1 = curr[i], curr[i + 1]
            new_pts.append(0.75 * p0 + 0.25 * p1)
            new_pts.append(0.25 * p0 + 0.75 * p1)
        new_pts.append(curr[-1])
        curr = np.array(new_pts, dtype=np.float32)
    return curr


def extract_laser_masks(
    rgb: np.ndarray, alpha_mask: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Fine-Line Portrait & Illustration Vectorizer:
    Combines `rembg` AI subject isolation with:
      1. Smooth outer cut silhouette (Layer 00 - #000000 0.1mm)
      2. Continuous, anti-aliased XDoG + Canny fine contour lines (Layer 01 - #0000FF 0.1mm)
      3. Local adaptive dark feature detection for hair, eyebrows, eyes/pupils, smile,
         and crests/badges without blotching flat skin (Layer 02 - #FF0000 Fill)
      4. Soft XDoG tonal sketch map for realistic material preview rendering.
    """
    fg_bool = alpha_mask > 127

    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    gray_clean = np.where(fg_bool, gray, 255).astype(np.uint8)

    # Edge-preserving bilateral filter keeps hair, eyes, and badges sharp while smoothing skin noise
    smooth = cv2.bilateralFilter(gray_clean, d=7, sigmaColor=28, sigmaSpace=28)
    smooth = cv2.bilateralFilter(smooth, d=7, sigmaColor=28, sigmaSpace=28)

    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    enhanced = np.where(fg_bool, clahe.apply(smooth), 255).astype(np.uint8)

    # -------------------------------------------------------------------------
    # Layer 00: Smooth Cut Profile around the AI-segmented subject silhouette
    # -------------------------------------------------------------------------
    cut_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    cut_mask = cv2.dilate(alpha_mask, cut_kernel, iterations=1)
    cut_mask = cv2.GaussianBlur(cut_mask, (11, 11), 0)
    _, cut_mask = cv2.threshold(cut_mask, 127, 255, cv2.THRESH_BINARY)

    # -------------------------------------------------------------------------
    # Layer 02: Crisp Fine-Line Feature Contours (Eyes, Eyebrows, Smile, Crest)
    # -------------------------------------------------------------------------
    # Narrow local adaptive threshold (`blockSize=13, C=9`) traces ONLY sharp local
    # dark lines (eyelashes, iris rings, eyebrows, lip line, hair waves, shirt badge)
    # as crisp fine lines — never filling large shadow areas or inverting faces on Slate!
    inner_fg = cv2.erode(alpha_mask, np.ones((5, 5), np.uint8), iterations=1) > 127
    local_fine_features = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        13,
        9,
    )
    fill_mask = np.where(inner_fg & (local_fine_features > 0), 255, 0).astype(np.uint8)
    fill_mask = _remove_speckles(fill_mask, min_pixels=18)

    # -------------------------------------------------------------------------
    # Layer 01: Continuous Structural Fine-Line Score Contours
    # -------------------------------------------------------------------------
    fg_pixels = enhanced[fg_bool]
    med = float(np.median(fg_pixels)) if fg_pixels.size > 0 else 135.0
    low_c = int(max(40, 0.55 * med))
    high_c = int(min(190, 1.20 * med))
    canny_edges = cv2.Canny(smooth, low_c, high_c)

    # Subject outer silhouette contour (crisp continuous fine line around hair, ears & shoulders)
    subject_outline = cv2.dilate(
        cv2.Canny(alpha_mask, 80, 160), np.ones((2, 2), np.uint8), iterations=1
    )

    score_combined = cv2.bitwise_or(canny_edges, subject_outline)
    score_mask = np.where(
        (alpha_mask > 0) | (subject_outline > 0), score_combined, 0
    ).astype(np.uint8)
    score_mask = _remove_speckles(score_mask, min_pixels=14)

    # -------------------------------------------------------------------------
    # Continuous-Tone Fine-Line Sketch Map (narrow DoG for crisp fine-line proofs)
    # -------------------------------------------------------------------------
    g_small = cv2.GaussianBlur(enhanced.astype(np.float32), (3, 3), 0.65)
    g_large = cv2.GaussianBlur(enhanced.astype(np.float32), (7, 7), 1.65)
    dog_diff = g_large - g_small
    sketch_intensity = np.clip((dog_diff - 2.8) / 7.5, 0.0, 1.0)
    sketch_intensity = np.where(inner_fg, sketch_intensity, 0.0).astype(np.float32)

    return cut_mask, score_mask, fill_mask, sketch_intensity


def _contours_to_smooth_svg_d(
    contours,
    epsilon_factor: float = 0.0012,
    min_arc: float = 12.0,
    close_paths: bool = False,
    smooth_passes: int = 1,
) -> str:
    """
    Converts OpenCV contours into Chaikin-smoothed SVG path `d` strings
    so LightBurn receives smooth, flowing curves instead of jagged stair-steps.
    """
    segments = []
    for cnt in contours:
        arc = cv2.arcLength(cnt, close_paths)
        if arc < min_arc:
            continue
        approx = cv2.approxPolyDP(cnt, epsilon_factor * arc, close_paths)
        pts = approx.reshape(-1, 2)
        if len(pts) < 2:
            continue
        if smooth_passes > 0 and len(pts) >= 3:
            pts = _chaikin_smooth_points(pts, iterations=smooth_passes)
        cmds = [f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"]
        for x, y in pts[1:]:
            cmds.append(f"L {x:.1f} {y:.1f}")
        if close_paths:
            cmds.append("Z")
        segments.append(" ".join(cmds))
    return " ".join(segments)


def build_lightburn_svg(
    cut_mask: np.ndarray,
    score_mask: np.ndarray,
    fill_mask: np.ndarray,
    custom_text: str = "",
) -> str:
    """
    Generates a production-ready LightBurn SVG strictly following Pauly Bruv Engraving's
    3-layer color & stroke specification:
      - Layer 00 (Cut Profile): Stroke #000000 (0.1mm), fill="none"
      - Layer 01 (Line / Score Accent): Stroke #0000FF (0.1mm), fill="none"
      - Layer 02 (Solid Fills): Fill #FF0000, stroke="none"
    """
    h, w = cut_mask.shape[:2]

    # 1. Layer 00: Smooth Cut Profile around the subject silhouette
    cut_contours, _ = cv2.findContours(
        cut_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    cut_path_d = _contours_to_smooth_svg_d(
        cut_contours,
        epsilon_factor=0.0018,
        min_arc=40.0,
        close_paths=True,
        smooth_passes=2,
    )

    # 2. Layer 01: Smooth Fine-Line Score Contours
    score_contours, _ = cv2.findContours(
        score_mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE
    )
    score_path_d = _contours_to_smooth_svg_d(
        score_contours,
        epsilon_factor=0.0015,
        min_arc=10.0,
        close_paths=False,
        smooth_passes=1,
    )

    # 3. Layer 02: Smooth Adaptive Feature Fills (hair, eyes, eyebrows, smile, crest)
    fill_contours, _ = cv2.findContours(
        fill_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
    )
    fill_path_d = _contours_to_smooth_svg_d(
        fill_contours,
        epsilon_factor=0.0014,
        min_arc=10.0,
        close_paths=True,
        smooth_passes=1,
    )

    escaped_text = escape(custom_text.strip().upper()) if custom_text else ""
    text_svg_block = ""
    if escaped_text:
        text_svg_block = (
            f'    <text x="{w // 2}" y="{h - 42}" text-anchor="middle" '
            f'font-family="Arial, sans-serif" font-weight="bold" font-size="28" '
            f'letter-spacing="2">{escaped_text}</text>\n'
        )

    svg_content = f"""<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!-- Pauly Bruv Engraving - LightBurn Fine-Line Production Vector File -->
<!-- Layer 00 (#000000, 0.1mm): Cut Profile | Layer 01 (#0000FF, 0.1mm): Fine Line Score | Layer 02 (#FF0000): Feature Fill -->
<svg xmlns="http://www.w3.org/2000/svg"
     width="100mm" height="100mm"
     viewBox="0 0 {w} {h}">
  <g id="Layer_00_Cut_Profile" inkscape:label="Layer 00 - Cut Profile" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     fill="none" stroke="#000000" stroke-width="0.1mm" stroke-linecap="round" stroke-linejoin="round">
    <path d="{cut_path_d}" />
  </g>
  <g id="Layer_01_Line_Score" inkscape:label="Layer 01 - Fine Line Score" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     fill="none" stroke="#0000FF" stroke-width="0.1mm" stroke-linecap="round" stroke-linejoin="round">
    <path d="{score_path_d}" />
  </g>
  <g id="Layer_02_Solid_Fills" inkscape:label="Layer 02 - Solid Fills" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     fill="#FF0000" fill-rule="evenodd" stroke="none">
    <path d="{fill_path_d}" />
{text_svg_block}  </g>
</svg>
"""
    return svg_content


def _apply_diagonal_watermark(base_img: Image.Image) -> Image.Image:
    """
    Overlays repeating diagonal 'PAULY BRUV ENGRAVING • PROOF ONLY' watermark
    across the composite preview image.
    """
    w, h = base_img.size
    overlay = Image.new('RGBA', (w * 2, h * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    try:
        font = ImageFont.truetype("arialbd.ttf", 20)
    except Exception:
        font = ImageFont.load_default()

    watermark_text = "PAULY BRUV ENGRAVING  •  PROOF ONLY"
    step_x = 460
    step_y = 115

    for y in range(0, h * 2, step_y):
        offset = (y // step_y) % 2 * (step_x // 2)
        for x in range(-step_x, w * 2, step_x):
            draw.text(
                (x + offset + 1, y + 1),
                watermark_text,
                fill=(0, 0, 0, 58),
                font=font,
            )
            draw.text(
                (x + offset, y),
                watermark_text,
                fill=(255, 255, 255, 68),
                font=font,
            )

    rotated = overlay.rotate(30, resample=Image.Resampling.BICUBIC)
    cx = (rotated.width - w) // 2
    cy = (rotated.height - h) // 2
    cropped_wm = rotated.crop((cx, cy, cx + w, cy + h))

    composited = Image.alpha_composite(base_img.convert('RGBA'), cropped_wm)
    return composited.convert('RGB')


def _encode_pil_to_data_url(img: Image.Image, quality: int = 91) -> str:
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=quality, optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    return f"data:image/jpeg;base64,{b64}"


def _blend_layer(
    canvas: np.ndarray, alpha_map: np.ndarray, target_rgb: Tuple[float, float, float]
):
    """Smoothly blends a 0..1 float alpha map onto an RGB float canvas."""
    a = alpha_map[:, :, None]
    color = np.array(target_rgb, dtype=np.float32)[None, None, :]
    canvas[:] = canvas * (1.0 - a) + color * a


def render_material_previews(
    cut_mask: np.ndarray,
    score_mask: np.ndarray,
    fill_mask: np.ndarray,
    sketch_intensity: np.ndarray,
) -> Dict[str, str]:
    """
    Renders three high-resolution, anti-aliased fine-line & feature-shaded proofs
    on Natural Slate, Laser Cut MDF / Birch, and Edge-Lit Acrylic.
    """
    h, w = cut_mask.shape[:2]
    rng = np.random.default_rng(seed=42)

    score_aa = cv2.GaussianBlur(
        score_mask.astype(np.float32) / 255.0, (3, 3), 0.5
    )
    score_aa = np.clip(score_aa * 1.35, 0.0, 1.0)

    fill_aa = cv2.GaussianBlur(
        fill_mask.astype(np.float32) / 255.0, (3, 3), 0.55
    )
    fill_aa = np.clip(fill_aa * 1.15, 0.0, 1.0)

    # Combine fine lines, feature fills, and subtle XDoG sketch shading for realistic laser look
    etch_map = np.clip(
        np.maximum(fill_aa * 0.92, np.maximum(score_aa * 0.88, sketch_intensity * 0.55)),
        0.0,
        1.0,
    )

    # Smooth cut silhouette outline
    cut_outline = cv2.Canny(cut_mask, 60, 150)
    cut_aa = cv2.GaussianBlur(cut_outline.astype(np.float32) / 255.0, (3, 3), 0.6)
    cut_aa = np.clip(cut_aa * 0.65, 0.0, 0.5)

    # Coaster plaque boundary
    coaster_mask = np.zeros((h, w), dtype=np.uint8)
    margin = 28
    cv2.rectangle(coaster_mask, (margin, margin), (w - margin, h - margin), 255, -1)
    coaster_edge = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(
        coaster_edge,
        (margin, margin),
        (w - margin, h - margin),
        255,
        thickness=1,
        lineType=cv2.LINE_AA,
    )
    coaster_edge_aa = coaster_edge.astype(np.float32) / 255.0

    # -------------------------------------------------------------------------
    # 1. NATURAL SLATE COASTER
    # -------------------------------------------------------------------------
    slate_bg = np.full((h, w, 3), (30, 33, 38), dtype=np.float32)
    slate_tex = cv2.GaussianBlur(
        rng.normal(0, 5.0, (h, w)).astype(np.float32), (9, 9), 0
    )
    fine_speck = cv2.GaussianBlur(
        rng.normal(0, 1.8, (h, w)).astype(np.float32), (3, 3), 0
    )
    for c in range(3):
        slate_bg[:, :, c] = np.clip(
            slate_bg[:, :, c] + slate_tex + fine_speck, 18, 50
        )

    for c, val in enumerate((15, 17, 21)):
        slate_bg[:, :, c] = np.where(coaster_mask > 0, slate_bg[:, :, c], val)

    _blend_layer(slate_bg, coaster_edge_aa, (88, 96, 108))
    _blend_layer(slate_bg, cut_aa, (100, 108, 120))
    _blend_layer(slate_bg, etch_map, (232, 238, 245))

    slate_pil = _apply_diagonal_watermark(Image.fromarray(slate_bg.astype(np.uint8)))

    # -------------------------------------------------------------------------
    # 2. LASER CUT MDF / BIRCH
    # -------------------------------------------------------------------------
    mdf_bg = np.zeros((h, w, 3), dtype=np.float32)
    y_coords = np.linspace(0, 22, h)[:, None]
    x_coords = np.linspace(0, 5, w)[None, :]
    grain = np.sin(y_coords + 0.3 * np.sin(x_coords * 5.0)) * 4.5
    fine_grain = cv2.GaussianBlur(
        rng.normal(0, 2.8, (h, w)).astype(np.float32), (17, 3), 0
    )
    wood_delta = grain + fine_grain

    base_wood = (225, 194, 152)
    for c in range(3):
        mdf_bg[:, :, c] = np.clip(base_wood[c] + wood_delta, 172, 244)

    for c, val in enumerate((28, 25, 22)):
        mdf_bg[:, :, c] = np.where(coaster_mask > 0, mdf_bg[:, :, c], val)

    _blend_layer(mdf_bg, coaster_edge_aa, (52, 30, 18))
    _blend_layer(mdf_bg, cut_aa, (82, 48, 28))
    _blend_layer(mdf_bg, etch_map, (44, 24, 12))

    mdf_pil = _apply_diagonal_watermark(Image.fromarray(mdf_bg.astype(np.uint8)))

    # -------------------------------------------------------------------------
    # 3. EDGE-LIT ACRYLIC
    # -------------------------------------------------------------------------
    acrylic_bg = np.full((h, w, 3), (9, 14, 26), dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.sqrt(
        ((xx - w / 2) / (w * 0.55)) ** 2 + ((yy - (h - 32)) / (h * 0.72)) ** 2
    )
    glow = np.clip(1.0 - dist, 0.0, 1.0) ** 1.8
    acrylic_bg[:, :, 0] += glow * 14
    acrylic_bg[:, :, 1] += glow * 62
    acrylic_bg[:, :, 2] += glow * 110

    bloom = cv2.GaussianBlur(etch_map, (11, 11), 0) * 0.55
    acrylic_bg[:, :, 0] = np.clip(acrylic_bg[:, :, 0] + bloom * 35, 0, 255)
    acrylic_bg[:, :, 1] = np.clip(acrylic_bg[:, :, 1] + bloom * 175, 0, 255)
    acrylic_bg[:, :, 2] = np.clip(acrylic_bg[:, :, 2] + bloom * 235, 0, 255)

    _blend_layer(acrylic_bg, coaster_edge_aa, (56, 189, 248))
    _blend_layer(acrylic_bg, cut_aa, (56, 189, 248))
    _blend_layer(acrylic_bg, etch_map, (235, 252, 255))

    # LED Base Bar
    acrylic_bg[h - 26 : h - 8, w // 4 : (w * 3) // 4] = (26, 34, 46)
    acrylic_bg[h - 29 : h - 25, w // 4 + 12 : (w * 3) // 4 - 12] = (135, 242, 255)

    acrylic_pil = _apply_diagonal_watermark(
        Image.fromarray(acrylic_bg.astype(np.uint8))
    )

    return {
        'slate': _encode_pil_to_data_url(slate_pil),
        'mdf': _encode_pil_to_data_url(mdf_pil),
        'acrylic': _encode_pil_to_data_url(acrylic_pil),
    }


def process_uploaded_photo(
    image_file, custom_text: str = ""
) -> Tuple[uuid.UUID, str, Dict[str, str]]:
    """
    Full pipeline:
      1. Opens uploaded image & removes background via cached `rembg` (`u2netp`) AI model.
      2. Extracts smooth Cut Profile (Layer 00), Fine-Line Contours (Layer 01), and
         Local Adaptive Feature Fills (Layer 02) for hair, eyes, eyebrows, and badges.
      3. Builds Chaikin-smoothed LightBurn SVG inside settings.PRIVATE_SVG_ROOT.
      4. Renders anti-aliased watermarked proofs for Slate, MDF, and Acrylic.
    """
    pil_img = Image.open(image_file)
    rgb, alpha_mask = remove_background(pil_img)
    cut_mask, score_mask, fill_mask, sketch_intensity = extract_laser_masks(
        rgb, alpha_mask
    )

    svg_xml = build_lightburn_svg(
        cut_mask=cut_mask,
        score_mask=score_mask,
        fill_mask=fill_mask,
        custom_text=custom_text,
    )

    private_dir = Path(settings.PRIVATE_SVG_ROOT)
    private_dir.mkdir(parents=True, exist_ok=True)

    job_uuid = uuid.uuid4()
    svg_filename = f"lightburn_{job_uuid}.svg"
    svg_path = private_dir / svg_filename
    svg_path.write_text(svg_xml, encoding='utf-8')

    previews = render_material_previews(
        cut_mask, score_mask, fill_mask, sketch_intensity
    )
    return job_uuid, svg_filename, previews
