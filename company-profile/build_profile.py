#!/usr/bin/env python3
"""
Rebuild pages 16 & 17 of the Al-Thuraiya company profile as
DRESSING ROOM and KITCHEN pages, and swap the back-cover photo.

The original page furniture (top striped band, side logos, footer bar with the
page number, page background) is kept by overlaying onto the untouched source
pages -- only the body area and the centre sub-brand logo are replaced.
"""
import io, os
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader, PdfWriter
import arabic_reshaper
from bidi.algorithm import get_display

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get('PROFILE_SRC', os.path.join(HERE, 'final_profile_2.pdf'))
OUT = os.path.join(HERE, 'althuraiya_profile_updated.pdf')

PW, PH = 595.276, 841.89

# ---------------------------------------------------------------- brand ----
ORANGE = HexColor('#F05A2B')
SLATE  = HexColor('#556467')
MAROON = HexColor('#A32B37')
GREY   = HexColor('#595A5C')
LGREY  = HexColor('#F2F2F2')
MGREY  = HexColor('#BFBFBF')

# geometry lifted from the source pages (top-down points)
HEADER_BOTTOM = 88.0      # logo row ends 83.5
FOOTER_TOP    = 800.0     # footer bar starts 804.0
BAND_BOTTOM   = 20.0      # striped band ends 16.6
CENTRE_LOGO   = (238.0, 22.0, 333.0, 86.0)   # x0, ytop0, x1, ytop1
ML, MR = 38.0, 557.0      # content margins matching p17 swatch strip
CW = MR - ML

NOTO = '/usr/share/fonts/truetype/noto'
pdfmetrics.registerFont(TTFont('L',   f'{NOTO}/NotoSans-Regular.ttf'))
pdfmetrics.registerFont(TTFont('LB',  f'{NOTO}/NotoSans-Bold.ttf'))
pdfmetrics.registerFont(TTFont('A',   f'{NOTO}/NotoSansArabic-Regular.ttf'))
pdfmetrics.registerFont(TTFont('AB',  f'{NOTO}/NotoSansArabic-Bold.ttf'))

# Noto Sans Arabic carries no Latin letters, so "PVC"/"UPVC" sitting inside an
# Arabic sentence would render as blanks. Latin runs are therefore measured and
# drawn with the Latin face, the rest with the Arabic face.
LATIN_FOR = {'A': 'L', 'AB': 'LB'}


def _runs(display_text):
    """Split a display-ordered string into (is_latin, chunk) runs."""
    out, cur, cur_lat = [], '', None
    for ch in display_text:
        lat = ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')
        if cur_lat is None or lat == cur_lat:
            cur += ch; cur_lat = lat
        else:
            out.append((cur_lat, cur)); cur, cur_lat = ch, lat
    if cur:
        out.append((cur_lat, cur))
    return out


def ar_width(display_text, font, size):
    tot = 0.0
    for lat, chunk in _runs(display_text):
        tot += pdfmetrics.stringWidth(chunk, LATIN_FOR[font] if lat else font, size)
    return tot


def draw_ar(c, x, y, display_text, font, size):
    """Draw a display-ordered Arabic line left-to-right from x, run by run."""
    for lat, chunk in _runs(display_text):
        f = LATIN_FOR[font] if lat else font
        c.setFont(f, size)
        c.drawString(x, y, chunk)
        x += pdfmetrics.stringWidth(chunk, f, size)


def draw_ar_right(c, x_right, y, display_text, font, size):
    draw_ar(c, x_right - ar_width(display_text, font, size), y, display_text, font, size)


def draw_ar_centre(c, x_mid, y, display_text, font, size):
    draw_ar(c, x_mid - ar_width(display_text, font, size) / 2, y, display_text, font, size)


def Y(td):
    """top-down points -> PDF user space"""
    return PH - td


def shape(txt):
    return get_display(arabic_reshaper.reshape(txt))


def wrap_ar(text, font, size, maxw):
    """Wrap logical Arabic text -> display-ordered lines, None marks a para break."""
    out = []
    for para in text.strip().split('\n'):
        if out:
            out.append(None)
        words, cur = para.split(), []
        for w in words:
            trial = cur + [w]
            if ar_width(shape(' '.join(trial)), font, size) <= maxw or not cur:
                cur = trial
            else:
                out.append(shape(' '.join(cur))); cur = [w]
        if cur:
            out.append(shape(' '.join(cur)))
    return out


