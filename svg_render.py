"""
轻量 SVG 渲染器（纯 PIL 实现，无系统依赖）
支持几何示意图常用的 SVG 元素：rect / circle / ellipse / line / polyline / polygon / path(基本) / text / g
可按任意目标尺寸栅格化，实现真正的矢量缩放效果。
"""
import math
import re
from PIL import Image, ImageDraw, ImageFont

# ========== 颜色解析 ==========
def parse_color(s, opacity=1.0):
    """解析 SVG 颜色字符串，返回 (r,g,b,a)"""
    if not s or s == 'none':
        return None
    s = s.strip()
    alpha = int(opacity * 255)
    if s.startswith('#'):
        h = s[1:]
        if len(h) == 3:
            h = ''.join(c*2 for c in h)
        if len(h) == 6:
            r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
            return (r, g, b, alpha)
        if len(h) == 8:
            r, g, b, a = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), int(h[6:8],16)
            return (r, g, b, int(a * opacity))
    # rgb(r,g,b) / rgba(r,g,b,a)
    m = re.match(r'rgba?\(([^)]+)\)', s)
    if m:
        parts = [p.strip() for p in m.group(1).split(',')]
        r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
        a = int(float(parts[3]) * 255) if len(parts) > 3 else alpha
        return (r, g, b, a)
    # 命名颜色（常用）
    named = {'black':(0,0,0),'white':(255,255,255),'red':(230,70,70),
             'blue':(6,90,130),'green':(40,167,69),'gray':(128,128,128),
             'orange':(245,166,35),'none':None}
    if s in named:
        c = named[s]
        return (c[0],c[1],c[2],alpha) if c else None
    return (0, 0, 0, alpha)


def get_attr(attrs, name, default=''):
    """获取属性（支持带命名空间的属性名）"""
    for k, v in attrs.items():
        if k == name or k.endswith(':' + name):
            return v
    return default


# ========== 变换矩阵 ==========
class Transform:
    """2D 仿射变换矩阵 [a b c d e f] 对应 x'=a*x+c*y+e, y'=b*x+d*y+f"""
    def __init__(self, a=1, b=0, c=0, d=1, e=0, f=0):
        self.m = [a, b, c, d, e, f]

    def apply(self, x, y):
        a, b, c, d, e, f = self.m
        return (a*x + c*y + e, b*x + d*y + f)

    def multiply(self, other):
        a1,b1,c1,d1,e1,f1 = self.m
        a2,b2,c2,d2,e2,f2 = other.m
        return Transform(
            a1*a2 + c1*b2, b1*a2 + d1*b2,
            a1*c2 + c1*d2, b1*c2 + d1*d2,
            a1*e2 + c1*f2 + e1, b1*e2 + d1*f2 + f1
        )

    @staticmethod
    def parse(s):
        """解析 transform 字符串，返回 Transform"""
        t = Transform()
        if not s:
            return t
        for m in re.finditer(r'(\w+)\(([^)]*)\)', s):
            func = m.group(1)
            args = [float(x) for x in re.findall(r'-?\d+\.?\d*', m.group(2))]
            if func == 'translate':
                tx, ty = (args[0], args[1] if len(args) > 1 else 0)
                t = t.multiply(Transform(1,0,0,1,tx,ty))
            elif func == 'rotate':
                a = math.radians(args[0])
                cx, cy = (args[1], args[2]) if len(args) > 2 else (0, 0)
                cos_a, sin_a = math.cos(a), math.sin(a)
                rot = Transform(cos_a, sin_a, -sin_a, cos_a, 0, 0)
                if cx or cy:
                    t = t.multiply(Transform(1,0,0,1,cx,cy))
                t = t.multiply(rot)
                if cx or cy:
                    t = t.multiply(Transform(1,0,0,1,-cx,-cy))
            elif func == 'scale':
                sx, sy = (args[0], args[1] if len(args) > 1 else args[0])
                t = t.multiply(Transform(sx,0,0,sy,0,0))
        return t


