"""
PPT风格视频渲染模块（便签式知识卡片风格）
设计语言：扁平化 + 轻微拟物质感（纸张/便签效果）
运动曲线：ease-out 为主——入场快、收尾缓，干净利落
"""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os
import math
import numpy as np

# ========== 配色 ==========
COLORS = {
    'bg':          (245, 247, 250),  # 背景更浅一点 F5F7FA
    'primary':     (6, 90, 130),     # 主色深蓝 065A82
    'accent':      (230, 70, 70),    # 强调红 E64646（文档里红色系为主）
    'accent_orange': (245, 166, 35), # 强调橙 F5A623
    'secondary':   (28, 114, 147),   # 次色蓝 1C7293
    'text_dark':   (26, 26, 46),     # 深文字 1A1A2E
    'text_main':   (45, 55, 72),     # 主文字 2D3748
    'text_gray':   (113, 128, 150),  # 灰色文字 718096
    'white':       (255, 255, 255),  # 白色
    'card_bg':     (255, 255, 255),  # 卡片背景
    'card_border': (226, 232, 240),  # 卡片边框
    'tip_bg':      (255, 248, 231),  # 口诀框背景 FFF8E7
    'tip_border':  (245, 166, 35),   # 口诀框边框
    'highlight':   (255, 235, 59),   # 黄色高亮 FFEB3B
    'sticky_bg':   (255, 252, 220),  # 便签黄 FFFCDC
    'sticky_tape': (255, 230, 100, 180),  # 胶带色（半透明）
}

# ========== 字体加载 ==========
def _get_font(size, bold=False, chinese=True):
    """获取字体（宋体为中文主字体）"""
    try:
        if chinese:
            # 宋体 - 对应PPT中的 Songti SC
            if bold:
                return ImageFont.truetype("/System/Library/Fonts/Supplemental/Songti.ttc", size, index=2)
            else:
                return ImageFont.truetype("/System/Library/Fonts/Supplemental/Songti.ttc", size, index=0)
        else:
            return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except:
        try:
            # 备用：苹方
            if bold:
                return ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", size, index=2)
            else:
                return ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", size, index=0)
        except:
            return ImageFont.load_default()

# ========== 背景生成 ==========
def create_ppt_background(width, height):
    """生成PPT风格背景：浅灰蓝 + 顶部深蓝条"""
    img = Image.new('RGB', (width, height), COLORS['bg'])
    draw = ImageDraw.Draw(img)
    
    # 顶部深蓝装饰条
    bar_h = int(height * 0.014)  # 约15px @ 1080p
    draw.rectangle([0, 0, width, bar_h], fill=COLORS['primary'])
    
    return img