def wrap_en(text, font, size, maxw):
    out = []
    for para in text.strip().split('\n'):
        if out:
            out.append(None)
        words, cur = para.split(), []
        for w in words:
            trial = cur + [w]
            if pdfmetrics.stringWidth(' '.join(trial), font, size) <= maxw or not cur:
                cur = trial
            else:
                out.append(' '.join(cur)); cur = [w]
        if cur:
            out.append(' '.join(cur))
    return out


def img_size(path):
    ir = ImageReader(path)
    return ir.getSize()


# ------------------------------------------------------------- drawing ----
def clear_body(c):
    """White out the body and the old centre sub-brand logo."""
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, Y(FOOTER_TOP), PW, FOOTER_TOP - HEADER_BOTTOM, stroke=0, fill=1)
    x0, t0, x1, t1 = CENTRE_LOGO
    c.rect(x0, Y(t1), x1 - x0, t1 - t0, stroke=0, fill=1)


def centre_logo(c, path, slot_h=52.0, top=26.0):
    w, h = img_size(path)
    ar = w / h
    hh = slot_h
    ww = hh * ar
    if ww > 88.0:                      # keep inside the header slot width
        ww = 88.0; hh = ww / ar
    x = (CENTRE_LOGO[0] + CENTRE_LOGO[2]) / 2 - ww / 2
    ytop = top + (slot_h - hh) / 2
    c.drawImage(path, x, Y(ytop + hh), ww, hh, mask=None)


def watermark(c, path, width=330.0, centre_td=430.0):
    w, h = img_size(path)
    ww = width; hh = ww * h / w
    c.drawImage(path, PW / 2 - ww / 2, Y(centre_td + hh / 2), ww, hh, mask=None)


def title_block(c, en, ar, td=112.0):
    c.setFont('LB', 15)
    c.setFillColor(ORANGE)
    c.drawCentredString(PW / 2, Y(td), en)
    draw_ar_centre(c, PW / 2, Y(td + 17), shape(ar), 'AB', 12)
    tw = max(pdfmetrics.stringWidth(en, 'LB', 15),
             ar_width(shape(ar), 'AB', 12)) + 46
    c.setFillColor(ORANGE)
    c.rect(PW / 2 - tw / 2, Y(td + 25), tw, 2.0, stroke=0, fill=1)


def para_ar(c, text, td, size=8.2, lead=12.6, gap=4.0, colour=SLATE, x_right=MR, maxw=CW):
    c.setFillColor(colour)
    y = td
    for ln in wrap_ar(text, 'A', size, maxw):
        if ln is None:
            y += gap; continue
        draw_ar_right(c, x_right, Y(y), ln, 'A', size)
        y += lead
    return y


def para_en(c, text, td, size=8.2, lead=10.4, gap=4.0, colour=GREY, x_left=ML, maxw=CW):
    c.setFont('L', size); c.setFillColor(colour)
    y = td
    for ln in wrap_en(text, 'L', size, maxw):
        if ln is None:
            y += gap; continue
        c.drawString(x_left, Y(y), ln)
        y += lead
    return y


def photo_slot(c, x, td, w, h, label, sub):
    """Branded placeholder awaiting a supplied photograph."""
    c.setFillColor(LGREY); c.setStrokeColor(MGREY); c.setLineWidth(0.7)
    c.setDash(3, 2)
    c.rect(x, Y(td + h), w, h, stroke=1, fill=1)
    c.setDash()
    # corner ticks in brand orange
    c.setStrokeColor(ORANGE); c.setLineWidth(1.4); t = 9
    for cx, cy, dx, dy in ((x, td, 1, 1), (x + w, td, -1, 1),
                           (x, td + h, 1, -1), (x + w, td + h, -1, -1)):
        c.line(cx, Y(cy), cx + dx * t, Y(cy))
        c.line(cx, Y(cy), cx, Y(cy + dy * t))
    c.setFillColor(ORANGE); c.setFont('LB', 7.5)
    c.drawCentredString(x + w / 2, Y(td + h / 2 - 1), label)
    c.setFillColor(MGREY); c.setFont('L', 6.2)
    c.drawCentredString(x + w / 2, Y(td + h / 2 + 9), sub)