# ========== 路径解析 ==========
def parse_path(d):
    """解析 SVG path 的 d 属性，返回 [(command, [(x,y),...]), ...]"""
    commands = []
    i = 0
    n = len(d)
    while i < n:
        while i < n and d[i] in ' \t\n\r,':
            i += 1
        if i >= n:
            break
        cmd = d[i]
        i += 1
        nums = []
        while i < n:
            while i < n and d[i] in ' \t\n\r,':
                i += 1
            if i < n and (d[i].isalpha()):
                break
            # 读取一个数
            sign = 1
            if i < n and d[i] in '+-':
                if d[i] == '-':
                    sign = -1
                i += 1
            num = ''
            while i < n and (d[i].isdigit() or d[i] == '.'):
                num += d[i]
                i += 1
            # 科学计数法
            if i < n and d[i] in 'eE':
                num += d[i]
                i += 1
                if i < n and d[i] in '+-':
                    num += d[i]
                    i += 1
                while i < n and d[i].isdigit():
                    num += d[i]
                    i += 1
            if num:
                nums.append(sign * float(num))
            else:
                break
        commands.append((cmd, nums))
    return commands


def path_to_polygons(d, transform):
    """将 path 转换为多边形点序列列表（支持 M/L/H/V/Z/C 简化处理）"""
    cmds = parse_path(d)
    polygons = []
    current = []
    start = (0, 0)
    pos = (0, 0)
    last_ctrl = None

    for cmd, nums in cmds:
        if cmd == 'M':
            if current:
                polygons.append(current)
            current = []
            x, y = nums[0], nums[1]
            pos = (x, y)
            start = pos
            current.append(transform.apply(x, y))
            for k in range(2, len(nums), 2):
                x, y = nums[k], nums[k+1]
                pos = (x, y)
                current.append(transform.apply(x, y))
        elif cmd == 'm':
            if current:
                polygons.append(current)
            current = []
            x, y = pos[0] + nums[0], pos[1] + nums[1]
            pos = (x, y)
            start = pos
            current.append(transform.apply(x, y))
            for k in range(2, len(nums), 2):
                x, y = pos[0] + nums[k], pos[1] + nums[k+1]
                pos = (x, y)
                current.append(transform.apply(x, y))
        elif cmd == 'L':
            for k in range(0, len(nums), 2):
                x, y = nums[k], nums[k+1]
                pos = (x, y)
                current.append(transform.apply(x, y))
        elif cmd == 'l':
            for k in range(0, len(nums), 2):
                x, y = pos[0] + nums[k], pos[1] + nums[k+1]
                pos = (x, y)
                current.append(transform.apply(x, y))
        elif cmd == 'H':
            for k in range(0, len(nums)):
                x = nums[k]
                pos = (x, pos[1])
                current.append(transform.apply(x, pos[1]))
        elif cmd == 'h':
            for k in range(0, len(nums)):
                x = pos[0] + nums[k]
                pos = (x, pos[1])
                current.append(transform.apply(x, pos[1]))
        elif cmd == 'V':
            for k in range(0, len(nums)):
                y = nums[k]
                pos = (pos[0], y)
                current.append(transform.apply(pos[0], y))
        elif cmd == 'v':
            for k in range(0, len(nums)):
                y = pos[1] + nums[k]
                pos = (pos[0], y)
                current.append(transform.apply(pos[0], y))
        elif cmd in ('Z', 'z'):
            if current:
                current.append(transform.apply(start[0], start[1]))
                polygons.append(current)
                current = []
            pos = start
        elif cmd == 'C':
            # 三次贝塞尔，用多点近似
            for k in range(0, len(nums), 6):
                c1x, c1y = nums[k], nums[k+1]
                c2x, c2y = nums[k+2], nums[k+3]
                ex, ey = nums[k+4], nums[k+5]
                steps = 12
                sx, sy = pos
                for s in range(1, steps+1):
                    t = s / steps
                    x = (1-t)**3*sx + 3*(1-t)**2*t*c1x + 3*(1-t)*t**2*c2x + t**3*ex
                    y = (1-t)**3*sy + 3*(1-t)**2*t*c1y + 3*(1-t)*t**2*c2y + t**3*ey
                    current.append(transform.apply(x, y))
                pos = (ex, ey)
        elif cmd == 'c':
            for k in range(0, len(nums), 6):
                c1x, c1y = pos[0]+nums[k], pos[1]+nums[k+1]
                c2x, c2y = pos[0]+nums[k+2], pos[1]+nums[k+3]
                ex, ey = pos[0]+nums[k+4], pos[1]+nums[k+5]
                steps = 12
                sx, sy = pos
                for s in range(1, steps+1):
                    t = s / steps
                    x = (1-t)**3*sx + 3*(1-t)**2*t*c1x + 3*(1-t)*t**2*c2x + t**3*ex
                    y = (1-t)**3*sy + 3*(1-t)**2*t*c1y + 3*(1-t)*t**2*c2y + t**3*ey
                    current.append(transform.apply(x, y))
                pos = (ex, ey)
    if current:
        polygons.append(current)
    return polygons


