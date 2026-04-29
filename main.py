import asyncio
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from stats_image import render_stats_image, render_empty_image

# 🔑 Токен берётся из секрета BOT_TOKEN
BOT_TOKEN = os.environ["BOT_TOKEN"]
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# 📋 Списки кнопок
BOOKMAKERS = ["Фонбет", "Pari", "BetBoom", "Marathon.bet", "OlimpBet", "BetCity",
              "Winline", "Лига ставок", "Zenit", "MelBet", "Leon.ru", "Tennisi.bet",
              "Bettery", "BET-M", "БалтБет", "СпортБет", "24bet.ru"]
SPORTS = ["Футбол", "Хоккей", "Баскетбол", "Волейбол", "Киберспорт", "Теннис",
          "Бильярд/Снукер", "Единоборства/Бокс", "Другое"]

class AppStates(StatesGroup):
    # Ставки
    bet_amount = State()
    bet_odds = State()
    calc_select = State()
    calc_result = State()
    # Депозиты
    dep_amount = State()
    # Выводы
    wd_amount = State()
    # Фрибеты
    type_choice = State()
    fb_sport = State()
    fb_amount = State()
    freebet_menu = State()

# 🗄️ База данных
async def init_db():
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bookmaker TEXT, market TEXT, bet_type TEXT, sport TEXT,
            amount REAL, odds REAL, status TEXT DEFAULT 'uncalculated', result TEXT, payout REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        # Безопасно добавляем колонки, если их нет
        try: await db.execute("ALTER TABLE bets ADD COLUMN is_freebet INTEGER DEFAULT 0")
        except: pass
        try: await db.execute("ALTER TABLE bets ADD COLUMN freebet_amount REAL DEFAULT 0")        except: pass
        
        await db.execute("""CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bookmaker TEXT, amount REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bookmaker TEXT, amount REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS freebets_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, bookmaker TEXT, amount REAL, date TEXT, status TEXT DEFAULT 'issued')""")
        await db.commit()

# 🛠️ Хелперы
def main_menu_kb():
    kb = ReplyKeyboardBuilder()
    for txt in ["Ставка", "Депозит", "Вывод", "Фрибеты", "Моя статистика"]:
        kb.button(text=txt)
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)
  
def bet_submenu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Внести ставку", callback_data="bet_add")
    kb.button(text="🧮 Рассчитать ставку", callback_data="bet_calc_list")
    kb.button(text="📜 История моих ставок", callback_data="bet_history")
    kb.button(text="🗑️ Очистить историю", callback_data="bet_clear_ask")
    kb.button(text="🔙 В главное меню", callback_data="go_main")
    kb.adjust(1)
    return kb.as_markup()

def parse_float(text: str) -> float:
    return float(text.replace(",", ".").replace(" ", ""))

def fmt_date(dt: str) -> str:
    y, m, d = dt[:10].split("-")
    return f"{d}.{m}.{y}"

async def send_long_message(chat_id, text: str, parse_mode="HTML"):
    if len(text) <= 4000:
        await bot.send_message(chat_id, text, parse_mode=parse_mode)
        return
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id, text[i:i+4000], parse_mode=parse_mode)

# 🟢 /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="НАЧАТЬ", callback_data="go_main")
    await message.answer(
        "Привет! Я бот, которого сделал человек, который долго искал какой-то сервис, что бы отслеживать свою статистику по ставкам, и, так как ничего подходящего не было найдено, появился я! Давай же начнем наш путь!",
        reply_markup=kb.as_markup()    )

@dp.callback_query(F.data == "go_main")
async def show_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Выберите раздел:", reply_markup=main_menu_kb())
    await call.answer()

# 📊 Меню "Ставка"
@dp.message(F.text == "Ставка")
async def bet_submenu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Что вы хотите сделать?", reply_markup=bet_submenu_kb())

# 🔹 ВНЕСТИ СТАВКУ
BET_QUESTIONS = [
    {"key": "bookmaker", "q": "1️⃣ В какой букмекерской конторе сделали ставку?", "opts": BOOKMAKERS, "prefix": "bc"},
    {"key": "market", "q": "2️⃣ Вид рынка?", "opts": ["Линия", "Лайв"], "prefix": "mkt"},
    {"key": "bet_type", "q": "3️⃣ Тип ставки?", "opts": ["Одинар", "Двойник", "Тройник", "Экспресс"], "prefix": "bt"},
    {"key": "sport", "q": "4️⃣ Вид спорта?", "opts": SPORTS, "prefix": "sp"}
]