def bullets(c, items, td, size=7.8, lead=11.6):
    """One full-width row per item: English left, Arabic right."""
    for i, (en, ar) in enumerate(items):
        y = td + i * lead
        c.setFillColor(ORANGE)
        c.circle(ML + 2.2, Y(y) + 2.4, 1.7, stroke=0, fill=1)
        c.setFillColor(GREY); c.setFont('L', size)
        c.drawString(ML + 8, Y(y), en)
        c.setFillColor(SLATE)
        draw_ar_right(c, MR, Y(y), shape(ar), 'A', size)
    return td + len(items) * lead


def strip(c, path, td, width=None, x=None):
    w, h = img_size(path)
    ww = width if width else CW
    hh = ww * h / w
    xx = x if x is not None else ML + (CW - ww) / 2
    c.drawImage(path, xx, Y(td + hh), ww, hh, mask=None)
    return td + hh


# ---------------------------------------------------------------- copy ----
AR_DRESS = """يصنّع مصنع الثريا للخزائن والمطابخ خزائن الملابس وغرف الملابس حسب المقاس في مصنعه بالدوحة، باستخدام ألواح مكسوة برقائق PVC وبنفس معايير الجودة المطبّقة على جميع منتجاتنا.
يبدأ كل مشروع بزيارة الموقع وأخذ المقاسات، ثم تُرسم الوحدات وتُقص وتُجمّع بأبعاد الغرفة تماماً، بحيث يُستفاد من ارتفاع السقف والزوايا والتجاويف بالكامل بدلاً من ملئها بوحدات جاهزة.
تتوفر التصاميم بأبواب مفصلية أو أبواب سحّاب أو غرف ملابس مفتوحة، مع تجهيزات داخلية تُحدَّد حسب الاستخدام: قضبان تعليق، ورفوف قابلة للتعديل، وأدراج، ورفوف أحذية، ومرايا، وإضاءة.
الأسطح مقاومة للرطوبة وثابتة اللون وسهلة التنظيف، وتتوفر بكامل مجموعة الألوان الموضحة في الصفحة المقابلة."""

EN_DRESS = """Al-Thuraiya Wardrobes and Kitchen manufactures made-to-measure wardrobes and dressing rooms in the same Doha factory that produces our UPVC profiles, using PVC-foil laminated panels and the same quality control applied across our range.
Every project starts with a site survey. Units are then drawn, cut and assembled to the exact dimensions of the room, so ceiling heights, corners and recesses are used fully instead of being filled with standard boxes.
Hinged-door, sliding-door and open walk-in layouts are all available. Interiors are specified around how the space will be used - hanging rails, adjustable shelving, drawer banks, shoe racks, mirrors and lighting.
Surfaces are moisture resistant, colour stable and easy to clean, and are supplied in the full range of finishes shown opposite."""

DRESS_BULLETS = [
    ("Made to measure, no standard sizes",  "تصنيع حسب المقاس دون مقاسات جاهزة"),
    ("Manufactured in our own Doha factory", "تصنيع في مصنعنا بالدوحة"),
    ("Moisture-resistant laminated panels",  "ألواح مكسوة مقاومة للرطوبة"),
    ("Hinged, sliding and walk-in layouts",  "أبواب مفصلية وسحّاب وغرف مفتوحة"),
    ("Full range of wood and plain finishes","مجموعة كاملة من الألوان والأخشاب"),
    ("Survey, manufacture and installation", "القياس والتصنيع والتركيب"),
]

AR_KITCHEN = """تُصنع المطابخ على المبدأ نفسه المتّبع في الخزائن: قياس على الموقع، وتصنيع محلي، وتشطيب بمواد مختارة لتناسب مناخ قطر.
تُنتج الهياكل والواجهات من ألواح مكسوة برقائق PVC تتحمل الرطوبة والبخار والتنظيف المتكرر، مع حواف محكمة الإغلاق تمنع وصول الماء إلى قلب اللوح.
تُرسم الوحدات السفلية والعلوية والخزائن الطويلة والجزر حسب مخططك، وتُختار أسطح العمل والمقابض والمفصلات وأنظمة الأدراج معك من مورّدينا المحليين والعالميين.
يتولى فريق واحد القياس والرسم والتصنيع والتوصيل والتركيب، لتبقى مسؤولية المطبخ المنجز في جهة واحدة."""