# ========== 主渲染函数 ==========
def render_svg(svg_string, target_w, target_h, scale=1.0):
    """
    将 SVG 字符串渲染为 PIL Image（RGBA）。
    target_w, target_h: 目标画布尺寸（像素）
    scale: 缩放倍数（>1 用于超采样，保证动画缩放时清晰）
    返回: PIL.Image (RGBA)，尺寸为 target_w x target_h
    """
    import xml.etree.ElementTree as ET

    # 解析 SVG
    root = ET.fromstring(svg_string)
    svg_ns = ''
    if root.tag.startswith('{'):
        svg_ns = root.tag.split('}')[0] + '}'

    # 获取原始尺寸和 viewBox
    svg_w = float(get_attr(root.attrib, 'width', '0').replace('px','') or '0')
    svg_h = float(get_attr(root.attrib, 'height', '0').replace('px','') or '0')
    viewBox = get_attr(root.attrib, 'viewBox', '')
    if viewBox:
        parts = [float(x) for x in viewBox.split()]
        vbx, vby, vbw, vbh = parts
        if svg_w == 0:
            svg_w = vbw
        if svg_h == 0:
            svg_h = vbh
    else:
        vbx, vby, vbw, vbh = 0, 0, svg_w, svg_h

    # 计算缩放：将 viewBox 映射到 target_w x target_h
    scale_x = target_w / vbw
    scale_y = target_h / vbh
    base_scale = min(scale_x, scale_y)
    # 居中偏移
    offset_x = (target_w - vbw * base_scale) / 2 - vbx * base_scale
    offset_y = (target_h - vbh * base_scale) / 2 - vby * base_scale

    base_transform = Transform(base_scale, 0, 0, base_scale, offset_x, offset_y)

    # 创建画布
    img = Image.new('RGBA', (int(target_w), int(target_h)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 字体加载
    def get_font(size):
        try:
            return ImageFont.truetype("/System/Library/Fonts/Supplemental/Songti.ttc", int(size), index=0)
        except:
            return ImageFont.load_default()

    def draw_element(elem, transform, inherited_opacity=1.0):
        tag = elem.tag.replace(svg_ns, '')
        attrs = elem.attrib

        # 当前变换
        t_str = get_attr(attrs, 'transform', '')
        cur_t = transform.multiply(Transform.parse(t_str)) if t_str else transform

        opacity = float(get_attr(attrs, 'opacity', '1') or '1') * inherited_opacity
        fill_opacity = float(get_attr(attrs, 'fill-opacity', '1') or '1')
        stroke_opacity = float(get_attr(attrs, 'stroke-opacity', '1') or '1')
        fill = parse_color(get_attr(attrs, 'fill', 'black'), fill_opacity * opacity)
        stroke = parse_color(get_attr(attrs, 'stroke', 'none'), stroke_opacity * opacity)
        sw = float(get_attr(attrs, 'stroke-width', '1') or '1') * base_scale

        if tag == 'rect':
            x = float(get_attr(attrs, 'x', '0'))
            y = float(get_attr(attrs, 'y', '0'))
            w = float(get_attr(attrs, 'width', '0'))
            h = float(get_attr(attrs, 'height', '0'))
            rx = float(get_attr(attrs, 'rx', '0'))
            xy = cur_t.apply(x, y)
            xy2 = cur_t.apply(x+w, y+h)
            box = [xy[0], xy[1], xy2[0], xy2[1]]
            if fill:
                draw.rounded_rectangle(box, radius=rx*base_scale, fill=fill)
            if stroke:
                draw.rounded_rectangle(box, radius=rx*base_scale, outline=stroke, width=max(1,int(sw)))

        elif tag == 'circle':
            cx = float(get_attr(attrs, 'cx', '0'))
            cy = float(get_attr(attrs, 'cy', '0'))
            r = float(get_attr(attrs, 'r', '0'))
            c = cur_t.apply(cx, cy)
            rr = r * base_scale
            box = [c[0]-rr, c[1]-rr, c[0]+rr, c[1]+rr]
            if fill:
                draw.ellipse(box, fill=fill)
            if stroke:
                draw.ellipse(box, outline=stroke, width=max(1,int(sw)))

        elif tag == 'ellipse':
            cx = float(get_attr(attrs, 'cx', '0'))
            cy = float(get_attr(attrs, 'cy', '0'))
            rx = float(get_attr(attrs, 'rx', '0'))
            ry = float(get_attr(attrs, 'ry', '0'))
            c = cur_t.apply(cx, cy)
            rx2 = rx * base_scale
            ry2 = ry * base_scale
            box = [c[0]-rx2, c[1]-ry2, c[0]+rx2, c[1]+ry2]
            if fill:
                draw.ellipse(box, fill=fill)
            if stroke:
                draw.ellipse(box, outline=stroke, width=max(1,int(sw)))

        elif tag == 'line':
            x1 = float(get_attr(attrs, 'x1', '0'))
            y1 = float(get_attr(attrs, 'y1', '0'))
            x2 = float(get_attr(attrs, 'x2', '0'))
            y2 = float(get_attr(attrs, 'y2', '0'))
            p1 = cur_t.apply(x1, y1)
            p2 = cur_t.apply(x2, y2)
            if stroke:
                draw.line([p1, p2], fill=stroke, width=max(1,int(sw)))

        elif tag in ('polyline', 'polygon'):
            points_str = get_attr(attrs, 'points', '')
            nums = [float(x) for x in re.findall(r'-?\d+\.?\d*', points_str)]
            pts = []
            for k in range(0, len(nums), 2):
                x, y = nums[k], nums[k+1]
                pts.append(cur_t.apply(x, y))
            if len(pts) >= 2:
                if tag == 'polygon' and fill:
                    draw.polygon(pts, fill=fill)
                if stroke:
                    draw.line(pts + ([pts[0]] if tag == 'polygon' else []),
                              fill=stroke, width=max(1,int(sw)))

        elif tag == 'path':
            d = get_attr(attrs, 'd', '')
            polys = path_to_polygons(d, cur_t)
            for poly in polys:
                if len(poly) >= 2:
                    if fill:
                        draw.polygon(poly, fill=fill)
                    if stroke:
                        draw.line(poly, fill=stroke, width=max(1,int(sw)))

        elif tag == 'text':
            x = float(get_attr(attrs, 'x', '0'))
            y = float(get_attr(attrs, 'y', '0'))
            font_size = float(get_attr(attrs, 'font-size', '16') or '16') * base_scale
            text_anchor = get_attr(attrs, 'text-anchor', 'start')
            text_color = fill if fill else (0, 0, 0, int(opacity*255))
            text = elem.text or ''
            # 处理 tspan
            for child in elem:
                if child.tag.replace(svg_ns, '') == 'tspan' and child.text:
                    text += child.text
            if text.strip():
                font = get_font(font_size)
                px, py = cur_t.apply(x, y)
                bbox = draw.textbbox((0, 0), text, font=font)
                tw = bbox[2] - bbox[0]
                if text_anchor == 'middle':
                    px -= tw / 2
                elif text_anchor == 'end':
                    px -= tw
                draw.text((px, py - font_size*0.8), text, font=font, fill=text_color)

        elif tag == 'g':
            for child in elem:
                draw_element(child, cur_t, opacity)

        # 递归子元素（非 g 的容器也处理）
        if tag not in ('g', 'text'):
            for child in elem:
                draw_element(child, cur_t, opacity)

    # 渲染根元素的所有子节点
    for child in root:
        draw_element(child, base_transform)

    return img


def load_svg_file(filepath, target_w, target_h):
    """从文件加载 SVG 并渲染为 PIL Image"""
    with open(filepath, 'r', encoding='utf-8') as f:
        svg_str = f.read()
    return render_svg(svg_str, target_w, target_h)
