#!/usr/bin/env python3
"""
知识点讲解视频生成器 - PPT风格版
完全还原PPT样式：浅灰蓝背景、蓝橙配色、宋体字、左文右图布局
支持口播字幕
"""
import os
import sys
import asyncio
import re
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, CompositeVideoClip, AudioFileClip, VideoClip, concatenate_videoclips

# 添加当前目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ppt_style import (
    COLORS, create_ppt_background, make_title_block, make_chapter_tag,
    make_bullet_point, make_tip_box, make_geometry_card, make_subtitle,
    render_text, _get_font
)
from avatar_talk import parse_window_config, create_avatar_window_clip

# ========== 动画参数 ==========
# ========== 动画参数（ease-out 风格：快入缓出）==========
ANIM_DURATION = 0.45       # 入场动画时长（更短更快）
STAGGER_DELAY = 0.10       # 元素错峰延迟（更紧凑）
FADE_DURATION = 0.40       # 淡入淡出时长
SLIDE_UP_DIST = 18         # 文字上滑淡入的距离（px）
BOUNCE_OVERSHOOT = 0.08    # 弹跳过冲比例
CARD_ROTATION = -2.5       # 卡片轻微旋转角度（度）
SECTION_BLANK = 0.35       # 大章节转场留白时间
SECTION_GAP = 0.15         # 两部分之间的间隔（更紧凑）
SUBTITLE_FONT_SIZE = 36    # 字幕字号
EMPHASIS_DURATION = 1.6    # 强调动效持续时长（秒），之后稳定静止
SLIDE_DISTANCE = 100       # 从左/右/上滑入的距离（px）