@dp.callback_query(F.data == "bet_add")
async def start_bet_flow(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(user_id=call.from_user.id, step=0)
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 Основная сумма", callback_data="bet_type_main")
    kb.button(text="🎁 Фрибет", callback_data="bet_type_freebet")
    kb.adjust(1)
    await call.message.answer("💰 Тип ставки:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(lambda c: c.data in ["bet_type_main", "bet_type_freebet"])
async def choose_bet_type(call: types.CallbackQuery, state: FSMContext):
    is_fb = call.data == "bet_type_freebet"
    await state.update_data(is_freebet_flag=is_fb)

    if is_fb:
        kb = InlineKeyboardBuilder()
        for bk in BOOKMAKERS:
            safe_id = bk.replace(" ", "").replace(".", "").lower()[:15]
            kb.button(text=bk, callback_data=f"fb_choose_{safe_id}")
        kb.adjust(2)
        await call.message.answer("📚 Выбери букмекера, где получен фрибет:", reply_markup=kb.as_markup())
    else:
        q = BET_QUESTIONS[0]
        kb = InlineKeyboardBuilder()
        for opt in q["opts"]:
            kb.button(text=opt, callback_data=f"{q['prefix']}_{opt}")
        kb.adjust(2)        await call.message.answer(q["q"], reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith(("bc_", "mkt_", "bt_", "sp_")))
async def process_inline_step(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = data.get("step", 0)
    key = BET_QUESTIONS[step]["key"]
    value = call.data.split("_", 1)[1]

    await state.update_data(**{key: value}, step=step + 1)

    if step + 1 < len(BET_QUESTIONS):
        q = BET_QUESTIONS[step + 1]
        kb = InlineKeyboardBuilder()
        for opt in q["opts"]:
            kb.button(text=opt, callback_data=f"{q['prefix']}_{opt}")
        kb.adjust(2)
        await call.message.edit_text(q["q"], reply_markup=kb.as_markup())
    else:
        await state.set_state(AppStates.bet_amount)
        await call.message.edit_text("5️⃣ Сумма вашей ставки?\n(Введите без пробелов, копейки через запятую, напр: 1432,00)")
    await call.answer()

@dp.message(AppStates.bet_amount)
async def process_bet_amount(message: types.Message, state: FSMContext):
    try:
        val = parse_float(message.text)
        if val <= 0:
            raise ValueError
        await state.update_data(amount=val)
        await state.set_state(AppStates.bet_odds)
        await message.answer("6️⃣ С каким коэффициентом ваша ставка?\n(До сотых, напр: 1,80)")
    except ValueError:
        await message.answer("⚠️ Неверный формат. Введите число > 0. Пример: 500,00")

@dp.message(AppStates.bet_odds)
async def process_bet_odds(message: types.Message, state: FSMContext):
    try:
        val = parse_float(message.text)
        if val <= 1.0:
            raise ValueError
        data = await state.get_data()
        data["odds"] = val

        # Для фрибетов ставим дефолтные значения полей БД
        if data.get("is_freebet_flag"):
            data.setdefault("market", "Линия")
            data.setdefault("bet_type", "Одинар")
            data.setdefault("sport", "Другое")
        is_fb = data.get("is_freebet_flag", False)
        fb_amt = data.get("freebet_amount", 0.0)

        async with aiosqlite.connect("stats.db") as db:
            await db.execute("""INSERT INTO bets (user_id, bookmaker, market, bet_type, sport, amount, odds, is_freebet, freebet_amount) 
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (data["user_id"], data["bookmaker"], data["market"], data["bet_type"], data["sport"], 
                 data["amount"], data["odds"], 1 if is_fb else 0, fb_amt))
            await db.commit()

            cur = await db.execute("SELECT id FROM bets ORDER BY id DESC LIMIT 1")
            bet_id = (await cur.fetchone())[0]

        await state.clear()
        kb = InlineKeyboardBuilder()
        kb.button(text="🏠 Главное меню", callback_data="go_main")
        await message.answer(
            f"✅ Ваша ставка учтена. <b>Номер: #{bet_id}</b>.\nКак только ставка рассчитается, вернитесь в раздел «Ставка» → «Рассчитать ставку». Удачи!",
            reply_markup=kb.as_markup(), parse_mode="HTML"
        )
    except ValueError:
        await message.answer("⚠️ Коэффициент должен быть > 1.00. Пример: 1,85")

# 🔹 РАССЧИТАТЬ СТАВКУ
@dp.callback_query(F.data == "bet_calc_list")
async def show_uncalculated(call: types.CallbackQuery, state: FSMContext):
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute("SELECT id, bookmaker, sport, amount, odds FROM bets WHERE user_id=? AND status='uncalculated' ORDER BY id DESC", (call.from_user.id,))
        bets = await cur.fetchall()

    if not bets:
        await call.message.answer("📭 У вас нет ставок, ожидающих расчёта.")
        await call.answer()
        return

    kb = InlineKeyboardBuilder()
    for bid, bk, sp, am, od in bets:
        kb.button(text=f"#{bid} | {bk} | {sp} | {am}₽ @ {od}", callback_data=f"calc_{bid}")
    kb.adjust(1)
    kb.button(text="🔙 Назад", callback_data="back_to_bet_menu")

    await state.set_state(AppStates.calc_select)
    await call.message.answer("Выберите ставку для расчёта:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("calc_"), AppStates.calc_select)
async def select_bet(call: types.CallbackQuery, state: FSMContext):
    bet_id = int(call.data.split("_")[1])
    await state.update_data(bet_id=bet_id)    await state.set_state(AppStates.calc_result)

    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Выигрыш", callback_data="res_win")
    kb.button(text="🔴 Проигрыш", callback_data="res_loss")
    kb.button(text="🔄 Возврат", callback_data="res_push")
    kb.adjust(3)

    await call.message.edit_text("Какой результат вашей ставки?", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("res_"), AppStates.calc_result)
async def process_result(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet_id = data["bet_id"]
    res_code = call.data.split("_")[1]

    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute("SELECT amount, odds, is_freebet, freebet_amount FROM bets WHERE id=?", (bet_id,))
        row = await cur.fetchone()
        am, od, is_fb, fb_amt = (row[0], row[1], row[2] or 0, row[3] or 0.0)

    if is_fb:
        if res_code == "win":
            payout = (fb_amt * od) - fb_amt
        else:
            payout = 0.0
    else:
        if res_code == "win":
            payout = am * (od - 1)
        elif res_code == "loss":
            payout = -am
        else:
            payout = 0.0

    res_txt = "Выигрыш" if res_code == "win" else ("Проигрыш" if res_code == "loss" else "Возврат")

    async with aiosqlite.connect("stats.db") as db:
        await db.execute("UPDATE bets SET status='calculated', result=?, payout=? WHERE id=?", (res_txt, payout, bet_id))
        await db.commit()

    await state.clear()
    await call.message.answer(f"✅ Результат сохранен.\n📊 Итог: <b>{payout:,.2f} ₽</b>", parse_mode="HTML")
    await call.answer()

# 📜 ИСТОРИЯ СТАВОК
PAGE_SIZE = 10

def add_nav_buttons(kb, page, has_more, prefix, back_cb):
    if page > 0 and has_more:        kb.row()
        kb.button(text="◀️ Назад", callback_data=f"{prefix}{page - 1}")
        kb.button(text="Вперёд ▶️", callback_data=f"{prefix}{page + 1}")
    elif page > 0:
        kb.row()
        kb.button(text="◀️ Назад", callback_data=f"{prefix}{page - 1}")
    elif has_more:
        kb.row()
        kb.button(text="Вперёд ▶️", callback_data=f"{prefix}{page + 1}")
    kb.row()
    kb.button(text="🔙 В меню", callback_data=back_cb)

async def render_bet_history(call, page):
    offset = page * PAGE_SIZE
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute(
            "SELECT id, bookmaker, sport, amount, odds, result, payout, created_at FROM bets "
            "WHERE user_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (call.from_user.id, PAGE_SIZE + 1, offset))
        bets = await cur.fetchall()
    if not bets and page == 0:
        await call.message.answer("📭 История ставок пуста.", reply_markup=bet_submenu_kb())
        return
    has_more = len(bets) > PAGE_SIZE
    bets = bets[:PAGE_SIZE]
    kb = InlineKeyboardBuilder()
    for bid, bk, sp, am, od, res, pay, date in bets:
        emoji = "🟢" if res == "Выигрыш" else ("🔴" if res == "Проигрыш" else ("🔄" if res == "Возврат" else "⏳"))
        kb.button(text=f"🗑️ #{bid} | {bk} | {am:,.0f}₽ @ {od} | {emoji} | {fmt_date(date)}",
                  callback_data=f"bet_del_{bid}")
    kb.adjust(1)
    add_nav_buttons(kb, page, has_more, "bet_hist_p_", "back_to_bet_menu")
    await call.message.answer(f"📊 <b>История ставок</b> — страница {page + 1}\nНажмите на запись, чтобы удалить:",
                              reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "bet_history")
async def show_history(call: types.CallbackQuery):
    await render_bet_history(call, 0)
    await call.answer()

@dp.callback_query(F.data.startswith("bet_hist_p_"))
async def bet_history_page(call: types.CallbackQuery):
    page = int(call.data.split("bet_hist_p_", 1)[1])
    await render_bet_history(call, page)
    await call.answer()

@dp.callback_query(F.data.startswith("bet_del_"))
async def bet_del_ask(call: types.CallbackQuery):
    bid = int(call.data.split("bet_del_", 1)[1])
    async with aiosqlite.connect("stats.db") as db:        cur = await db.execute(
            "SELECT bookmaker, sport, amount, odds, result, payout, created_at FROM bets WHERE id=? AND user_id=?",
            (bid, call.from_user.id))
        row = await cur.fetchone()
    if not row:
        await call.answer("Запись не найдена", show_alert=True)
        return
    bk, sp, am, od, res, pay, dt = row
    res_text = f"{res} (+{pay:,.2f}₽)" if res else "Не рассчитана"
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑️ Удалить", callback_data=f"bet_delc_{bid}")
    kb.button(text="❌ Отмена", callback_data="bet_history")
    kb.adjust(2)
    await call.message.edit_text(
        f"⚠️ Удалить ставку?\n\n<b>#{bid}</b> | {bk} | {sp}\n"
        f"💰 {am:,.2f} ₽ @ {od}\nРезультат: {res_text}\n📅 {fmt_date(dt)}",
        reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("bet_delc_"))
async def bet_del_confirm(call: types.CallbackQuery):
    bid = int(call.data.split("bet_delc_", 1)[1])
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("DELETE FROM bets WHERE id=? AND user_id=?", (bid, call.from_user.id))
        await db.commit()
    await call.message.edit_text(f"🗑️ Ставка #{bid} удалена.")
    await call.message.answer("Что вы хотите сделать?", reply_markup=bet_submenu_kb())
    await call.answer()

# 🗑️ ОЧИСТИТЬ ИСТОРИЮ
@dp.callback_query(F.data == "bet_clear_ask")
async def ask_clear(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑️ Да, удалить всё", callback_data="bet_clear_yes")
    kb.button(text="❌ Отмена", callback_data="back_to_bet_menu")
    kb.adjust(2)
    await call.message.answer("⚠️ <b>Внимание!</b>\nВы уверены, что хотите удалить всю историю ставок? Это действие нельзя отменить.", reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "bet_clear_yes")
async def process_clear_yes(call: types.CallbackQuery):
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("DELETE FROM bets WHERE user_id=?", (call.from_user.id,))
        await db.commit()
    await call.message.edit_text("🗑️ История ставок успешно очищена.")
    await asyncio.sleep(1)
    await call.message.answer("Выберите раздел:", reply_markup=main_menu_kb())
    await call.answer()

@dp.callback_query(F.data == "back_to_bet_menu")async def back_to_bet(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Что вы хотите сделать?", reply_markup=bet_submenu_kb())
    await call.answer()

# 💰 МЕНЮ "ДЕПОЗИТ"
def deposit_submenu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Внести депозит", callback_data="dep_add")
    kb.button(text="📜 История депозитов", callback_data="dep_history")
    kb.button(text="🔙 В главное меню", callback_data="go_main")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(F.text == "Депозит")
async def deposit_submenu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Что вы хотите сделать?", reply_markup=deposit_submenu_kb())

@dp.callback_query(F.data == "dep_add")
async def deposit_add_start(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    for bk in BOOKMAKERS:
        kb.button(text=bk, callback_data=f"dep_bc_{bk}")
    kb.adjust(2)
    await call.message.answer("1️⃣ В какой букмекерской конторе сделали депозит?", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("dep_bc_"))
async def process_dep_bookmaker(call: types.CallbackQuery, state: FSMContext):
    bc_name = call.data.split("dep_bc_", 1)[1]
    await state.update_data(deposit_bookmaker=bc_name)
    await state.set_state(AppStates.dep_amount)
    await call.message.edit_text("2️⃣ На какую сумму внесён депозит?\n(Введите сумму без пробелов и точек, копейки отделите запятой, например 1500,00)")
    await call.answer()

@dp.message(AppStates.dep_amount)
async def process_dep_amount(message: types.Message, state: FSMContext):
    try:
        val = parse_float(message.text)
        if val <= 0:
            raise ValueError
        data = await state.get_data()
        async with aiosqlite.connect("stats.db") as db:
            await db.execute("INSERT INTO deposits (user_id, bookmaker, amount) VALUES (?, ?, ?)",
                             (message.from_user.id, data["deposit_bookmaker"], val))
            await db.commit()
        await state.clear()
        kb = InlineKeyboardBuilder()        kb.button(text="🏠 Главное меню", callback_data="go_main")
        await message.answer(f"✅ Депозит в <b>{data['deposit_bookmaker']}</b> на сумму <b>{val:,.2f} ₽</b> учтён.", reply_markup=kb.as_markup(), parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Неверный формат. Введите число > 0. Пример: 1500,00")

async def render_dep_history(call, page):
    offset = page * PAGE_SIZE
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute(
          "SELECT id, bookmaker, amount, created_at FROM deposits WHERE user_id=? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (call.from_user.id, PAGE_SIZE + 1, offset))
        rows = await cur.fetchall()
    if not rows and page == 0:
        await call.message.answer("📭 История депозитов пуста.", reply_markup=deposit_submenu_kb())
        return
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    kb = InlineKeyboardBuilder()
    for did, bk, am, dt in rows:
        kb.button(text=f"🗑️ #{did} | {bk} | {am:,.2f}₽ | {fmt_date(dt)}", callback_data=f"dep_del_{did}")
    kb.adjust(1)
    add_nav_buttons(kb, page, has_more, "dep_hist_p_", "dep_back")
    await call.message.answer(f"📜 <b>История депозитов</b> — страница {page + 1}\nНажмите на запись, чтобы удалить:",
                              reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "dep_history")
async def dep_history(call: types.CallbackQuery):
    await render_dep_history(call, 0)
    await call.answer()

@dp.callback_query(F.data.startswith("dep_hist_p_"))
async def dep_history_page(call: types.CallbackQuery):
    page = int(call.data.split("dep_hist_p_", 1)[1])
    await render_dep_history(call, page)
    await call.answer()

@dp.callback_query(F.data.startswith("dep_del_"))
async def dep_del_ask(call: types.CallbackQuery):
    did = int(call.data.split("dep_del_", 1)[1])
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute("SELECT bookmaker, amount, created_at FROM deposits WHERE id=? AND user_id=?",
                               (did, call.from_user.id))
        row = await cur.fetchone()
    if not row:
        await call.answer("Запись не найдена", show_alert=True)
        return
    bk, am, dt = row
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑️ Удалить", callback_data=f"dep_delc_{did}")
    kb.button(text="❌ Отмена", callback_data="dep_history")
    kb.adjust(2)
    await call.message.edit_text(
        f"⚠️ Удалить запись?\n\n<b>#{did}</b> | {bk}\n💰 {am:,.2f} ₽\n📅 {fmt_date(dt)}",
        reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("dep_delc_"))
async def dep_del_confirm(call: types.CallbackQuery):
    did = int(call.data.split("dep_delc_", 1)[1])
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("DELETE FROM deposits WHERE id=? AND user_id=?", (did, call.from_user.id))
        await db.commit()
    await call.message.edit_text(f"🗑️ Депозит #{did} удалён.")
    await call.message.answer("Что дальше?", reply_markup=deposit_submenu_kb())
    await call.answer()

@dp.callback_query(F.data == "dep_back")
async def dep_back(call: types.CallbackQuery):
    await call.message.answer("Что вы хотите сделать?", reply_markup=deposit_submenu_kb())
    await call.answer()

# 💸 МЕНЮ "ВЫВОД"
def withdrawal_submenu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Внести вывод", callback_data="wd_add")
    kb.button(text="📜 История выводов", callback_data="wd_history")
    kb.button(text="🔙 В главное меню", callback_data="go_main")
    kb.adjust(1)
    return kb.as_markup()

@dp.message(F.text == "Вывод")
async def withdrawal_submenu(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Что вы хотите сделать?", reply_markup=withdrawal_submenu_kb())

@dp.callback_query(F.data == "wd_add")
async def withdrawal_add_start(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    for bk in BOOKMAKERS:
        kb.button(text=bk, callback_data=f"wd_bc_{bk}")
    kb.adjust(2)
    await call.message.answer("1️⃣ Из какой букмекерской конторы сделали вывод?", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("wd_bc_"))
async def process_wd_bookmaker(call: types.CallbackQuery, state: FSMContext):
    bc_name = call.data.split("wd_bc_", 1)[1]
    await state.update_data(withdrawal_bookmaker=bc_name)
    await state.set_state(AppStates.wd_amount)
    await call.message.edit_text("2️⃣ Какую сумму вывели?\n(Введите сумму без пробелов и точек, копейки отделите запятой, например 1500,00)")
    await call.answer()

@dp.message(AppStates.wd_amount)
async def process_wd_amount(message: types.Message, state: FSMContext):
    try:
        val = parse_float(message.text)
        if val <= 0:
            raise ValueError
        data = await state.get_data()
        async with aiosqlite.connect("stats.db") as db:
            await db.execute("INSERT INTO withdrawals (user_id, bookmaker, amount) VALUES (?, ?, ?)",
                             (message.from_user.id, data["withdrawal_bookmaker"], val))
            await db.commit()
        await state.clear()
        kb = InlineKeyboardBuilder()
        kb.button(text="🏠 Главное меню", callback_data="go_main")
        await message.answer(f"✅ Вывод из <b>{data['withdrawal_bookmaker']}</b> на сумму <b>{val:,.2f} ₽</b> учтён.", reply_markup=kb.as_markup(), parse_mode="HTML")
    except ValueError:
        await message.answer("⚠️ Неверный формат. Введите число > 0. Пример: 1500,00")

async def render_wd_history(call, page):
    offset = page * PAGE_SIZE
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute(
            "SELECT id, bookmaker, amount, created_at FROM withdrawals WHERE user_id=? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (call.from_user.id, PAGE_SIZE + 1, offset))
        rows = await cur.fetchall()
    if not rows and page == 0:
        await call.message.answer("📭 История выводов пуста.", reply_markup=withdrawal_submenu_kb())
        return
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    kb = InlineKeyboardBuilder()
    for wid, bk, am, dt in rows:
        kb.button(text=f"🗑️ #{wid} | {bk} | {am:,.2f}₽ | {fmt_date(dt)}", callback_data=f"wd_del_{wid}")
    kb.adjust(1)
    add_nav_buttons(kb, page, has_more, "wd_hist_p_", "wd_back")
    await call.message.answer(f"📜 <b>История выводов</b> — страница {page + 1}\nНажмите на запись, чтобы удалить:",
                              reply_markup=kb.as_markup(), parse_mode="HTML")

@dp.callback_query(F.data == "wd_history")
async def wd_history(call: types.CallbackQuery):
    await render_wd_history(call, 0)
    await call.answer()

@dp.callback_query(F.data.startswith("wd_hist_p_"))
async def wd_history_page(call: types.CallbackQuery):
    page = int(call.data.split("wd_hist_p_", 1)[1])
    await render_wd_history(call, page)
    await call.answer()

@dp.callback_query(F.data.startswith("wd_del_"))
async def wd_del_ask(call: types.CallbackQuery):
    wid = int(call.data.split("wd_del_", 1)[1])
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute("SELECT bookmaker, amount, created_at FROM withdrawals WHERE id=? AND user_id=?",
                               (wid, call.from_user.id))
        row = await cur.fetchone()
    if not row:
        await call.answer("Запись не найдена", show_alert=True)
        return
    bk, am, dt = row
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑️ Удалить", callback_data=f"wd_delc_{wid}")
    kb.button(text="❌ Отмена", callback_data="wd_history")
    kb.adjust(2)
    await call.message.edit_text(
        f"⚠️ Удалить запись?\n\n<b>#{wid}</b> | {bk}\n💸 {am:,.2f} ₽\n📅 {fmt_date(dt)}",
        reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("wd_delc_"))
async def wd_del_confirm(call: types.CallbackQuery):
    wid = int(call.data.split("wd_delc_", 1)[1])
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("DELETE FROM withdrawals WHERE id=? AND user_id=?", (wid, call.from_user.id))
        await db.commit()
    await call.message.edit_text(f"🗑️ Вывод #{wid} удалён.")
    await call.message.answer("Что дальше?", reply_markup=withdrawal_submenu_kb())
    await call.answer()

@dp.callback_query(F.data == "wd_back")
async def wd_back(call: types.CallbackQuery):
    await call.message.answer("Что вы хотите сделать?", reply_markup=withdrawal_submenu_kb())
    await call.answer()

# 📊 МЕНЮ "МОЯ СТАТИСТИКА"
BET_TYPES_ORDER = ["Одинар", "Двойник", "Тройник", "Экспресс"]
MARKETS_ORDER = ["Линия", "Лайв"]

def format_group_stats(rows):
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
    profit_sign = "+" if profit >= 0 else ""
    return (
        f"   Всего ставок: <b>{n}</b>" + (f" (⏳ ожидают расчёта: {pending})" if pending else "") + "\n"
        f"   🟢 Выигрыши: <b>{wins}</b> | 🔴 Проигрыши: <b>{losses}</b> | 🔄 Возвраты: <b>{returns}</b>\n"
        f"   Средний кф: <b>{avg_odds:.2f}</b>\n"
        f"   Сумма ставок: <b>{total_amount:,.2f} ₽</b>\n"
        f"   Средняя ставка: <b>{avg_amount:,.2f} ₽</b>\n"
        f"   Процент побед: <b>{win_pct:.1f}%</b>\n"
        f"   Профит: <b>{profit_sign}{profit:,.2f} ₽</b>\n"
        f"   ROI: <b>{profit_sign}{roi:.1f}%</b>\n"
    )

async def build_bets_stats_text(user_id, bookmaker=None):
    query = "SELECT bet_type, market, amount, odds, result, payout FROM bets WHERE user_id=?"
    params = [user_id]
    if bookmaker:
        query += " AND bookmaker=?"
        params.append(bookmaker)
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute(query, params)
        rows = await cur.fetchall()

    if not rows:
        return "\n<i>Ставок пока нет.</i>\n"

    text = ""
    for market in MARKETS_ORDER:
        emoji = "📋" if market == "Линия" else "🔴"
        text += f"\n<b>{emoji} {market.upper()}</b>\n"
        any_in_market = False
        for bt in BET_TYPES_ORDER:
            group = [(r[2], r[3], r[4], r[5]) for r in rows if r[1] == market and r[0] == bt]
            stats = format_group_stats(group)
            if stats:
                any_in_market = True
                text += f"\n  <b>• {bt}</b>\n{stats}"
        if not any_in_market:
            text += "  <i>Нет ставок.</i>\n"
    return text

async def get_finance_for_bk(user_id, bookmaker, month=None):
    m_filter = " AND strftime('%Y-%m', created_at)=?" if month else ""
    params = [user_id, bookmaker] + ([month] if month else [])
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM deposits WHERE user_id=? AND bookmaker=?{m_filter}", params)
        dep = (await cur.fetchone())[0]
        cur = await db.execute(
            f"SELECT COALESCE(SUM(amount), 0) FROM withdrawals WHERE user_id=? AND bookmaker=?{m_filter}", params)
        wd = (await cur.fetchone())[0]
    return dep, wd

RU_MONTHS = {1:"Январь",2:"Февраль",3:"Март",4:"Апрель",5:"Май",6:"Июнь",
             7:"Июль",8:"Август",9:"Сентябрь",10:"Октябрь",11:"Ноябрь",12:"Декабрь"}

def fmt_month(ym: str) -> str:
    y, m = ym.split("-")
    return f"{RU_MONTHS[int(m)]} {y}"

async def get_months(user_id, bookmaker=None):
    bk_filter = " AND bookmaker=?" if bookmaker else ""
    params = [user_id] + ([bookmaker] if bookmaker else [])
    months = set()
    async with aiosqlite.connect("stats.db") as db:
        for tbl in ("bets", "deposits", "withdrawals"):
            cur = await db.execute(
                f"SELECT DISTINCT strftime('%Y-%m', created_at) FROM {tbl} WHERE user_id=?{bk_filter}",
                params)
            for r in await cur.fetchall():
                if r[0]:
                    months.add(r[0])
    return sorted(months, reverse=True)

async def fetch_bets(user_id, bookmaker=None, month=None):
    q = "SELECT bet_type, market, amount, odds, result, payout FROM bets WHERE user_id=?"
    p = [user_id]
    if bookmaker:
        q += " AND bookmaker=?"; p.append(bookmaker)
    if month:
        q += " AND strftime('%Y-%m', created_at)=?"; p.append(month)
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute(q, p)
        return await cur.fetchall()

@dp.message(F.text == "Моя статистика")
async def stats_menu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 По букмекерским конторам", callback_data="stats_by_bk")
    kb.button(text="📈 Общие показатели", callback_data="stats_total")
    kb.button(text="🗑️ Сбросить статистику", callback_data="stats_reset_ask")
    kb.button(text="🔙 В главное меню", callback_data="go_main")
    kb.adjust(1)
    await message.answer("Выберите раздел статистики:", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "stats_reset_ask")
async def stats_reset_ask(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🗑️ Да, удалить всё", callback_data="stats_reset_yes")
    kb.button(text="❌ Отмена", callback_data="go_main")
    kb.adjust(2)
    await call.message.answer(
        "⚠️ <b>Внимание!</b>\nВы собираетесь удалить <b>всю</b> статистику: ставки, депозиты и выводы. Это действие нельзя отменить.",
        reply_markup=kb.as_markup(), parse_mode="HTML"
    )
    await call.answer()

@dp.callback_query(F.data == "stats_reset_yes")
async def stats_reset_yes(call: types.CallbackQuery):
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("DELETE FROM bets WHERE user_id=?", (call.from_user.id,))
        await db.execute("DELETE FROM deposits WHERE user_id=?", (call.from_user.id,))
        await db.execute("DELETE FROM withdrawals WHERE user_id=?", (call.from_user.id,))
        await db.commit()
    await call.message.edit_text("🗑️ Статистика полностью очищена.")
    await call.message.answer("Выберите раздел:", reply_markup=main_menu_kb())
    await call.answer()

@dp.callback_query(F.data == "stats_total")
async def stats_total_menu(call: types.CallbackQuery):
    months = await get_months(call.from_user.id)
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Общая статистика (за всё время)", callback_data="tot_all")
    for m in months:
        kb.button(text=f"📅 {fmt_month(m)}", callback_data=f"tot_m_{m}")
    kb.button(text="🔙 Назад", callback_data="stats_back_menu")
    kb.adjust(1)
    await call.message.answer("Общие показатели — выберите период:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "tot_all")
async def stats_total_all(call: types.CallbackQuery):
    rows = await fetch_bets(call.from_user.id)
    if not rows:
        buf = render_empty_image("Общая статистика", "Ставок пока нет.")
    else:
        buf = render_stats_image("Общая статистика", "За всё время • все букмекерские конторы", rows)
    await bot.send_photo(call.from_user.id, BufferedInputFile(buf.read(), filename="stats.png"))
    await call.answer()

@dp.callback_query(F.data.startswith("tot_m_"))
async def stats_total_month(call: types.CallbackQuery):
    ym = call.data.split("tot_m_", 1)[1]
    rows = await fetch_bets(call.from_user.id, month=ym)
    if not rows:
        buf = render_empty_image("Общая статистика", f"{fmt_month(ym)} — ставок нет.")
    else:
        buf = render_stats_image("Общая статистика", f"{fmt_month(ym)} • все букмекерские конторы", rows)
    await bot.send_photo(call.from_user.id, BufferedInputFile(buf.read(), filename="stats.png"))
    await call.answer()

@dp.callback_query(F.data == "stats_back_menu")
async def stats_back_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 По букмекерским конторам", callback_data="stats_by_bk")
    kb.button(text="📈 Общие показатели", callback_data="stats_total")
    kb.button(text="🗑️ Сбросить статистику", callback_data="stats_reset_ask")
    kb.button(text="🔙 В главное меню", callback_data="go_main")
    kb.adjust(1)
    await call.message.answer("Выберите раздел статистики:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data == "stats_by_bk")
async def stats_by_bk_list(call: types.CallbackQuery):
    async with aiosqlite.connect("stats.db") as db:
        cur = await db.execute("""
            SELECT bookmaker FROM bets WHERE user_id=?
            UNION SELECT bookmaker FROM deposits WHERE user_id=?
            UNION SELECT bookmaker FROM withdrawals WHERE user_id=?
        """, (call.from_user.id, call.from_user.id, call.from_user.id))
        bks = sorted({r[0] for r in await cur.fetchall()})

    if not bks:
        await call.message.answer("📭 Пока нет данных ни по одной букмекерской конторе.")
        await call.answer()
        return

    kb = InlineKeyboardBuilder()
    for bk in bks:
        kb.button(text=bk, callback_data=f"stats_bk_{bk}")
    kb.adjust(2)
    await call.message.answer("Выберите букмекерскую контору:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("stats_bk_"))
async def stats_bk_period_menu(call: types.CallbackQuery):
    bk = call.data.split("stats_bk_", 1)[1]
    months = await get_months(call.from_user.id, bookmaker=bk)
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Общая статистика (за всё время)", callback_data=f"bkall_{bk}")
    for m in months:
        kb.button(text=f"📅 {fmt_month(m)}", callback_data=f"bkm_{m}_{bk}")
    kb.button(text="🔙 К списку контор", callback_data="stats_by_bk")
    kb.adjust(1)
    await call.message.answer(f"<b>{bk}</b>\nВыберите период:",
                              reply_markup=kb.as_markup(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data.startswith("bkall_"))
async def stats_bk_all(call: types.CallbackQuery):
    bk = call.data.split("bkall_", 1)[1]
    rows = await fetch_bets(call.from_user.id, bookmaker=bk)
    dep, wd = await get_finance_for_bk(call.from_user.id, bk)
    balance = wd - dep
    buf = render_stats_image(bk, "За всё время", rows, finance=(dep, wd, balance))
    await bot.send_photo(call.from_user.id, BufferedInputFile(buf.read(), filename=f"stats_{bk}.png"))
    await call.answer()

@dp.callback_query(F.data.startswith("bkm_"))
async def stats_bk_month(call: types.CallbackQuery):
    rest = call.data.split("bkm_", 1)[1]
    ym, bk = rest.split("_", 1)
    rows = await fetch_bets(call.from_user.id, bookmaker=bk, month=ym)
    dep, wd = await get_finance_for_bk(call.from_user.id, bk, month=ym)
    balance = wd - dep
    buf = render_stats_image(bk, fmt_month(ym), rows, finance=(dep, wd, balance))
    await bot.send_photo(call.from_user.id, BufferedInputFile(buf.read(), filename=f"stats_{bk}.png"))
    await call.answer()

# 🎁 ФРИБЕТЫ: ОБРАБОТЧИКИ
@dp.callback_query(F.data.startswith("fb_choose_"))
async def fb_bookmaker_selected(call: types.CallbackQuery, state: FSMContext):
    safe_id = call.data[10:]
    bk_name = next((b for b in BOOKMAKERS if b.replace(" ", "").replace(".", "").lower()[:15] == safe_id), "Unknown")
    await state.update_data(bookmaker=bk_name)
    await call.message.answer("🏆 Введи вид спорта (например: Футбол, Хоккей, Теннис):")
    await state.set_state(AppStates.fb_sport)
    await call.answer()

@dp.message(AppStates.fb_sport)
async def fb_sport_input(message: types.Message, state: FSMContext):
    await state.update_data(sport=message.text)
    await message.answer("💰 Введи сумму фрибета:")
    await state.set_state(AppStates.fb_amount)

@dp.message(AppStates.fb_amount)
async def fb_amount_input(message: types.Message, state: FSMContext):
    if not message.text.replace('.', '', 1).isdigit():
        return await message.answer("Введи число, например: 500")
    await state.update_data(freebet_amount=float(message.text))
    await message.answer("📈 Введи коэффициент (например: 2.10):")
    await state.set_state(AppStates.bet_odds)

@dp.message(F.text == "Фрибеты")
async def cmd_freebet(message: types.Message, state: FSMContext):
    kb = InlineKeyboardBuilder()
    for bk in BOOKMAKERS:
        safe_id = bk.replace(" ", "").replace(".", "").lower()[:15]
        kb.button(text=bk, callback_data=f"fbi_{safe_id}")
    kb.adjust(2)
    await message.answer("📚 От какого букмекера получен фрибет?", reply_markup=kb.as_markup())
    await state.set_state(AppStates.freebet_menu)

@dp.callback_query(F.data.startswith("fbi_"), AppStates.freebet_menu)
async def freebet_select_bk(call: types.CallbackQuery, state: FSMContext):
    safe_id = call.data[4:]
    bk_name = next((b for b in BOOKMAKERS if b.replace(" ", "").replace(".", "").lower()[:15] == safe_id), "Unknown")
    await state.update_data(issue_bk=bk_name)
    await call.message.answer("💰 Введи сумму выданного фрибета:")
    await state.set_state(AppStates.fb_amount_issue)
    await call.answer()

@dp.message(state=AppStates.fb_amount_issue)
async def freebet_save(message: types.Message, state: FSMContext):
    if not message.text.replace('.', '', 1).isdigit():
        return await message.answer("Введи число, например: 500")
    data = await state.get_data()
    amt = float(message.text)
    async with aiosqlite.connect("stats.db") as db:
        await db.execute("INSERT INTO freebets_log (user_id, bookmaker, amount, date) VALUES (?, ?, ?, ?)",
                         (message.from_user.id, data.get("issue_bk", "Unknown"), amt, datetime.now().strftime("%Y-%m-%d")))
        await db.commit()
    await message.answer(f"✅ Фрибет от {data.get('issue_bk')} на {amt}₽ записан! Используй его через меню «🎯 Ставка» → «🎁 Фрибет».")
    await state.clear()

# 🚀 Запуск
async def main():
    await init_db()
    print("✅ Бот запущен. Ожидает сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
