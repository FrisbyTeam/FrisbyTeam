import asyncio
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# 🔑 ВСТАВЬТЕ СЮДА ТОКЕН ОТ @BotFather
BOT_TOKEN = "ВАШ_ТОКЕН_ОТ_BOTFATHER"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# 📋 Списки для кнопок
BOOKMAKERS = ["Фонбет", "Pari", "BetBoom", "Marathon.bet", "OlimpBet", "BetCity", 
              "Winline", "Лига ставок", "Zenit", "MelBet", "Leon.ru", "Tennisi.bet", 
              "Bettery", "BET-M", "БалтБет", "СпортБет", "24bet.ru"]
SPORTS = ["Футбол", "Хоккей", "Баскетбол", "Волейбол", "Киберспорт", "Теннис", 
          "Бильярд/Снукер", "Единоборства/Бокс", "Другое"]

class BetStates(StatesGroup):
    waiting_amount = State()
    waiting_odds = State()
    calc_select = State()
    calc_result = State()

# 🗄️ База данных
async def init_db():
    async with aiosqlite.connect("bets.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, bookmaker TEXT, market TEXT, bet_type TEXT, sport TEXT,
            amount REAL, odds REAL, status TEXT DEFAULT 'uncalculated',
            result TEXT, payout REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        await db.commit()

async def save_bet( dict) -> int:
    async with aiosqlite.connect("bets.db") as db:
        cur = await db.execute(
            "INSERT INTO bets (user_id, bookmaker, market, bet_type, sport, amount, odds) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data["user_id"], data["bookmaker"], data["market"], data["bet_type"], data["sport"], data["amount"], data["odds"])
        )
        await db.commit()
        return data.get("step") # placeholder, real ID fetched below
    return 0

async def get_last_bet_id() -> int:
    async with aiosqlite.connect("bets.db") as db:
        cur = await db.execute("SELECT id FROM bets ORDER BY id DESC LIMIT 1")        res = await cur.fetchone()
        return res[0] if res else 0

async def get_uncalculated_bets(user_id: int):
    async with aiosqlite.connect("bets.db") as db:
        cur = await db.execute(
            "SELECT id, bookmaker, sport, amount, odds FROM bets WHERE user_id=? AND status='uncalculated'", (user_id,)
        )
        return await cur.fetchall()

async def update_bet_result(bet_id: int, result: str, payout: float):
    async with aiosqlite.connect("bets.db") as db:
        await db.execute("UPDATE bets SET status='calculated', result=?, payout=? WHERE id=?", (result, payout, bet_id))
        await db.commit()

# 🛠️ Хелперы
def main_menu_kb():
    kb = ReplyKeyboardBuilder()
    for txt in ["Ставка", "Депозит", "Вывод", "Моя статистика"]:
        kb.button(text=txt)
    kb.adjust(2)
    return kb.as_markup(resize_keyboard=True)

def parse_float(text: str) -> float:
    return float(text.replace(",", ".").replace(" ", ""))

# 🟢 /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="НАЧАТЬ", callback_data="go_main")
    await message.answer(
        "Привет! Я бот, которого сделал человек, который долго искал какой-то сервис, что бы отслеживать свою статистику по ставкам, и, так как ничего подходящего не было найдено, появился я! Давай же начнем наш путь!",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data == "go_main")
async def show_main(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Выберите раздел:", reply_markup=main_menu_kb())
    await call.answer()

# 📊 Меню "Ставка"
@dp.message(F.text == "Ставка")
async def bet_submenu(message: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.button(text="Внести ставку", callback_data="bet_add")
    kb.button(text="Рассчитать ставку", callback_data="bet_calc_list")
    kb.adjust(1)    await message.answer("Что вы хотите сделать?", reply_markup=kb.as_markup())

# 🔹 ВНЕСТИ СТАВКУ (Линейный опрос через FSM)
BET_QUESTIONS = [
    {"key": "bookmaker", "q": "1️⃣ В какой букмекерской конторе сделали ставку?", "opts": BOOKMAKERS, "prefix": "bc"},
    {"key": "market", "q": "2️⃣ Вид рынка?", "opts": ["Линия", "Лайв"], "prefix": "mkt"},
    {"key": "bet_type", "q": "3️⃣ Тип ставки?", "opts": ["Одинар", "Двойник", "Тройник", "Экспресс"], "prefix": "bt"},
    {"key": "sport", "q": "4️⃣ Вид спорта?", "opts": SPORTS, "prefix": "sp"}
]

@dp.callback_query(F.data == "bet_add")
async def start_bet_flow(call: types.CallbackQuery, state: FSMContext):
    await state.update_data(user_id=call.from_user.id, step=0)
    q = BET_QUESTIONS[0]
    kb = InlineKeyboardBuilder()
    for opt in q["opts"]:
        kb.button(text=opt, callback_data=f"{q['prefix']}_{opt}")
    kb.adjust(2)
    await call.message.answer(q["q"], reply_markup=kb.as_markup())
    await call.answer()

# Обработка кнопок опроса
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
        # Переход к ручному вводу
        await state.set_state(BetStates.waiting_amount)
        await call.message.edit_text("5️⃣ Сумма вашей ставки?\n(Введите без пробелов, копейки через запятую, напр: 1432,00)")
    await call.answer()

# Сумма
@dp.message(BetStates.waiting_amount)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        val = parse_float(message.text)
        if val <= 0: raise ValueError        await state.update_data(amount=val)
        await state.set_state(BetStates.waiting_odds)
        await message.answer("6️⃣ С каким коэффициентом ваша ставка?\n(До сотых, напр: 1,80)")
    except ValueError:
        await message.answer("⚠️ Неверный формат. Введите число больше 0, дробную часть отделяйте запятой. Пример: 500,00")

# Коэффициент
@dp.message(BetStates.waiting_odds)
async def process_odds(message: types.Message, state: FSMContext):
    try:
        val = parse_float(message.text)
        if val <= 1.0: raise ValueError
        data = await state.get_data()
        data["odds"] = val
        data["user_id"] = message.from_user.id
        
        # Сохраняем в БД
        async with aiosqlite.connect("bets.db") as db:
            await db.execute("INSERT INTO bets (user_id, bookmaker, market, bet_type, sport, amount, odds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (data["user_id"], data["bookmaker"], data["market"], data["bet_type"], data["sport"], data["amount"], data["odds"]))
            await db.commit()
        
        bet_id = await get_last_bet_id()
        await state.clear()
        
        kb = InlineKeyboardBuilder()
        kb.button(text="🏠 Главное меню", callback_data="go_main")
        await message.answer(
            f"✅ Ваша ставка учтена. Номер вашей ставки: {bet_id}.\nКак только ваша ставка рассчитается, нажмите соответствующую кнопку в главном меню! Удачи!",
            reply_markup=kb.as_markup()
        )
    except ValueError:
        await message.answer("⚠️ Коэффициент должен быть числом > 1.00. Пример: 1,85")

# 🔹 РАССЧИТАТЬ СТАВКУ
@dp.callback_query(F.data == "bet_calc_list")
async def show_uncalculated(call: types.CallbackQuery, state: FSMContext):
    bets = await get_uncalculated_bets(call.from_user.id)
    if not bets:
        await call.message.answer("📭 У вас нет ставок, ожидающих расчёта.")
        await call.answer()
        return

    kb = InlineKeyboardBuilder()
    for bid, bk, sp, am, od in bets:
        label = f"#{bid} | {bk} | {sp} | {am}₽ @ {od}"
        kb.button(text=label, callback_data=f"calc_{bid}")
    kb.adjust(1)
    
    await state.set_state(BetStates.calc_select)    await call.message.answer("Выберите ставку для расчёта:", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("calc_"), BetStates.calc_select)
async def select_bet(call: types.CallbackQuery, state: FSMContext):
    bet_id = int(call.data.split("_")[1])
    await state.update_data(bet_id=bet_id)
    await state.set_state(BetStates.calc_result)
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🟢 Выигрыш", callback_data="res_win")
    kb.button(text="🔴 Проигрыш", callback_data="res_loss")
    kb.button(text="🔄 Возврат", callback_data="res_push")
    kb.adjust(1)
    
    await call.message.edit_text("Какой результат вашей ставки?", reply_markup=kb.as_markup())
    await call.answer()

@dp.callback_query(F.data.startswith("res_"), BetStates.calc_result)
async def process_result(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    bet_id = data["bet_id"]
    res_code = call.data.split("_")[1]
    
    # Получаем данные ставки для расчёта
    async with aiosqlite.connect("bets.db") as db:
        cur = await db.execute("SELECT amount, odds FROM bets WHERE id=?", (bet_id,))
        row = await cur.fetchone()
        if not row:
            await call.message.answer("⚠️ Ошибка: ставка не найдена.")
            return
        am, od = row

    if res_code == "win":
        payout = am * od
        res_txt = "Выигрыш"
    elif res_code == "loss":
        payout = 0.0
        res_txt = "Проигрыш"
    else:
        payout = am
        res_txt = "Возврат"

    await update_bet_result(bet_id, res_txt, payout)
    await state.clear()
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🏠 Главное меню", callback_data="go_main")
    await call.message.answer(f"✅ Результат сохранен.\n📊 Выплата: {payout:,.2f} ₽", reply_markup=kb.as_markup())
    await call.answer()
# 🚀 Запуск
async def main():
    await init_db()
    print("✅ Бот запущен. Ожидает сообщений...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())