# ========== 内容解析 ==========
def parse_content(filepath):
    """解析内容配置文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    global_config = {}
    sections = []
    current_section = None
    current_field = None
    
    for line in lines:
        line = line.rstrip('\n')
        
        # 跳过空行和注释
        if not line.strip() or line.strip().startswith('#'):
            continue
        
        # 全局设置
        if line.startswith('=== 全局设置 ==='):
            current_section = None
            current_field = None
            continue
        
        # 新的一部分
        if line.startswith('=== 第'):
            if current_section:
                sections.append(current_section)
            current_section = {
                'title': '',
                'subtitle': '',   # 英文副标题
                'chapter': '',    # 题型编号
                'diagram': '',           # 几何图文件名
                'diagram_label': '',     # 图卡标题（默认「几何示意图」）
                'diagram_layers': [],    # 图示标注图层（分步出现）
                'points': [],            # 要点（可为字符串或 (文本, 动效类型) 元组）
                'tip': '',        # 解题口诀
                'tip_anim': 'pulse_emph',  # 口诀动效，默认 pulse_emph 强调（入场后1.6秒静止）
                'title_anim': 'scale_bounce',  # 标题动效，默认 scale_bounce
                'narration': '',
                'sec_title': '',         # 要点小标题，默认「模型核心」
                'tip_title': '',         # 口诀框标题，默认「解题口诀」
            }
            current_field = None
            continue
        
        # 全局配置项
        if current_section is None and ':' in line:
            key, val = line.split(':', 1)
            global_config[key.strip()] = val.strip()
            continue
        
        if current_section is None:
            continue
        
        # 标题
        if line.startswith('标题:'):
            current_section['title'] = line[3:].strip()
            current_field = 'title'
            continue
        
        # 副标题（英文）
        if line.startswith('副标题:'):
            current_section['subtitle'] = line[5:].strip()
            current_field = 'subtitle'
            continue
        
        # 题型编号
        if line.startswith('题型:'):
            current_section['chapter'] = line[3:].strip()
            current_field = 'chapter'
            continue
        
        # 几何图
        if line.startswith('几何图:'):
            current_section['diagram'] = line[4:].strip()
            current_field = 'diagram'
            continue
        
        # 图卡标题（可选）
        if line.startswith('图示标题:'):
            current_section['diagram_label'] = line[5:].strip()
            current_field = 'diagram_label'
            continue
        
        # 要点小标题（可选）
        if line.startswith('要点小标题:'):
            current_section['sec_title'] = line[6:].strip()
            current_field = 'sec_title'
            continue
        
        # 图示标注（多层，分步出现）
        if line.startswith('图示标注:'):
            current_section['diagram_layers'] = []
            current_field = 'diagram_layers'
            continue
        
        # 要点
        if line.startswith('要点:'):
            current_field = 'points'
            continue
        
        # 解题口诀
        if line.startswith('口诀:'):
            current_section['tip'] = line[3:].strip()
            current_field = 'tip'
            continue
        
        # 口诀动效（可选，默认 pulse_idle）
        if line.startswith('口诀动效:'):
            current_section['tip_anim'] = line[5:].strip()
            continue
        
        # 标题动效（可选，默认 scale_bounce）
        if line.startswith('标题动效:'):
            current_section['title_anim'] = line[5:].strip()
            continue
        
        # 旁白
        if line.startswith('旁白:'):
            current_section['narration'] = line[3:].strip()
            current_field = 'narration'
            continue
        
        # 续行
        if current_field == 'points' and line.strip().startswith('-'):
            content = line.strip()[1:].strip()
            # 支持要点标记动效，格式：
            #   [入场] 文字              —— 仅入场，入场后静止
            #   [入场,强调] 文字          —— 入场后强调1.6秒，然后静止
            # 入场标记：left/right/top/zoom/rotate/flip/elastic
            # 强调标记：bounce/highlight/pulse/shake/wiggle
            entry_map = {
                'left': 'slide_left',
                'right': 'slide_right',
                'top': 'slide_top',
                'zoom': 'zoom_in',
                'rotate': 'rotate_in',
                'flip': 'flip_in',
                'elastic': 'elastic_in',
            }
            emphasis_map = {
                'bounce': 'bounce_emph',
                'highlight': 'highlight_emph',
                'pulse': 'pulse_emph',
                'shake': 'shake_emph',
                'wiggle': 'wiggle_emph',
            }
            point_anim = 'fade_slide_up'
            point_emph = ''
            # 匹配 [xxx] 或 [xxx,yyy]
            import re as _re
            m = _re.match(r'^\[([^\]]+)\]\s*', content)
            if m:
                tags = m.group(1).split(',')
                if len(tags) == 1:
                    tag = tags[0].strip()
                    if tag in entry_map:
                        point_anim = entry_map[tag]
                    elif tag in emphasis_map:
                        point_anim = 'fade_slide_up'
                        point_emph = emphasis_map[tag]
                elif len(tags) >= 2:
                    e_tag = tags[0].strip()
                    p_tag = tags[1].strip()
                    if e_tag in entry_map:
                        point_anim = entry_map[e_tag]
                    if p_tag in emphasis_map:
                        point_emph = emphasis_map[p_tag]
                content = content[m.end():].strip()
            # 存储为 (文本, 入场动效, 强调动效) 元组
            current_section['points'].append((content, point_anim, point_emph))
        elif current_field == 'diagram_layers' and line.strip().startswith('-'):
            content = line.strip()[1:].strip()
            current_section['diagram_layers'].append(content)
        elif current_field == 'narration':
            current_section['narration'] += line.strip()
    
    if current_section:
        sections.append(current_section)

    # 全局「要点小标题 / 口诀标题」作为各页默认值
    for key, field in (('要点小标题', 'sec_title'), ('口诀标题', 'tip_title')):
        val = (global_config.get(key) or '').strip()
        if val:
            for s in sections:
                if not s.get(field):
                    s[field] = val

    return global_config, sections

# ========== 加载几何图 ==========
def load_geo_image(filename, search_dirs):
    """
    加载几何图。
    .svg 文件返回 SVG 字符串（由 make_geometry_card 矢量渲染），
    其他格式返回 PIL Image（位图）。
    """
    for d in search_dirs:
        path = os.path.join(d, filename)
        if os.path.exists(path):
            if filename.lower().endswith('.svg'):
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                return Image.open(path).convert('RGBA')
    # 尝试直接当路径
    if os.path.exists(filename):
        if filename.lower().endswith('.svg'):
            with open(filename, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return Image.open(filename).convert('RGBA')
    return None

# ========== 生成PPT风格单页视频（便签式卡片风格）==========
def create_ppt_section(section, audio_duration, bg_img, video_w, video_h, window_cfg=None):
    """
    生成PPT风格的单页视频片段
    动画风格：
    - 整体淡入淡出转场 + 留白
    - 标题：缩放弹入（从略小放大+过冲）
    - 装饰线：从左到右绘制生长
    - 要点文字：上滑淡入（从下方18px滑入+淡入）
    - 口诀卡片：斜向滑入 + 轻微旋转 + 弹跳落地
    - 几何图卡片：斜向滑入 + 轻微旋转
    - 图示标注：弹出淡入
    """
    from moviepy import vfx
    import math
    
    # ===== 布局参数 =====
    left_margin = int(video_w * 0.055)
    right_margin = int(video_w * 0.05)
    top_margin = int(video_h * 0.07)
    content_w = video_w - left_margin - right_margin

    # 右下角有通话小窗时：出图页改成「左图右文」，避免图卡和小窗重叠
    diagram_left = bool(window_cfg) and bool(section['diagram'])
    if diagram_left:
        img_col_w = int(content_w * 0.46)
        txt_col_w = int(content_w * 0.42)
        img_col_x = left_margin
        txt_col_x = left_margin + img_col_w + int(content_w * 0.06)
    else:
        # 无图页 + 有小窗时文字列放宽，避免右半屏过空
        txt_col_w = int(content_w * (0.60 if window_cfg else 0.45))
        img_col_w = int(content_w * 0.50)
        txt_col_x = left_margin
        img_col_x = left_margin + txt_col_w + int(content_w * 0.05)

    
    # ===== 元素定义 =====
    # 每个元素: (name, img_pil, x, y, anim_type, delay, flags)
    # anim_type: 'fade_slide_up' | 'scale_bounce' | 'card_slide_rot' | 'pop_fade' | 'line_grow'
    #            'bounce_idle' | 'pulse_idle' | 'shake_idle' | 'wiggle_idle' | 'highlight_bounce'
    # flags 新增字段（持续动画用）:
    #   idle_amp: 持续动画幅度（默认值见各类型）
    #   idle_freq: 持续动画频率 Hz（默认 1.5）
    #   idle_delay: 入场后多久开始持续动画（秒，默认 0.3）
    elements = []
    
    # 1. 题型标签（左图右文时，图卡会盖住左列顶部，标签改放右列）
    if section['chapter']:
        tag = make_chapter_tag(section['chapter'])
        tw, th = tag.size
        tag_x = txt_col_x if diagram_left else left_margin
        tag_y = top_margin - 6
        elements.append(('tag', tag, tag_x, tag_y, 'fade_slide_up', 0.0, {}))
    
    # 2. 标题区（入场动效可通过 标题动效 指定，默认 scale_bounce）
    title = make_title_block(section['title'], section.get('subtitle', ''),
                              max_width=txt_col_w)
    t_w, t_h = title.size
    title_x = txt_col_x
    title_y = top_margin + 75
    title_anim = section.get('title_anim', 'scale_bounce')
    title_flags = {'bounce_amount': 0.06}
    elements.append(('title', title, title_x, title_y, title_anim, 0.10, title_flags))
    
    # 3. 装饰线（从左到右生长）—— 单独处理，从标题图里提取不方便
    # 简化：标题整体缩放弹入，装饰线包含在标题图中
    
    # 4. 要点小标题（可用 要点小标题 自定义，默认「模型核心」）
    sec_title_font = _get_font(28, bold=True, chinese=True)
    sec_title_img = render_text(section.get('sec_title') or '模型核心', sec_title_font, COLORS['text_dark'])
    st_w, st_h = sec_title_img.size
    sec_y = title_y + t_h + 35
    elements.append(('sec_title', sec_title_img, title_x, sec_y, 'fade_slide_up', 0.25, {}))
    
    # 5. 要点列表（支持动效标记）
    point_y = sec_y + st_h + 20
    point_delay = 0.35
    for i, point_item in enumerate(section['points']):
        # 兼容三种格式：纯字符串 / (文本, 入场) / (文本, 入场, 强调)
        if isinstance(point_item, tuple):
            if len(point_item) == 3:
                point_text, point_anim, point_emph = point_item
            else:
                point_text, point_anim = point_item
                point_emph = ''
        else:
            point_text, point_anim, point_emph = point_item, 'fade_slide_up', ''

        is_highlight = (point_emph == 'highlight_emph')
        # 左图右文布局时文字区更窄，要点多时自动缩小字号，保证不压到右下小窗
        point_font = 28
        point_gap = 16
        if diagram_left and len(section['points']) >= 4:
            point_font, point_gap = 24, 12
        elif diagram_left and len(section['points']) == 3:
            point_font, point_gap = 26, 14

        bp = make_bullet_point(point_text, font_size=point_font, max_width=txt_col_w - 30,
                               highlight=is_highlight)
        bp_w, bp_h = bp.size
        # 根据入场动效类型传入参数
        point_flags = {'slide_dist': SLIDE_UP_DIST}
        if point_anim in ('slide_left', 'slide_right', 'slide_top'):
            point_flags['slide_dist'] = SLIDE_DISTANCE
        # 强调动效参数（入场后播放 EMPHASIS_DURATION 秒然后静止）
        if point_emph:
            point_flags['emphasis_anim'] = point_emph
            point_flags['emphasis_dur'] = EMPHASIS_DURATION
            if point_emph == 'bounce_emph':
                point_flags['emph_amp'] = 10
                point_flags['emph_freq'] = 2.0
            elif point_emph == 'highlight_emph':
                point_flags['emph_amp'] = 12
                point_flags['emph_freq'] = 2.2
                point_flags['pulse_amp'] = 0.06
                point_flags['wiggle_amp'] = 2.0
            elif point_emph == 'pulse_emph':
                point_flags['emph_amp'] = 0.06
                point_flags['emph_freq'] = 1.5
            elif point_emph == 'shake_emph':
                point_flags['emph_amp'] = 8
                point_flags['emph_freq'] = 3.0
            elif point_emph == 'wiggle_emph':
                point_flags['emph_amp'] = 3.0
                point_flags['emph_freq'] = 2.0
        elements.append((f'point_{i}', bp, title_x, point_y, point_anim, point_delay, point_flags))
        point_y += bp_h + point_gap
        point_delay += STAGGER_DELAY
    
    # 6. 解题口诀（斜向滑入 + 旋转 + 弹跳；入场后强调1.6秒然后静止）
    tip_y = point_y + 25
    tip_delay = point_delay + 0.15
    if section['tip']:
        tip = make_tip_box(section['tip'], title=section.get('tip_title') or '解题口诀', width=txt_col_w)
        tip_w, tip_h = tip.size
        tip_emph = section.get('tip_anim', 'pulse_emph')
        # 入场始终用 card_slide_rot（滑入+旋转+弹跳），入场后叠加强调动效（1.6秒后静止）
        tip_flags = {'rotation': CARD_ROTATION, 'bounce': True, 'from_dir': 'bottom_left'}
        # tip_anim 支持的值：pulse_emph / bounce_emph / highlight_emph / shake_emph / wiggle_emph / none
        if tip_emph and tip_emph != 'none':
            tip_flags['emphasis_anim'] = tip_emph
            tip_flags['emphasis_dur'] = EMPHASIS_DURATION
            if tip_emph == 'pulse_emph':
                tip_flags['emph_amp'] = 0.06
                tip_flags['emph_freq'] = 1.5
            elif tip_emph == 'bounce_emph':
                tip_flags['emph_amp'] = 10
                tip_flags['emph_freq'] = 2.0
            elif tip_emph == 'highlight_emph':
                tip_flags['emph_amp'] = 12
                tip_flags['emph_freq'] = 2.2
                tip_flags['pulse_amp'] = 0.06
            elif tip_emph == 'shake_emph':
                tip_flags['emph_amp'] = 8
                tip_flags['emph_freq'] = 3.0
            elif tip_emph == 'wiggle_emph':
                tip_flags['emph_amp'] = 3.0
                tip_flags['emph_freq'] = 2.0
        elements.append(('tip', tip, title_x, tip_y, 'card_slide_rot', tip_delay, tip_flags))
        point_y = tip_y + tip_h
    
    # 7. 几何图卡片（斜向滑入 + 轻微旋转）
    geo_card_pos = None
    if section['diagram']:
        geo_img = load_geo_image(section['diagram'], 
                                  [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images'),
                                   os.path.dirname(os.path.abspath(__file__))])
        if geo_img:
            card_h = int(video_h * (0.86 if diagram_left else 0.82))
            card = make_geometry_card(geo_img, card_w=img_col_w, card_h=card_h,
                                      label=section.get('diagram_label', '几何示意图'))
            cw, ch = card.size
            card_x = img_col_x
            card_y = top_margin + 10
            geo_card_pos = (card_x, card_y, cw, ch)
            # 几何图入场后持续呼吸动效（脉冲缩放+上下浮动），不停止
            geo_flags = {'rotation': 1.5, 'bounce': False,
                         'from_dir': 'left' if diagram_left else 'right',
                         'idle_anim': 'breath_idle'}
            elements.append(('geo_card', card, card_x, card_y, 'card_slide_rot', 0.15, geo_flags))
    
    # 8. 图示标注图层（弹出淡入）
    if section.get('diagram_layers') and geo_card_pos:
        card_x, card_y, cw, ch = geo_card_pos
        content_top = card_y + 60
        content_bottom = card_y + ch - 20
        content_left = card_x + 30
        content_right = card_x + cw - 30
        content_w_layer = content_right - content_left
        content_h_layer = content_bottom - content_top
        
        layer_positions = [
            (0.78, 0.06),
            (0.18, 0.42),
            (0.55, 0.82),
            (0.12, 0.75),
        ]
        
        # 基础延迟：几何图卡片入场完成后才开始出标注
        base_layer_delay = 0.15 + ANIM_DURATION + 0.1
        
        for i, layer_file in enumerate(section['diagram_layers']):
            layer_img = load_geo_image(layer_file,
                                        [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'images'),
                                         os.path.dirname(os.path.abspath(__file__))])
            if layer_img:
                lw, lh = layer_img.size
                rx, ry = layer_positions[i % len(layer_positions)]
                lx = int(content_left + content_w_layer * rx - lw / 2)
                ly = int(content_top + content_h_layer * ry - lh / 2)
                
                delay = base_layer_delay + i * 0.45
                
                elements.append((f'layer_{i}', layer_img, lx, ly, 'pop_fade', delay,
                                 {'scale_from': 0.85}))
    
    # ===== 计算时间线 =====
    max_delay = max(e[5] for e in elements) if elements else 0
    all_in_time = max_delay + ANIM_DURATION + 0.2
    
    # 总时长（含淡入淡出留白）
    min_duration = all_in_time + 1.2 + FADE_DURATION
    total_duration = max(audio_duration, min_duration) + SECTION_GAP
    
    # 淡入淡出时间点
    fade_in_end = FADE_DURATION  # 从0到fade_dur完成淡入
    fade_out_start = total_duration - FADE_DURATION - SECTION_GAP
    
    # ===== 创建背景 =====
    bg_clip = ImageClip(np.array(bg_img)).with_duration(total_duration)
    
    # ===== 生成每个元素的clip =====
    clips = [bg_clip]
    
    for name, img, x, y, anim_type, delay, flags in elements:
        iw, ih = img.size
        start_t = delay
        
        # 统一的位置/缩放/透明度动画函数
        def make_clip(img_pil, x_pos, y_pos, start_time, anim_type, flags_dict, iw_img, ih_img):
            pil_img = img_pil
            total_dur = total_duration
            fd_in = FADE_DURATION
            fd_out_start = fade_out_start
            
            def make_frame(t):
                # 计算当前时间的状态
                # 入场动画进度
                elapsed = t - start_time
                if elapsed < 0:
                    progress = 0.0
                elif elapsed < ANIM_DURATION:
                    progress = elapsed / ANIM_DURATION
                    # ease-out cubic
                    progress = 1 - (1 - progress) ** 3
                else:
                    progress = 1.0
                
                # 离场动画（整体淡出，配合章节转场）
                if t >= fd_out_start:
                    fade_progress = (t - fd_out_start) / FADE_DURATION
                    fade_progress = min(fade_progress, 1.0)
                    opacity = 1.0 - fade_progress
                elif t < fd_in:
                    # 开场整体淡入
                    fade_p = min(t / fd_in, 1.0)
                    opacity = fade_p
                else:
                    opacity = 1.0
                
                # ===== 根据动画类型计算位置和缩放 =====
                cur_x = x_pos
                cur_y = y_pos
                scale = 1.0
                rotation = 0.0
                
                if anim_type == 'fade_slide_up':
                    # 上滑淡入：从下方 slide_dist 像素处滑入
                    slide_d = flags_dict.get('slide_dist', SLIDE_UP_DIST)
                    if progress < 1.0:
                        cur_y = y_pos + int(slide_d * (1 - progress))
                
                elif anim_type == 'slide_left':
                    # 从左侧滑入
                    slide_d = flags_dict.get('slide_dist', SLIDE_DISTANCE)
                    if progress < 1.0:
                        cur_x = x_pos - int(slide_d * (1 - progress))
                
                elif anim_type == 'slide_right':
                    # 从右侧滑入
                    slide_d = flags_dict.get('slide_dist', SLIDE_DISTANCE)
                    if progress < 1.0:
                        cur_x = x_pos + int(slide_d * (1 - progress))
                
                elif anim_type == 'slide_top':
                    # 从上方滑入
                    slide_d = flags_dict.get('slide_dist', SLIDE_DISTANCE)
                    if progress < 1.0:
                        cur_y = y_pos - int(slide_d * (1 - progress))
                
                elif anim_type == 'zoom_in':
                    # 缩放入场：从 1.4 倍缩小到 1.0 + 淡入
                    if progress < 1.0:
                        scale = 1.4 - 0.4 * progress
                
                elif anim_type == 'rotate_in':
                    # 旋转入场：从 90 度旋转到 0 度 + 淡入
                    if progress < 1.0:
                        rotation = 90 * (1 - progress)
                
                elif anim_type == 'flip_in':
                    # 水平翻转入场：模拟 3D 翻转
                    if progress < 1.0:
                        # 用缩放模拟翻转：先变窄再恢复
                        flip_p = progress
                        scale_x = abs(math.cos(flip_p * math.pi))
                        if scale_x < 0.05:
                            scale_x = 0.05
                        scale = scale_x
                
                elif anim_type == 'elastic_in':
                    # 弹性入场：强过冲
                    if progress < 0.0:
                        scale = 0.5
                    elif progress < 0.5:
                        p = progress / 0.5
                        p = 1 - (1 - p) ** 2
                        scale = 0.5 + (1.15 - 0.5) * p
                    elif progress < 1.0:
                        p = (progress - 0.5) / 0.5
                        scale = 1.15 - 0.15 * p
                    else:
                        scale = 1.0
                
                elif anim_type == 'scale_bounce':
                    # 缩放弹入：从小放大 + 轻微过冲
                    bounce = flags_dict.get('bounce_amount', 0.06)
                    if progress < 0.0:
                        scale = 0.85
                    elif progress < 0.6:
                        # 快速放大
                        p = progress / 0.6
                        p = 1 - (1 - p) ** 2
                        scale = 0.85 + (1.0 + bounce - 0.85) * p
                    elif progress < 1.0:
                        # 回弹到正常大小
                        p = (progress - 0.6) / 0.4
                        p = 1 - (1 - p) ** 2
                        scale = (1.0 + bounce) - bounce * p
                    else:
                        scale = 1.0
                
                elif anim_type == 'card_slide_rot':
                    # 卡片斜向滑入 + 旋转 + 可选弹跳
                    rot_target = flags_dict.get('rotation', 0)
                    from_dir = flags_dict.get('from_dir', 'bottom_left')
                    has_bounce = flags_dict.get('bounce', False)
                    
                    # 起始位置（屏幕外）
                    if from_dir == 'bottom_left':
                        start_x = x_pos - 120
                        start_y = y_pos + 150
                    elif from_dir == 'right':
                        start_x = video_w - 20
                        start_y = y_pos + 60
                    elif from_dir == 'bottom':
                        start_x = x_pos
                        start_y = video_h - 20
                    else:
                        start_x = x_pos
                        start_y = y_pos + 150
                    
                    if progress < 1.0:
                        # ease-out
                        p = progress
                        cur_x = int(start_x + (x_pos - start_x) * p)
                        cur_y = int(start_y + (y_pos - start_y) * p)
                        rotation = rot_target * (1 - p) * 2  # 旋转从2倍回落到目标
                    elif has_bounce and progress < 1.2:
                        # 弹跳阶段（过冲 + 回弹）
                        bp = (progress - 1.0) / 0.2
                        if bp < 0.5:
                            bp2 = bp / 0.5
                            bp2 = 1 - (1 - bp2) ** 2
                            cur_y = y_pos + int(8 * bp2)
                            rotation = rot_target * (1 - bp2 * 0.3)
                        else:
                            bp2 = (bp - 0.5) / 0.5
                            bp2 = 1 - (1 - bp2) ** 2
                            cur_y = y_pos + int(8 * (1 - bp2))
                            rotation = rot_target * (bp2 * 0.3 + 0.7)
                    else:
                        rotation = rot_target
                        cur_y = y_pos
                
                elif anim_type == 'pop_fade':
                    # 弹出淡入：从小放大 + 淡入
                    sf = flags_dict.get('scale_from', 0.85)
                    if progress < 1.0:
                        scale = sf + (1.0 - sf) * progress

                # ===== 强调动效（入场完成后播放 EMPHASIS_DURATION 秒，然后静止）=====
                # 通过 flags 中的 emphasis_anim 字段触发
                emph_type = flags_dict.get('emphasis_anim', '')
                if progress >= 1.0 and emph_type:
                    emph_dur = flags_dict.get('emphasis_dur', EMPHASIS_DURATION)
                    emph_delay = 0.15  # 入场后稍微延迟再开始强调
                    emph_t = elapsed - ANIM_DURATION - emph_delay
                    if 0 < emph_t < emph_dur:
                        # 用衰减包络：开始强，逐渐减弱到 0
                        env = 1.0 - (emph_t / emph_dur)
                        env = env ** 1.5  # 加速衰减
                        phase = 2 * math.pi * flags_dict.get('emph_freq', 2.0) * emph_t

                        if emph_type == 'bounce_emph':
                            amp = flags_dict.get('emph_amp', 10)
                            cur_y = y_pos - int(abs(math.sin(phase)) * amp * env)

                        elif emph_type == 'pulse_emph':
                            amp = flags_dict.get('emph_amp', 0.06)
                            scale = 1.0 + amp * (0.5 + 0.5 * math.sin(phase)) * env

                        elif emph_type == 'shake_emph':
                            amp = flags_dict.get('emph_amp', 8)
                            cur_x = x_pos + int(math.sin(phase) ** 3 * amp * env)

                        elif emph_type == 'wiggle_emph':
                            amp = flags_dict.get('emph_amp', 3.0)
                            rotation = math.sin(phase) * amp * env

                        elif emph_type == 'highlight_emph':
                            # 高亮跳动：跳 + 脉冲 + 摆动组合
                            b_amp = flags_dict.get('emph_amp', 12)
                            p_amp = flags_dict.get('pulse_amp', 0.06)
                            w_amp = flags_dict.get('wiggle_amp', 2.0)
                            cur_y = y_pos - int(abs(math.sin(phase)) * b_amp * env)
                            scale = 1.0 + p_amp * (0.5 + 0.5 * math.sin(phase + math.pi / 4)) * env
                            rotation = math.sin(phase * 0.8) * w_amp * env

                # ===== 持续动效（入场完成后无限循环播放，不衰减）=====
                # 通过 flags 中的 idle_anim 字段触发，适用于几何图等需要"活着"的元素
                idle_type = flags_dict.get('idle_anim', '')
                if progress >= 1.0 and idle_type:
                    # 强调动效播放期间不叠加持续动效，强调结束后才开始持续动效
                    emph_dur = flags_dict.get('emphasis_dur', EMPHASIS_DURATION)
                    emph_delay = 0.15
                    emph_end_t = ANIM_DURATION + emph_delay + emph_dur
                    idle_t = elapsed - emph_end_t
                    if idle_t > 0:
                        if idle_type == 'pulse_idle':
                            # 缓慢脉冲缩放（呼吸感）
                            amp = flags_dict.get('idle_amp', 0.03)
                            freq = flags_dict.get('idle_freq', 0.5)
                            phase = 2 * math.pi * freq * idle_t
                            scale = 1.0 + amp * (0.5 + 0.5 * math.sin(phase))

                        elif idle_type == 'float_idle':
                            # 上下缓慢浮动
                            amp = flags_dict.get('idle_amp', 6)
                            freq = flags_dict.get('idle_freq', 0.4)
                            phase = 2 * math.pi * freq * idle_t
                            cur_y = y_pos + int(math.sin(phase) * amp)

                        elif idle_type == 'sway_idle':
                            # 轻微左右摆动
                            amp = flags_dict.get('idle_amp', 1.5)
                            freq = flags_dict.get('idle_freq', 0.33)
                            phase = 2 * math.pi * freq * idle_t
                            rotation = math.sin(phase) * amp

                        elif idle_type == 'breath_idle':
                            # 呼吸：脉冲缩放 + 上下浮动组合（最自然）
                            p_amp = flags_dict.get('idle_amp', 0.025)
                            f_amp = flags_dict.get('float_amp', 5)
                            p_freq = flags_dict.get('idle_freq', 0.5)
                            f_freq = flags_dict.get('float_freq', 0.4)
                            p_phase = 2 * math.pi * p_freq * idle_t
                            f_phase = 2 * math.pi * f_freq * idle_t
                            scale = 1.0 + p_amp * (0.5 + 0.5 * math.sin(p_phase))
                            cur_y = y_pos + int(math.sin(f_phase) * f_amp)

                # ===== 渲染帧 =====
                # 缩放和旋转
                if abs(scale - 1.0) > 0.001 or abs(rotation) > 0.01:
                    new_w = max(int(iw_img * scale), 1)
                    new_h = max(int(ih_img * scale), 1)
                    resized = pil_img.resize((new_w, new_h), Image.LANCZOS)
                    if abs(rotation) > 0.01:
                        resized = resized.rotate(rotation, resample=Image.BICUBIC,
                                                  expand=True, fillcolor=(0, 0, 0, 0))
                    rw, rh = resized.size
                    px = x_pos + (iw_img - rw) // 2
                    py = cur_y + (ih_img - rh) // 2
                    # 调整位置：用旋转/缩放后的图中心对齐目标位置
                    # 简化：用左上角 + 偏移
                    frame = Image.new('RGBA', (video_w, video_h), (0, 0, 0, 0))
                    if opacity < 0.999:
                        # 应用透明度
                        alpha = resized.split()[-1]
                        alpha = alpha.point(lambda a: int(a * opacity))
                        resized.putalpha(alpha)
                    frame.paste(resized, (px, py), resized)
                    return np.array(frame)
                else:
                    # 普通位置变化
                    frame = Image.new('RGBA', (video_w, video_h), (0, 0, 0, 0))
                    if opacity < 0.999:
                        alpha = pil_img.split()[-1]
                        alpha = alpha.point(lambda a: int(a * opacity))
                        tmp = pil_img.copy()
                        tmp.putalpha(alpha)
                        frame.paste(tmp, (cur_x, cur_y), tmp)
                    else:
                        frame.paste(pil_img, (cur_x, cur_y), pil_img)
                    return np.array(frame)
            
            return make_frame
        
        frame_func = make_clip(img, x, y, start_t, anim_type, flags, iw, ih)
        clip = VideoClip(frame_func, duration=total_duration)
        clips.append(clip)
    
    # ===== 合成 =====
    video = CompositeVideoClip(clips, size=(video_w, video_h))
    video = video.with_duration(total_duration)
    
    return video, elements

# ========== AI 配音 ==========
async def generate_audio_async(text, voice_name, output_path):
    """使用edge-tts生成语音"""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice_name)
    await communicate.save(output_path)

def generate_audio(text, voice_name, output_path):
    """优先 edge-tts；不可用时回退到 macOS 系统语音（离线）"""
    try:
        asyncio.run(generate_audio_async(text, voice_name, output_path))
        if os.path.getsize(output_path) > 0:
            return
    except Exception as e:
        print(f'    edge-tts 不可用（{type(e).__name__}），改用系统语音合成')
    _say_tts(text, output_path)

def _say_tts(text, output_path, rate=175):
    """macOS `say` 离线合成 → ffmpeg 转 mp3"""
    import subprocess, tempfile
    import imageio_ffmpeg
    aiff = tempfile.mktemp(suffix='.aiff')
    subprocess.run(['say', '-v', 'Tingting', '-r', str(rate), '-o', aiff, text], check=True)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, '-y', '-loglevel', 'error', '-i', aiff,
                    '-ar', '44100', '-ac', '1', '-b:a', '128k', output_path], check=True)
    os.remove(aiff)

# ========== 字幕生成 ==========
def split_narration_to_sentences(text):
    """把旁白拆分成短句（按句号、问号、感叹号、逗号拆分）"""
    # 先按强标点拆分
    import re
    # 保留标点符号在句子末尾
    sentences = re.split(r'([。！？!?])', text)
    
    # 把标点和前面的句子合并
    merged = []
    for i in range(0, len(sentences), 2):
        if i + 1 < len(sentences):
            s = sentences[i] + sentences[i+1]
        else:
            s = sentences[i]
        s = s.strip()
        if s:
            merged.append(s)
    
    # 如果句子太长（超过25字），再按逗号拆一下
    final = []
    for s in merged:
        if len(s) > 25 and ('，' in s or ',' in s):
            parts = re.split(r'([，,])', s)
            sub = []
            for j in range(0, len(parts), 2):
                if j + 1 < len(parts):
                    sub_s = parts[j] + parts[j+1]
                else:
                    sub_s = parts[j]
                sub_s = sub_s.strip()
                if sub_s:
                    sub.append(sub_s)
            # 太短的句子和前面合并
            combined = []
            for sub_s in sub:
                if combined and len(sub_s) < 6:
                    combined[-1] += sub_s
                else:
                    combined.append(sub_s)
            final.extend(combined)
        else:
            final.append(s)
    
    # 过滤掉太短的
    final = [s for s in final if len(s) >= 3]
    
    return final if final else [text]


def create_subtitle_clips(narration_text, audio_duration, video_w, video_h, width_ratio=0.78):
    """创建逐句字幕clips（一句一句出现、消失）"""
    from moviepy import vfx
    
    sentences = split_narration_to_sentences(narration_text)
    n = len(sentences)
    
    if n == 0:
        return None
    
    # 按字数比例分配时间
    total_chars = sum(len(s) for s in sentences)
    # 每句的时长（按字数分配，保留淡入淡出时间）
    fade_dur = 0.25
    min_dur = 1.0  # 每句最少1秒
    
    # 可用时间（去掉开头结尾的缓冲）
    buffer_start = 0.3
    buffer_end = 0.5
    available = audio_duration - buffer_start - buffer_end
    available = max(available, n * min_dur)
    
    # 计算每句时间
    durations = []
    for s in sentences:
        ratio = len(s) / total_chars
        dur = max(available * ratio, min_dur)
        durations.append(dur)
    
    # 归一化，确保总时间匹配
    total_dur = sum(durations)
    scale = available / total_dur
    durations = [d * scale for d in durations]
    
    # 生成每句字幕clip
    clips = []
    current_t = buffer_start
    
    for i, (sentence, dur) in enumerate(zip(sentences, durations)):
        sub_img = make_subtitle(sentence, width=int(video_w * width_ratio),
                                font_size=SUBTITLE_FONT_SIZE)
        sw, sh = sub_img.size
        
        sub_x = (video_w - sw) // 2
        sub_y = video_h - sh - 50  # 底部50px
        
        clip = ImageClip(np.array(sub_img))
        clip = clip.with_position((sub_x, sub_y))
        clip = clip.with_start(current_t)
        clip = clip.with_duration(dur)
        
        # 淡入淡出
        actual_fade = min(fade_dur, dur / 3)
        clip = clip.with_effects([
            vfx.FadeIn(actual_fade),
            vfx.FadeOut(actual_fade)
        ])
        
        clips.append(clip)
        current_t += dur
    
    return clips

# ========== 主函数 ==========
def main():
    work_dir = os.path.dirname(os.path.abspath(__file__))
    content_file = os.path.join(work_dir, 'content.txt')
    temp_dir = os.path.join(work_dir, 'temp_assets')
    output_file = os.path.join(work_dir, 'output.mp4')
    
    os.makedirs(temp_dir, exist_ok=True)
    
    print("=" * 60)
    print("  知识点讲解视频生成器 (PPT风格)")
    print("=" * 60)
    
    # 1. 读取内容
    print("\n[1/5] 读取内容配置...")
    global_config, sections = parse_content(content_file)
    print(f"  共找到 {len(sections)} 个知识点部分")
    
    voice_map = {
        '晓晓': 'zh-CN-XiaoxiaoNeural',
        '晓伊': 'zh-CN-XiaoyiNeural',
        '云健': 'zh-CN-YunjianNeural',
        '云希': 'zh-CN-YunxiNeural',
        '云扬': 'zh-CN-YunyangNeural',
    }
    voice_name = voice_map.get(global_config.get('配音音色', '云健'), 'zh-CN-YunjianNeural')
    
    # 2. 生成配音
    print(f"\n[2/5] 生成AI配音（{global_config.get('配音音色', '云健')}）...")
    audio_durations = []
    for i, sec in enumerate(sections):
        audio_path = os.path.join(temp_dir, f'audio_{i+1}.mp3')
        narration = sec['narration'].strip()
        if narration:
            print(f"  生成第 {i+1} 部分配音...")
            generate_audio(narration, voice_name, audio_path)
            audio_clip = AudioFileClip(audio_path)
            duration = audio_clip.duration
            audio_clip.close()
            audio_durations.append(duration)
            print(f"    时长: {duration:.1f}秒")
        else:
            audio_durations.append(5.0)
    
    # 3. 生成背景
    print("\n[3/5] 生成PPT风格背景...")
    size_str = global_config.get('视频尺寸', '1920x1080')
    video_w, video_h = map(int, size_str.split('x'))
    
    # 检查是否有自定义背景
    custom_bg = None
    for ext in ['png', 'jpg', 'jpeg']:
        bg_path = os.path.join(work_dir, f'background.{ext}')
        if os.path.exists(bg_path):
            custom_bg = Image.open(bg_path).convert('RGB').resize((video_w, video_h), Image.LANCZOS)
            print(f"  使用自定义背景: background.{ext}")
            break
    
    if custom_bg:
        bg_img = custom_bg
    else:
        bg_img = create_ppt_background(video_w, video_h)
        print("  生成PPT风格浅灰蓝背景")
    
    # 4. 生成每一页视频
    print("\n[4/5] 合成视频画面...")
    window_cfg = parse_window_config(global_config, work_dir)
    if window_cfg:
        print(f"  右下角通话小窗已开启（形象: {os.path.basename(window_cfg['avatar'])}，"
              f"口型: {'开' if window_cfg['lip_sync'] else '关'}）")
    sub_ratio = 0.56 if window_cfg else 0.78
    clips = []
    for i, (sec, audio_dur) in enumerate(zip(sections, audio_durations)):
        print(f"  处理第 {i+1} 部分...")
        clip, elems = create_ppt_section(sec, audio_dur, bg_img, video_w, video_h, window_cfg)
        
        # 添加字幕（逐句出现消失）
        narration = sec['narration'].strip()
        if narration:
            sub_clips = create_subtitle_clips(narration, audio_dur, video_w, video_h, sub_ratio)
            if sub_clips:
                all_clips = [clip] + sub_clips
                clip = CompositeVideoClip(all_clips, size=(video_w, video_h))
                clip = clip.with_duration(clip.duration)

        # 叠加右下角视频通话小窗（形象 + 背景 + 音频驱动口型）
        if window_cfg:
            audio_path = os.path.join(temp_dir, f'audio_{i+1}.mp3')
            win_clip, _ = create_avatar_window_clip(
                audio_path if window_cfg['lip_sync'] else None,
                clip.duration, video_w, video_h, window_cfg, intro=(i == 0))
            clip = CompositeVideoClip([clip, win_clip], size=(video_w, video_h))
            clip = clip.with_duration(clip.duration)

        
        # 添加音频
        audio_path = os.path.join(temp_dir, f'audio_{i+1}.mp3')
        if os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            clip = clip.with_audio(audio)
        
        clips.append(clip)
    
    # 5. 拼接所有部分
    print("\n[5/5] 拼接所有部分...")
    final_video = concatenate_videoclips(clips, method="compose")
    
    # 导出
    print(f"  导出视频到: {output_file}")
    final_video.write_videofile(
        output_file,
        fps=30,
        codec='libx264',
        audio_codec='aac',
        logger='bar'
    )
    
    print(f"\n{'=' * 60}")
    print(f"  ✅ 视频生成完成！")
    print(f"  输出文件: {output_file}")
    print(f"  总时长: {final_video.duration:.1f} 秒")
    print(f"{'=' * 60}")

if __name__ == '__main__':
    main()
