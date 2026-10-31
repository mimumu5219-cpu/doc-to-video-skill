#!/usr/bin/env python3
"""
右下角「视频通话」小窗
- 形象：透明底 PNG（抠好的角色图）
- 背景：书房暖光等小窗背景图（自动 cover 裁切 + 虚化 + 暖色背光）
- 对口型：解析该页 TTS 配音的音量包络，逐帧驱动嘴巴开合，并叠加轻微呼吸/起伏
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

DEFAULT_WINDOW = dict(
    w=320, h=260,          # 小窗尺寸（含底部信息条）
    radius=24,
    margin_right=48,
    margin_bottom=48,
    pos='right',           # right / left
    mouth_anchor=(0.50, 0.427),   # 嘴巴位置（相对形象包围盒的比例）
    label='',              # 底部姓名标签，空则不显示
)

# 缓存的缩放级别（说话时轻微放大，避免逐帧重采样）
_SCALE_STEPS = [1.00, 1.005, 1.01, 1.015, 1.02, 1.025, 1.03]


# ========== 素材加载 ==========
def load_avatar(path, height):
    """加载透明底形象，按目标高度缩放，返回 RGBA"""
    img = Image.open(path).convert('RGBA')
    bbox = img.split()[-1].getbbox()
    if bbox:
        img = img.crop(bbox)
    ratio = height / img.height
    return img.resize((int(img.width * ratio), height), Image.LANCZOS)


def load_window_bg(path, size):
    """加载小窗背景：cover 裁切 + 虚化 + 压暗，作为人物身后环境"""
    w, h = size
    img = Image.open(path).convert('RGB')
    scale = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left = (img.width - w) // 2
    top = (img.height - h) // 2
    img = img.crop((left, top, left + w, top + h))
    img = img.filter(ImageFilter.GaussianBlur(3.0))
    arr = np.asarray(img).astype(np.float32)
    # 轻微压暗 + 暖色偏移，让深色形象更突出
    arr = arr * 0.92
    arr[:, :, 0] += 6
    arr[:, :, 2] -= 4
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _radial_glow(w, h, cx, cy, rx, ry, color, peak=52):
    """人物身后的柔和暖色背光，用来分离深色形象与暗背景"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    a = np.clip(1 - d, 0, 1) ** 1.8 * peak
    layer = np.zeros((h, w, 4), dtype=np.float32)
    layer[:, :, 0], layer[:, :, 1], layer[:, :, 2] = color
    layer[:, :, 3] = a
    return Image.fromarray(layer.astype(np.uint8))


def _font(size):
    try:
        from ppt_style import _get_font
        return _get_font(size, bold=False, chinese=True)
    except Exception:
        return ImageFont.load_default()


# ========== 小窗底图（静态部分）==========
def build_window_base(bg_path, cfg):
    """构建小窗静态底图（背景、边框、投影、通话中角标、底部信息条）"""
    W, H = cfg['w'], cfg['h']
    pad = 22  # 投影留白
    cw, ch = W + pad * 2, H + pad * 2

    bg = load_window_bg(bg_path, (W, H)) if bg_path and os.path.exists(bg_path) else _fallback_bg(W, H)
    bg = Image.alpha_composite(
        bg.convert('RGBA'),
        _radial_glow(W, H, W * 0.5, H * 0.50, W * 0.48, H * 0.46, (255, 191, 120), 60)
    )

    # 圆角裁切
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, H - 1], radius=cfg['radius'], fill=255)
    inner = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    inner.paste(bg, (0, 0), mask)

    # 底部信息条：上深下浅的渐隐黑条
    bar = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bar_h = 42
    for i in range(bar_h):
        a = int(105 * (i / bar_h) ** 1.6)
        bd.line([(0, H - bar_h + i), (W, H - bar_h + i)], fill=(0, 0, 0, a))
    inner = Image.alpha_composite(inner, Image.composite(bar, Image.new('RGBA', (W, H), (0, 0, 0, 0)), mask))

    # 脚下的柔和接触阴影，让形象"站在"房间里
    contact = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(contact)
    cy0 = H - 34
    cd.ellipse([W * 0.5 - W * 0.27, cy0 - 11, W * 0.5 + W * 0.27, cy0 + 11], fill=(0, 0, 0, 110))
    contact = contact.filter(ImageFilter.GaussianBlur(9))
    inner = Image.alpha_composite(inner, Image.composite(contact, Image.new('RGBA', (W, H), (0, 0, 0, 0)), mask))

    # 「通话中」角标
    d = ImageDraw.Draw(inner)
    pill_w, pill_h = 92, 28
    d.rounded_rectangle([12, 12, 12 + pill_w, 12 + pill_h], radius=14, fill=(0, 0, 0, 96))
    d.ellipse([12 + 11, 12 + 9, 12 + 20, 12 + 18], fill=(76, 217, 100, 255))
    d.text((12 + 26, 12 + 5), '通话中', font=_font(16), fill=(255, 255, 255, 240))

    # 麦克风图标（右下）
    mx, my = W - 30, H - 24
    d.rounded_rectangle([mx - 6, my - 16, mx + 6, my + 2], radius=6, fill=(255, 255, 255, 210))
    d.arc([mx - 10, my - 6, mx + 10, my + 12], start=0, end=180, fill=(255, 255, 255, 210), width=2)
    d.line([(mx, my + 12), (mx, my + 17)], fill=(255, 255, 255, 210), width=2)

    # 白色描边
    ImageDraw.Draw(inner).rounded_rectangle(
        [1, 1, W - 2, H - 2], radius=cfg['radius'], outline=(255, 255, 255, 235), width=3)

    # 投影 + 贴到带留白的画布
    canvas = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
    shadow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [0, 0, W - 1, H - 1], radius=cfg['radius'], fill=(0, 0, 0, 140))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    canvas.alpha_composite(shadow, (pad, pad + 8))
    canvas.alpha_composite(inner, (pad, pad))
    return canvas, pad


