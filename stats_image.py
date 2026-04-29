from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

BG = (20, 23, 36)
CARD = (37, 42, 61)
CARD_BORDER = (58, 64, 85)
HEADER_BG = (49, 46, 129)
TEXT = (240, 242, 248)
MUTED = (155, 163, 184)
ACCENT = (129, 140, 248)
GREEN = (74, 222, 128)
RED = (248, 113, 113)
BLUE = (96, 165, 250)
YELLOW = (250, 204, 21)

WIDTH = 900
PAD = 30
CARD_GAP = 16
CARD_W = (WIDTH - PAD * 2 - CARD_GAP) // 2
CARD_H = 290


def _font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def _text_w(draw, text, font):
    return draw.textbbox((0, 0), text, font=font)[2]


def _group_stats(rows):
    n = len(rows)
    if n == 0:
        return None
    wins = sum(1 for r in rows if r[2] == "Выигрыш")
    losses = sum(1 for r in rows if r[2] == "Проигрыш")
    returns = sum(1 for r in rows if r[2] == "Возврат")
    pending = sum(1 for r in rows if r[2] is None)
    total_amount = sum(r[0] for r in rows)
    avg_amount = total_amount / n
    avg_odds = sum(r[1] for r in rows) / n
    decided = wins + losses + returns
    win_pct = (wins / decided * 100) if decided > 0 else 0
    decided_amount = sum(r[0] for r in rows if r[2] is not None)
    decided_payout = sum((r[3] or 0) for r in rows if r[2] is not None)
    profit = decided_payout - decided_amount
    roi = (profit / decided_amount * 100) if decided_amount > 0 else 0
    return {
        "n": n, "wins": wins, "losses": losses, "returns": returns, "pending": pending,
        "avg_odds": avg_odds, "total_amount": total_amount, "avg_amount": avg_amount,
        "win_pct": win_pct, "profit": profit, "roi": roi,
    }


def _fmt_money(v):
    s = f"{abs(v):,.2f}".replace(",", " ")
    return s + " ₽"