# ========== 文字渲染 ==========
def render_text(text, font, color, max_width=None, line_spacing=1.3):
    """渲染多行文字，返回PIL Image"""
    # 自动换行
    lines = []
    if max_width and max_width > 0:
        current_line = ""
        for char in text:
            test_line = current_line + char
            bbox = font.getbbox(test_line)
            if bbox[2] - bbox[0] <= max_width or not current_line:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = char
        if current_line:
            lines.append(current_line)
    else:
        lines = [text]
    
    # 计算总尺寸
    line_height = int(font.size * line_spacing)
    total_h = line_height * len(lines)
    # 计算最宽行
    max_w = 0
    for line in lines:
        bbox = font.getbbox(line)
        w = bbox[2] - bbox[0]
        max_w = max(max_w, w)
    
    max_w = max(max_w, 1)
    total_h = max(total_h, 1)
    
    img = Image.new('RGBA', (max_w + 4, total_h + 4), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    y = 2
    for line in lines:
        bbox = font.getbbox(line)
        draw.text((2, y - bbox[1]), line, font=font, fill=color)
        y += line_height
    
    return img

# ========== 单个要点元素 ==========
def make_bullet_point(text, font_size=28, max_width=700, dot_color=None, highlight=False):
    """生成要点条目。highlight=True 时用红色加粗突出显示"""
    if dot_color is None:
        dot_color = COLORS['accent'] if highlight else COLORS['secondary']
    
    # 高亮文字用红色加粗
    text_color = COLORS['accent'] if highlight else COLORS['text_main']
    font = _get_font(font_size, bold=highlight, chinese=True)
    
    # 圆点
    dot_size = int(font_size * 0.55)
    dot_y_offset = int(font_size * 0.35)
    
    # 文字
    text_x = int(font_size * 1.2)
    text_img = render_text(text, font, text_color, max_width=max_width - text_x)
    tw, th = text_img.size
    
    total_w = max(tw + text_x + 10, dot_size + text_x + tw + 10)
    total_h = max(th, dot_size + dot_y_offset * 2)
    
    img = Image.new('RGBA', (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 圆点（高亮时用红色菱形/方块，更醒目）
    dot_x = 0
    dot_y = (total_h - dot_size) // 2
    if highlight:
        # 高亮用红色实心圆 + 外圈光晕
        for r in range(dot_size, dot_size // 2, -2):
            alpha = int(40 * (1 - (r - dot_size//2) / (dot_size/2)))
            cx = dot_x + dot_size // 2
            cy = dot_y + dot_size // 2
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=(230, 70, 70, alpha))
        draw.ellipse([dot_x, dot_y, dot_x + dot_size, dot_y + dot_size],
                     fill=COLORS['accent'])
    else:
        draw.rounded_rectangle([dot_x, dot_y, dot_x + dot_size, dot_y + dot_size],
                               radius=2, fill=dot_color)
    
    # 文字
    img.paste(text_img, (text_x, (total_h - th) // 2), text_img)
    
    return img

# ========== 解题口诀框 ==========
def make_tip_box(poem, title="解题口诀", width=800):
    """生成解题口诀框（便签风格：浅黄底 + 顶部胶带 + 轻微纸张质感）"""
    title_font = _get_font(22, bold=True, chinese=True)
    poem_font = _get_font(28, bold=True, chinese=True)
    tag_font = _get_font(18, bold=True, chinese=True)
    
    # 计算尺寸
    poem_img = render_text(poem, poem_font, COLORS['text_dark'], max_width=width - 60)
    pw, ph = poem_img.size
    
    box_h = max(ph + 85, 130)
    box_w = width
    
    img = Image.new('RGBA', (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 便签背景（浅黄色，带轻微阴影感）
    draw.rounded_rectangle([0, 12, box_w-1, box_h-1], radius=4,
                           fill=COLORS['sticky_bg'], outline=(240, 225, 160), width=1)
    
    # 顶部胶带（半透明黄色，左右超出一点）
    tape_w = int(box_w * 0.35)
    tape_h = 28
    tape_x = (box_w - tape_w) // 2
    tape_y = -6
    # 胶带主体
    tape_rect = [tape_x, tape_y, tape_x + tape_w, tape_y + tape_h]
    draw.rounded_rectangle(tape_rect, radius=3, fill=COLORS['sticky_tape'])
    # 胶带两侧的锯齿感（简化成小三角）
    for i in range(3):
        tx = tape_x + i * (tape_w // 4)
        draw.polygon([(tx, tape_y + tape_h),
                       (tx + 6, tape_y + tape_h + 4),
                       (tx + 12, tape_y + tape_h)],
                     fill=COLORS['sticky_tape'])
    
    # 左侧红色竖线装饰（强调感）
    draw.rectangle([14, 25, 18, box_h - 15], fill=COLORS['accent'])
    
    # 标签小字（可用 title 自定义，默认「解题口诀」）
    tag_text = title
    tag_bbox = tag_font.getbbox(tag_text)
    tag_tw = tag_bbox[2] - tag_bbox[0]
    draw.text((32, 28 - tag_bbox[1]),
              tag_text, font=tag_font, fill=COLORS['accent'])
    
    # 口诀内容
    poem_x = 32
    poem_y = 62
    img.paste(poem_img, (poem_x, poem_y), poem_img)
    
    return img

# ========== 题型标签 ==========
def make_chapter_tag(chapter_num):
    """生成题型标签：橙色方块 + '题型 X'"""
    has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in str(chapter_num))
    font = _get_font(26, bold=True, chinese=has_cjk)
    
    text = f"题型 {chapter_num}"
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    
    pad_x = 40
    pad_y = 20
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2
    
    img = Image.new('RGBA', (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 橙色背景
    draw.rounded_rectangle([0, 0, box_w-1, box_h-1], radius=4,
                           fill=COLORS['accent'])
    
    # 文字（白色）
    draw.text((pad_x - bbox[0], (box_h - th) // 2 - bbox[1]),
              text, font=font, fill=COLORS['white'])
    
    return img

# ========== 几何图卡片 ==========
def make_geometry_card(geo_image, card_w=800, card_h=800, label="几何示意图"):
    """
    生成几何示意图卡片（白底 + 浅灰边框 + 标题）
    geo_image: PIL Image（位图）或 str（SVG 字符串，矢量渲染）
    """
    label_font = _get_font(22, bold=False, chinese=True)
    
    img = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 卡片背景
    draw.rounded_rectangle([0, 0, card_w-1, card_h-1], radius=8,
                           fill=COLORS['card_bg'], outline=COLORS['card_border'], width=1)
    
    # "几何示意图"标签
    label_bbox = label_font.getbbox(label)
    lw = label_bbox[2] - label_bbox[0]
    draw.text((24, 20 - label_bbox[1]), label, font=label_font, fill=COLORS['text_gray'])
    
    # 几何图内容区
    content_top = 60
    content_bottom = card_h - 20
    content_left = 30
    content_right = card_w - 30
    content_w = content_right - content_left
    content_h = content_bottom - content_top
    
    if isinstance(geo_image, str):
        # ===== 矢量图（SVG）：按目标尺寸渲染，2x 超采样保证动画缩放时清晰 =====
        from svg_render import render_svg
        # 先以内容区尺寸渲染得到正确比例，再放大到填满内容区
        # 用 2x 分辨率渲染，动画缩放（最大 1.15x）仍保持锐利
        hi_w = int(content_w * 2)
        hi_h = int(content_h * 2)
        geo_rendered = render_svg(geo_image, hi_w, hi_h)
        # 缩放到内容区实际尺寸（向下采样，保证清晰）
        scale = min(content_w / hi_w, content_h / hi_h)
        new_w = int(hi_w * scale)
        new_h = int(hi_h * scale)
        geo_resized = geo_rendered.resize((new_w, new_h), Image.LANCZOS)
    else:
        # ===== 位图（PNG）：放开 1.0 上限，允许放大填满卡片 =====
        geo_w, geo_h = geo_image.size
        scale = min(content_w / geo_w, content_h / geo_h)
        new_w = int(geo_w * scale)
        new_h = int(geo_h * scale)
        geo_resized = geo_image.resize((new_w, new_h), Image.LANCZOS)
    
    gx = content_left + (content_w - new_w) // 2
    gy = content_top + (content_h - new_h) // 2
    
    img.paste(geo_resized, (gx, gy), geo_resized)
    
    return img


# ========== 大图展示卡片（视觉冲击力强）==========
def make_showcase_card(geo_image, card_w=900, card_h=700, title="", subtitle=""):
    """
    大图展示卡片：深色渐变背景 + 发光边框 + 大图 + 标题
    视觉冲击力强，用来突出重点图示
    """
    img = Image.new('RGBA', (card_w, card_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 深色渐变背景（从上到下：深蓝到更深蓝）
    for y in range(card_h):
        ratio = y / card_h
        r = int(20 + 10 * ratio)
        g = int(40 + 20 * ratio)
        b = int(70 + 30 * ratio)
        draw.line([(0, y), (card_w, y)], fill=(r, g, b, 255))
    
    # 外发光边框（多层，模拟光晕）
    for i in range(6, 0, -1):
        alpha = 20 + i * 15
        draw.rounded_rectangle([i*2, i*2, card_w-1-i*2, card_h-1-i*2], 
                               radius=14, outline=(245, 166, 35, alpha), width=2)
    
    # 主边框
    draw.rounded_rectangle([0, 0, card_w-1, card_h-1], radius=12,
                           outline=(255, 255, 255, 100), width=2)
    
    # 顶部标题区
    if title:
        title_font = _get_font(28, bold=True, chinese=True)
        title_bbox = title_font.getbbox(title)
        tw = title_bbox[2] - title_bbox[0]
        # 标题背景条
        draw.rounded_rectangle([30, 20, 30 + tw + 40, 60], radius=8,
                               fill=(245, 166, 35, 220))
        draw.text((50, 28 - title_bbox[1]), title, font=title_font, fill=(255, 255, 255))
    
    # 副标题（右上角）
    if subtitle:
        sub_font = _get_font(18, bold=False, chinese=True)
        sub_bbox = sub_font.getbbox(subtitle)
        sw = sub_bbox[2] - sub_bbox[0]
        draw.text((card_w - sw - 30, 30 - sub_bbox[1]),
                  subtitle, font=sub_font, fill=(200, 210, 220))
    
    # 几何图（大图展示，占主要空间）
    geo_w, geo_h = geo_image.size
    content_top = 85
    content_bottom = card_h - 35
    content_left = 45
    content_right = card_w - 45
    content_w = content_right - content_left
    content_h = content_bottom - content_top
    
    scale = min(content_w / geo_w, content_h / geo_h, 1.0)
    new_w = int(geo_w * scale)
    new_h = int(geo_h * scale)
    
    geo_resized = geo_image.resize((new_w, new_h), Image.LANCZOS)
    
    # 给图片加一个发光底层（让图片更突出）
    glow_size = 20
    glow_img = Image.new('RGBA', (new_w + glow_size*2, new_h + glow_size*2), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_img)
    for i in range(glow_size, 0, -1):
        alpha = int(30 * (i / glow_size))
        glow_draw.rounded_rectangle([glow_size - i, glow_size - i, 
                                       new_w + glow_size + i, new_h + glow_size + i],
                                      radius=8, outline=(245, 166, 35, alpha), width=2)
    # 把图贴到底层上
    glow_img.paste(geo_resized, (glow_size, glow_size), geo_resized)
    
    gx = content_left + (content_w - new_w) // 2 - glow_size
    gy = content_top + (content_h - new_h) // 2 - glow_size
    
    img.paste(glow_img, (gx, gy), glow_img)
    
    # 底部装饰线
    draw.rounded_rectangle([card_w//2 - 60, card_h - 20, card_w//2 + 60, card_h - 16],
                           radius=2, fill=(245, 166, 35, 180))
    
    return img

# ========== 标题区 ==========
def make_title_block(main_title, en_subtitle="", max_width=800):
    """生成标题块：主标题 + 英文副标题 + 红色装饰线（从左到右绘制）"""
    title_font = _get_font(54, bold=True, chinese=True)
    en_font = _get_font(20, bold=False, chinese=False)
    
    # 主标题
    title_img = render_text(main_title, title_font, COLORS['primary'], max_width=max_width)
    tw, th = title_img.size
    
    # 英文副标题
    en_img = render_text(en_subtitle.upper(), en_font, COLORS['text_gray'], max_width=max_width)
    ew, eh = en_img.size
    
    # 装饰线（红色，文档里强调红色系）
    line_w = min(120, tw * 0.4)  # 约为标题宽度的40%
    line_h = 4
    
    total_w = max(tw, ew, line_w) + 10
    total_h = th + 18 + eh + 24 + line_h
    
    img = Image.new('RGBA', (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # 主标题
    img.paste(title_img, (0, 0), title_img)
    
    # 英文副标题
    img.paste(en_img, (0, th + 18), en_img)
    
    # 装饰线（红色）
    line_y = th + 18 + eh + 18
    draw.rounded_rectangle([0, line_y, line_w, line_y + line_h], radius=2,
                           fill=COLORS['accent'])
    
    return img

# ========== 字幕 ==========
def make_subtitle(text, width=1400, font_size=40):
    """生成底部字幕：无背景、深色文字（PPT背景的反色）、单行"""
    font = _get_font(font_size, bold=False, chinese=True)
    
    # 强制单行显示（不换行）
    text_img = render_text(text, font, COLORS['text_dark'], max_width=None)
    tw, th = text_img.size
    
    # 如果超过最大宽度，缩小字号
    if tw > width:
        scale = width / tw
        new_size = int(font_size * scale * 0.95)
        new_size = max(new_size, 24)  # 最小24号
        font = _get_font(new_size, bold=False, chinese=True)
        text_img = render_text(text, font, COLORS['text_dark'], max_width=None)
        tw, th = text_img.size
    
    # 无背景，只有文字
    img = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
    img.paste(text_img, (0, 0), text_img)
    
    return img

# ========== 测试 ==========
if __name__ == "__main__":
    # 测试生成
    bg = create_ppt_background(1920, 1080)
    bg.save("/tmp/test_bg.png")
    print("背景测试完成")
    
    tag = make_chapter_tag("一")
    tag.save("/tmp/test_tag.png")
    print(f"题型标签: {tag.size}")
    
    title = make_title_block("四边形构造全等", "QUADRILATERAL CONGRUENCE")
    title.save("/tmp/test_title.png")
    print(f"标题: {title.size}")
    
    bp = make_bullet_point("两对邻边分别相等")
    bp.save("/tmp/test_bullet.png")
    print(f"要点: {bp.size}")
    
    tip = make_tip_box("边等连对角，全等自然成")
    tip.save("/tmp/test_tip.png")
    print(f"口诀框: {tip.size}")
    
    sub = make_subtitle("大家好，欢迎来到全等三角形压轴题专项突破")
    sub.save("/tmp/test_subtitle.png")
    print(f"字幕: {sub.size}")