EN_KITCHEN = """Kitchens are built on the same principle as our wardrobes: measured on site, manufactured locally, and finished in materials chosen for Qatar's climate.
Carcasses and fronts are produced from PVC-foil laminated panels that stand up to moisture, steam and repeated cleaning, with sealed edges that keep water out of the core of the board.
Base units, wall units, tall units and islands are drawn to your plan. Worktops, handles, hinges and drawer systems are selected together with you from our local and international suppliers.
Survey, drawings, manufacture, delivery and installation are handled by one team, so responsibility for the finished kitchen stays in one place."""


# ------------------------------------------------------------- page 16 ----
def page_dressing(c):
    clear_body(c)
    watermark(c, f'{HERE}/assets/logo_watermark.png', width=300, centre_td=352)
    centre_logo(c, f'{HERE}/assets/logo_wardrobes_kitchen.png')
    title_block(c, 'DRESSING ROOM', 'غرف الملابس')

    y = para_ar(c, AR_DRESS, 156)
    y = para_en(c, EN_DRESS, y + 8)

    y = strip(c, f'{HERE}/assets/strip_icons.png', y + 16, width=430)

    # 2 x 2 photo grid
    gy = y + 18
    gw = (CW - 12) / 2
    gh = 126.0
    slots = [('DRESSING ROOM 01', 'walk-in / corner layout'),
             ('DRESSING ROOM 02', 'sliding-door wardrobe'),
             ('DRESSING ROOM 03', 'internal fittings detail'),
             ('DRESSING ROOM 04', 'hinged-door wardrobe')]
    for i, (lab, sub) in enumerate(slots):
        col, row = i % 2, i // 2
        photo_slot(c, ML + col * (gw + 12), gy + row * (gh + 12), gw, gh, lab, sub)

    by = gy + 2 * (gh + 12) + 12
    bullets(c, DRESS_BULLETS, by)


# ------------------------------------------------------------- page 17 ----
def page_kitchen(c):
    clear_body(c)
    watermark(c, f'{HERE}/assets/logo_watermark.png', width=300, centre_td=560)
    centre_logo(c, f'{HERE}/assets/logo_wardrobes_kitchen.png')
    title_block(c, 'KITCHEN', 'المطابخ')

    y = para_ar(c, AR_KITCHEN, 156)
    y = para_en(c, EN_KITCHEN, y + 8)

    # hero slot
    hy = y + 16
    photo_slot(c, ML, hy, CW, 196, 'KITCHEN 01', 'full kitchen, wide view')

    # three across
    ry = hy + 196 + 12
    sw = (CW - 24) / 3
    for i, (lab, sub) in enumerate([('KITCHEN 02', 'island / worktop'),
                                    ('KITCHEN 03', 'tall & wall units'),
                                    ('KITCHEN 04', 'drawer / door detail')]):
        photo_slot(c, ML + i * (sw + 12), ry, sw, 128, lab, sub)

    # colour range
    cy = ry + 128 + 20
    c.setFillColor(ORANGE); c.setFont('LB', 8.5)
    c.drawString(ML, Y(cy), 'ENJOY WITH CHOICE COLOR')
    draw_ar_right(c, MR, Y(cy), shape('استمتع باختيارك اللون'), 'AB', 8.5)
    c.setFillColor(GREY); c.setFont('L', 6.8)
    c.drawCentredString(PW / 2, Y(cy), 'the same finishes are available across wardrobes and kitchens')
    strip(c, f'{HERE}/assets/strip_swatch.png', cy + 8)


# ------------------------------------------------------------- page 20 ----
def page_backcover(c):
    # inner area of the existing navy photo frame, measured off the source page
    x0, x1 = 192.72, 402.48
    t0, t1 = 455.04, 652.32
    c.drawImage(f'{HERE}/assets/backcover_photo.png', x0, Y(t1), x1 - x0, t1 - t0, mask=None)


# ---------------------------------------------------------------- build ----
def overlay(fn):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PW, PH))
    fn(c)
    c.showPage(); c.save(); buf.seek(0)
    return PdfReader(buf).pages[0]


def main():
    reader = PdfReader(SRC)
    writer = PdfWriter()
    jobs = {15: page_dressing, 16: page_kitchen, 19: page_backcover}  # 0-based
    for i, page in enumerate(reader.pages):
        if i in jobs:
            page.merge_page(overlay(jobs[i]))
        writer.add_page(page)
    with open(OUT, 'wb') as f:
        writer.write(f)
    print('wrote', OUT, os.path.getsize(OUT), 'bytes,', len(writer.pages), 'pages')


if __name__ == '__main__':
    main()