def _draw_card(draw, x, y, title, s):
    draw.rounded_rectangle((x, y, x + CARD_W, y + CARD_H), radius=18, fill=CARD, outline=CARD_BORDER, width=1)
    draw.rectangle((x, y, x + 6, y + CARD_H), fill=ACCENT)
    f_title = _font(22, bold=True)
    f_label = _font(15)
    f_val = _font(17, bold=True)
    f_small = _font(13)

    draw.text((x + 22, y + 16), title, font=f_title, fill=TEXT)
    sub = f"Всего: {s['n']}" + (f"   ожидают расчёта: {s['pending']}" if s['pending'] else "")
    draw.text((x + 22, y + 46), sub, font=f_small, fill=MUTED)

    line_y = y + 78
    chip_w = (CARD_W - 44 - 16) // 3
    for i, (lbl, val, color) in enumerate([
        ("Победы", s["wins"], GREEN),
        ("Поражения", s["losses"], RED),
        ("Возвраты", s["returns"], BLUE),
    ]):
        cx = x + 22 + i * (chip_w + 8)
        draw.rounded_rectangle((cx, line_y, cx + chip_w, line_y + 50), radius=10, fill=(28, 32, 48))
        draw.text((cx + chip_w // 2, line_y + 8), str(val), font=_font(20, bold=True), fill=color, anchor="mt")
        draw.text((cx + chip_w // 2, line_y + 32), lbl, font=f_small, fill=MUTED, anchor="mt")

    rows = [
        ("Средний кф", f"{s['avg_odds']:.2f}", TEXT),
        ("Сумма ставок", _fmt_money(s["total_amount"]), TEXT),
        ("Средняя ставка", _fmt_money(s["avg_amount"]), TEXT),
        ("Процент побед", f"{s['win_pct']:.1f}%", YELLOW),
        ("Профит", ("+" if s["profit"] >= 0 else "−") + _fmt_money(s["profit"]),
         GREEN if s["profit"] >= 0 else RED),
        ("ROI", ("+" if s["roi"] >= 0 else "−") + f"{abs(s['roi']):.1f}%",
         GREEN if s["roi"] >= 0 else RED),
    ]
    ry = y + 142
    for lbl, val, color in rows:
        draw.text((x + 22, ry), lbl, font=f_label, fill=MUTED)
        w = _text_w(draw, val, f_val)
        draw.text((x + CARD_W - 22 - w, ry - 1), val, font=f_val, fill=color)
        ry += 23


def _calc_height(blocks_per_market):
    h = PAD + 90  # header
    for n_cards in blocks_per_market:
        h += 50  # market header
        if n_cards == 0:
            h += 50
        else:
            rows = (n_cards + 1) // 2
            h += rows * (CARD_H + CARD_GAP)
    return h + PAD


def _draw_header(draw, title, subtitle=None, finance=None):
    draw.rounded_rectangle((PAD, PAD, WIDTH - PAD, PAD + 80 if not finance else PAD + 170),
                           radius=20, fill=HEADER_BG)
    draw.text((PAD + 24, PAD + 18), title, font=_font(28, bold=True), fill=TEXT)
    if subtitle:
        draw.text((PAD + 24, PAD + 52), subtitle, font=_font(15), fill=(199, 210, 254))
    if finance:
        dep, wd, balance = finance
        cy = PAD + 90
        col_w = (WIDTH - PAD * 2 - 32) // 3
        for i, (lbl, val, color) in enumerate([
            ("ДЕПОЗИТЫ", _fmt_money(dep), TEXT),
            ("ВЫВОДЫ", _fmt_money(wd), TEXT),
            ("БАЛАНС", ("+" if balance >= 0 else "−") + _fmt_money(balance),
             GREEN if balance >= 0 else RED),
        ]):
            cx = PAD + 16 + i * (col_w + 8)
            draw.rounded_rectangle((cx, cy, cx + col_w, cy + 70), radius=14, fill=(40, 38, 100))
            draw.text((cx + col_w // 2, cy + 10), lbl, font=_font(12, bold=True), fill=(199, 210, 254), anchor="mt")
            draw.text((cx + col_w // 2, cy + 32), val, font=_font(20, bold=True), fill=color, anchor="mt")


BET_TYPES_ORDER = ["Одинар", "Двойник", "Тройник", "Экспресс"]
MARKETS_ORDER = [("Линия", BLUE), ("Лайв", RED)]


def render_stats_image(title, subtitle, rows, finance=None):
    """rows: list of tuples (bet_type, market, amount, odds, result, payout)"""
    grouped = {}
    for m_name, _ in MARKETS_ORDER:
        for bt in BET_TYPES_ORDER:
            data = [(r[2], r[3], r[4], r[5]) for r in rows if r[1] == m_name and r[0] == bt]
            grouped[(m_name, bt)] = _group_stats(data)

    blocks_per_market = []
    for m_name, _ in MARKETS_ORDER:
        blocks_per_market.append(sum(1 for bt in BET_TYPES_ORDER if grouped[(m_name, bt)]))

    height = _calc_height(blocks_per_market)
    img = Image.new("RGB", (WIDTH, height), BG)
    draw = ImageDraw.Draw(img)

    _draw_header(draw, title, subtitle, finance)
    cy = PAD + (170 if finance else 80) + 20

    for (m_name, m_color), n_cards in zip(MARKETS_ORDER, blocks_per_market):
        draw.rectangle((PAD, cy + 8, PAD + 6, cy + 38), fill=m_color)
        draw.text((PAD + 18, cy + 8), m_name.upper(), font=_font(22, bold=True), fill=TEXT)
        cy += 50
        if n_cards == 0:
            draw.text((PAD + 18, cy + 8), "Нет ставок в этой категории.", font=_font(15), fill=MUTED)
            cy += 50
            continue
        col = 0
        row_top = cy
        for bt in BET_TYPES_ORDER:
            s = grouped[(m_name, bt)]
            if not s:
                continue
            x = PAD + col * (CARD_W + CARD_GAP)
            _draw_card(draw, x, row_top, bt, s)
            col += 1
            if col == 2:
                col = 0
                row_top += CARD_H + CARD_GAP
        if col == 1:
            row_top += CARD_H + CARD_GAP
        cy = row_top

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def render_empty_image(title, subtitle="Ставок пока нет."):
    img = Image.new("RGB", (WIDTH, 260), BG)
    draw = ImageDraw.Draw(img)
    _draw_header(draw, title, subtitle)
    draw.rounded_rectangle((PAD, PAD + 110, WIDTH - PAD, 240), radius=18, fill=CARD, outline=CARD_BORDER, width=1)
    draw.text((WIDTH // 2, 175), "Данных нет", font=_font(22, bold=True), fill=MUTED, anchor="mm")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