def _fallback_bg(w, h):
    """没有背景图时：深紫夜色渐变 + 光斑"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    t = yy / max(h - 1, 1)
    arr = np.zeros((h, w, 3), dtype=np.float32)
    arr[:, :, 0] = 44 - 18 * t
    arr[:, :, 1] = 34 - 14 * t
    arr[:, :, 2] = 62 - 22 * t
    glow = np.clip(1 - (((xx - w * 0.72) / (w * 0.42)) ** 2 + ((yy - h * 0.22) / (h * 0.3)) ** 2), 0, 1)
    arr += (glow ** 2)[..., None] * np.array([46, 22, 74], dtype=np.float32)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ========== 音频包络 ==========
def audio_envelope(audio_path, fps=30, gate=0.28):
    """把配音音量转成逐帧「张嘴程度」0~1，带快起慢落平滑"""
    env = np.zeros(1, dtype=np.float32)
    if audio_path and os.path.exists(audio_path):
        try:
            from moviepy import AudioFileClip
            clip = AudioFileClip(audio_path)
            samples = clip.to_soundarray()
            dur = clip.duration
            clip.close()
            mono = samples.mean(axis=1) if samples.ndim > 1 else samples
            sr = len(mono) / max(dur, 0.001)
            block = sr / fps
            n = max(int(len(mono) / block), 1)
            vals = np.array([
                float(np.sqrt(np.mean(mono[int(i * block):int((i + 1) * block) + 1] ** 2)) + 1e-6)
                for i in range(n)
            ], dtype=np.float32)
            ref = float(np.percentile(vals, 95)) if vals.size else 0.0
            if ref > 1e-4:
                floor = ref * gate
                env = np.clip((vals - floor) / max(ref - floor, 1e-4), 0, 1) ** 0.75
        except Exception as e:
            print(f'    [小窗] 解析音频包络失败，改用静音口型: {e}')
            env = np.zeros(1, dtype=np.float32)

    # 快起慢落（模拟说话的嘴部惯性）
    smooth = np.zeros_like(env)
    prev = 0.0
    for i, v in enumerate(env):
        a = 0.60 if v > prev else 0.24
        prev = prev + (v - prev) * a
        smooth[i] = prev
    return smooth


# ========== 逐帧渲染 ==========
def _draw_mouth(img, anchor, openness):
    """在形象上绘制嘴巴：闭合为细线，张开为椭圆 + 紫舌"""
    w, h = img.size
    cx = anchor[0] * w
    cy = anchor[1] * h
    mw = max(int(w * 0.075), 11)
    if openness < 0.05:
        return img
    mh = int(mw * (0.22 + 0.58 * openness))
    layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    box = [cx - mw / 2, cy - mh / 2, cx + mw / 2, cy + mh / 2]
    # 无描边的暗色口腔，小尺寸下更像自然的张嘴
    d.ellipse(box, fill=(16, 11, 20, 255))
    if openness > 0.34:
        tongue = [cx - mw * 0.34, cy + mh * 0.04,
                  cx + mw * 0.34, cy + mh * 0.50]
        d.ellipse(tongue, fill=(126, 74, 200, 230))
    # 极轻的柔化，避免硬边锯齿
    layer = layer.filter(ImageFilter.GaussianBlur(0.35))
    return Image.alpha_composite(img, layer)


def create_avatar_window_clip(audio_path, duration, video_w, video_h, cfg, intro=False):
    """生成小窗 clip（带透明遮罩，直接叠在主画面右下角）"""
    from moviepy import VideoClip

    base, pad = build_window_base(cfg.get('bg'), cfg)
    W, H = cfg['w'], cfg['h']
    canvas_w, canvas_h = base.size

    avatar = load_avatar(cfg['avatar'], int(H * 0.86))
    scales = {s: avatar.resize((int(avatar.width * s), int(avatar.height * s), ), Image.LANCZOS)
              for s in _SCALE_STEPS}
    rest_x = (W - avatar.width) // 2
    rest_y = H - avatar.height - 30   # 站在底部信息条上方

    env = audio_envelope(audio_path, fps=30)
    n = len(env)

    if cfg.get('pos') == 'left':
        win_x = int(video_w * 0.0) + cfg['margin_right']
    else:
        win_x = video_w - W - cfg['margin_right']
    win_y = video_h - H - cfg['margin_bottom']

    label_font = _font(15)
    mask_arr = np.asarray(base.split()[-1]).astype(np.float32) / 255.0

    def _ease_out(p):
        return 1 - (1 - p) ** 3

    def _intro(t):
        """入场：0.55 秒内从右侧 28px 滑入 + 淡入"""
        if not intro:
            return 0.0, 1.0
        p = min(t / 0.55, 1.0)
        e = _ease_out(p)
        return 28 * (1 - e), e

    def make_frame(t):
        idx = min(int(t * 30), n - 1) if n > 0 else 0
        v = float(env[idx]) if n > 0 else 0.0
        scale = 1.0 + 0.03 * v
        step = min(_SCALE_STEPS, key=lambda s: abs(s - scale))
        av = _draw_mouth(scales[step].copy(), cfg['mouth_anchor'], v)

        frame = base.copy()
        ox = (canvas_w - av.width) // 2
        oy = pad + rest_y - (av.height - avatar.height) + int(-2 * v)
        frame.alpha_composite(av, (ox, oy))

        # 底部信息条文字：姓名 + 计时
        d = ImageDraw.Draw(frame)
        txt_y = pad + H - 27
        if cfg.get('label'):
            d.text((pad + 14, txt_y), cfg['label'], font=label_font, fill=(255, 255, 255, 235))
        sec = int(t)
        d.text((pad + W - 104, txt_y), f'{sec // 60:02d}:{sec % 60:02d}',
               font=label_font, fill=(255, 255, 255, 225))

        dx, fade = _intro(t)
        if dx:
            frame = Image.fromarray(np.roll(np.asarray(frame), int(dx), axis=1))
        return np.asarray(frame.convert('RGB'))

    def make_mask(t):
        _, fade = _intro(t)
        return mask_arr * fade

    clip = VideoClip(make_frame, duration=duration)
    clip.mask = VideoClip(make_mask, duration=duration)
    return clip.with_position((win_x - pad, win_y - pad)), (win_x, win_y)


def parse_window_config(global_config, work_dir):
    """从 content.txt 全局设置读取小窗配置；未配置形象则返回 None"""
    avatar_name = (global_config.get('形象') or '').strip()
    if not avatar_name or avatar_name.lower() in ('off', 'none', '关闭'):
        return None

    def _resolve(name, default):
        if not name:
            return default
        for base in (work_dir, os.path.join(work_dir, 'images')):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
        return os.path.join(work_dir, name)

    bg_name = (global_config.get('小窗背景') or '').strip() or 'avatar_bg.png'
    if not os.path.exists(_resolve(bg_name, '')):
        for ext in ('jpg', 'jpeg', 'png', 'webp'):
            if os.path.exists(os.path.join(work_dir, f'avatar_bg.{ext}')):
                bg_name = f'avatar_bg.{ext}'
                break

    size = 320
    if (global_config.get('小窗尺寸') or '').strip().isdigit():
        size = int(global_config.get('小窗尺寸').strip())

    anchor = DEFAULT_WINDOW['mouth_anchor']
    raw = (global_config.get('口型位置') or '').strip()
    if raw and ',' in raw:
        try:
            anchor = tuple(float(x) for x in raw.split(',')[:2])
        except ValueError:
            pass

    cfg = dict(DEFAULT_WINDOW)
    cfg.update(
        w=size,
        h=int(size * 0.8125),
        avatar=_resolve(avatar_name, ''),
        bg=_resolve(bg_name, '') if bg_name else '',
        pos='left' if (global_config.get('小窗位置') or '').strip() == '左下' else 'right',
        label=(global_config.get('小窗姓名') or '').strip(),
        mouth_anchor=anchor,
        lip_sync=(global_config.get('口型') or 'on').strip().lower() not in ('off', 'none', '关闭'),
    )
    return cfg
