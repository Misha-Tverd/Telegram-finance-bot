# import logging
# import asyncio
# import re
# import sqlite3
# from datetime import datetime
# from difflib import get_close_matches

# from aiogram import Bot, Dispatcher, types, F
# from aiogram.filters import Command
# from aiogram.fsm.context import FSMContext
# from aiogram.fsm.state import State, StatesGroup
# from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# # ==========================================
# # 1. КОНФІГУРАЦІЯ ТА НАЛАШТУВАННЯ
# # ==========================================
# API_TOKEN = '8517651425:AAEKUffGx0dmj73YLOwEiFcqnrdOofpVwPU'

# # Мапінг ID користувачів (ЗАМІНИ НА ВЛАСНІ ID)
# USER_MAP = {
#     847387368: "Міша",
#     854570254: "Настя"
# }

# EXPENSE_CATS = ["🛒 Продукти", "⚡ Комунальні", "🏠 Для дому", "🏗️ Ремонт", "🚗 Транспорт", 
#                 "🐱 Тварини", "💊 Здоров'я", "👕 Одяг", "🎉 Відпочинок", "🧴 Догляд", "💸 Борг", "❓ Інше"]

# INCOME_CATS = ["💼 Зарплата", "🎁 Премія", "💳 Кешбек", "📈 Відсотки", "🪙 Копійки", "📦 Продаж", "🧧 Подарунок"]

# # ==========================================
# # 2. МОДУЛЬ БАЗИ ДАНИХ (DatabaseManager)
# # ==========================================
# class FinanceDB:
#     def __init__(self, db_path="finance.db"):
#         self.conn = sqlite3.connect(db_path)
#         self.conn.row_factory = sqlite3.Row
#         self.create_tables()

#     def get_all_balances(self):
#         with self.conn:
#             # Повертає список словників з назвою та сумою
#             return self.conn.execute("SELECT name, value FROM balances").fetchall()
#     def save_ten_percent(self, user_id, original_amount):
#         savings_amount = round(original_amount * 0.1, 2)
#         user_name = USER_MAP.get(user_id, "Гість")
#         date = datetime.now().strftime("%Y-%m-%d")
        
#         with self.conn:
#             # 1. Записуємо операцію в журнал як витрату на заощадження
#             self.conn.execute("""INSERT INTO journal (user_name, type, category, sub, amount, currency, date) 
#                                VALUES (?, 'expense', '🏦 Заощадження', 'Авто 10%', ?, 'UAH', ?)""",
#                               (user_name, savings_amount, date))
#             # 2. Знімаємо з основного гаманця
#             self.conn.execute("UPDATE balances SET value = value - ? WHERE name = 'UAH'", (savings_amount,))
#             # 3. Кладемо в гаманець заощаджень
#             self.conn.execute("UPDATE balances SET value = value + ? WHERE name = 'SAVINGS'", (savings_amount,))
#         return savings_amount

#     def create_tables(self):
#         with self.conn:
#             # Журнал транзакцій
#             self.conn.execute("""CREATE TABLE IF NOT EXISTS journal (
#                 id INTEGER PRIMARY KEY AUTOINCREMENT, 
#                 user_name TEXT, type TEXT, category TEXT, sub TEXT, 
#                 amount REAL, currency TEXT, date TEXT)""")
#             # Таблиця балансів
#             self.conn.execute("CREATE TABLE IF NOT EXISTS balances (name TEXT PRIMARY KEY, value REAL)")
#             for b in ['UAH', 'USD', 'EUR', 'COINS']:
#                 self.conn.execute("INSERT OR IGNORE INTO balances VALUES (?, 0)", (b,))

#     def add_entry(self, user_id, t_type, cat, sub, amount, curr='UAH'):
#         user_name = USER_MAP.get(user_id, "Гість")
#         date = datetime.now().strftime("%Y-%m-%d")
#         with self.conn:
#             self.conn.execute("INSERT INTO journal (user_name, type, category, sub, amount, currency, date) VALUES (?,?,?,?,?,?,?)",
#                               (user_name, t_type, cat, sub, amount, curr, date))
#             # Оновлення балансу (спрощено для UAH)
#             mod = 1 if t_type == 'income' else -1
#             target_wallet = 'COINS' if cat == "🪙 Копійки" else curr
#             self.conn.execute("UPDATE balances SET value = value + ? WHERE name = ?", (amount * mod, target_wallet))
#         return self.get_last_id()

#     def get_last_id(self):
#         return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

#     def delete_entry(self, entry_id):
#         with self.conn:
#             entry = self.conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
#             if entry:
#                 mod = -1 if entry['type'] == 'income' else 1
#                 self.conn.execute("UPDATE balances SET value = value + ? WHERE name = ?", (entry['amount'] * mod, entry['currency']))
#                 self.conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
#                 return True
#         return False

#     def get_stats_monthly(self):
#         month = datetime.now().strftime("%Y-%m")
#         return self.conn.execute("SELECT category, SUM(amount) FROM journal WHERE type='expense' AND date LIKE ? GROUP BY category", (f"{month}%",)).fetchall()

#     def get_history(self, date_str):
#         return self.conn.execute("SELECT * FROM journal WHERE date = ?", (date_str,)).fetchall()

# # ==========================================
# # 3. ЛОГІКА ІНТЕРФЕЙСУ (Keyboards)
# # ==========================================
# class UI:
#     @staticmethod
#     def main_menu():
#         return ReplyKeyboardMarkup(keyboard=[
#             [KeyboardButton(text="💸 Витрати"), KeyboardButton(text="💰 Дохід")],
#             [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🏦 Баланс")],
#             [KeyboardButton(text="🔍 Пошук/Видалити")]
#         ], resize_keyboard=True, is_persistent=True)

#     @staticmethod
#     def cats_menu(items):
#         btns = [KeyboardButton(text=i) for i in items]
#         return ReplyKeyboardMarkup(keyboard=[btns[i:i+3] for i in range(0, len(btns), 3)], resize_keyboard=True)

# # ==========================================
# # 4. ХЕНДЛЕРИ ТА СТАНИ (Logic)
# # ==========================================
# db = FinanceDB()
# bot = Bot(token=API_TOKEN)
# dp = Dispatcher()

# class FinanceStates(StatesGroup):
#     choosing_cat = State()
#     entering_amount = State()
#     searching_date = State()

# @dp.message(Command("start"))
# async def cmd_start(message: types.Message):
#     name = USER_MAP.get(message.from_user.id, "Користувачу")
#     await message.answer(f"Привіт, {name}! Я готовий рахувати гроші.", reply_markup=UI.main_menu())

# @dp.message(F.text.in_(["💸 Витрати", "💰 Дохід"]))
# async def init_trans(message: types.Message, state: FSMContext):
#     mode = "expense" if "Витрати" in message.text else "income"
#     cats = EXPENSE_CATS if mode == "expense" else INCOME_CATS
#     await state.update_data(mode=mode)
#     await message.answer("Оберіть категорію:", reply_markup=UI.cats_menu(cats))
#     await state.set_state(FinanceStates.choosing_cat)

# @dp.message(FinanceStates.choosing_cat)
# async def process_cat(message: types.Message, state: FSMContext):
#     await state.update_data(cat=message.text)
#     await message.answer(f"Введіть суму (можна з описом, напр: 'штукатурка 1200'):", reply_markup=types.ReplyKeyboardRemove())
#     await state.set_state(FinanceStates.entering_amount)

# @dp.message(FinanceStates.entering_amount)
# async def process_amount(message: types.Message, state: FSMContext):
#     # Формуємо кнопки під повідомленням
#     buttons = [[InlineKeyboardButton(text="Скасувати ↩️", callback_data=f"del_{last_id}")]]
    
#     res_text = f"✅ Записано: {data['cat']} — {amount} грн."
    
#     # Якщо це дохід — додаємо кнопку для швидкого відкладання 10%
#     if data['mode'] == "income":
#         save_val = round(amount * 0.1, 2)
#         # Додаємо кнопку, яка передає суму оригінального доходу через callback_data
#         buttons.append([InlineKeyboardButton(
#             text=f"💎 Відкласти 10% ({save_val} грн)", 
#             callback_data=f"save10_{amount}"
#         )])
#         res_text += f"\n\n💡 Не забудь відкласти {save_val} грн!"
#     @dp.callback_query(F.data.startswith("save10_"))
#     async def callback_save_money(callback: types.CallbackQuery):
#         # Отримуємо суму доходу з callback_data
#         income_amount = float(callback.data.split("_")[1])
    
#         # Викликаємо метод БД для переказу коштів
#         saved = db.save_ten_percent(callback.from_user.id, income_amount)
    
#         # Редагуємо повідомлення, щоб підтвердити дію
#         await callback.message.edit_text(f"💎 Успішно! {saved} грн перераховано в заощадження.")
#         wait callback.answer("Гроші відкладено!")
#         ikb = InlineKeyboardMarkup(inline_keyboard=buttons)
#     await message.answer(res_text, reply_markup=get_main_kb())
#     await message.answer("Дії з записом:", reply_markup=ikb)

# @dp.message(F.text == "📊 Статистика")
# async def show_stats(message: types.Message):
#     rows = db.get_stats_monthly()
#     if not rows: return await message.answer("Цього місяця витрат немає.")
    
#     report = "📊 **Витрати за місяць:**\n" + "\n".join([f"• {r[0]}: {r[1]:.2f} грн" for r in rows])
#     await message.answer(report, parse_mode="Markdown")

# @dp.message(F.text == "🏦 Баланс")
# async def show_balance(message: types.Message):
#     balances = db.get_all_balances()
#     if not balances:
#         return await message.answer("Дані про баланс відсутні.")
    
#     # Формуємо гарне повідомлення
#     report = "🏦 **Поточний стан рахунків:**\n\n"
#     for b in balances:
#         name = b['name']
#         val = b['value']
        
#         # Додаємо іконки для краси
#         icon = "💵" if name == "UAH" else "💰"
#         if name == "USD": icon = "💵"
#         if name == "EUR": icon = "💶"
#         if name == "COINS": icon = "🪙"
        
#         report += f"{icon} {name}: {val:.2f}\n"
        
#     await message.answer(report, parse_mode="Markdown")


# @dp.message(F.text == "🔍 Пошук/Видалити")
# async def search_init(message: types.Message, state: FSMContext):
#     await message.answer("Введіть дату (напр. 2024-05-20):")
#     await state.set_state(FinanceStates.searching_date)

# @dp.message(FinanceStates.searching_date)
# async def search_res(message: types.Message, state: FSMContext):
#     history = db.get_history(message.text)
#     if not history: return await message.answer("Нічого не знайдено.")
#     @dp.callback_query(F.data.startswith("save10_"))
#     async def callback_save_money(callback: types.CallbackQuery):
#         # Отримуємо суму доходу з callback_data
#         income_amount = float(callback.data.split("_")[1])
    
#         # Викликаємо метод БД для переказу коштів
#     saved = db.save_ten_percent(callback.from_user.id, income_amount)
    
#         # Редагуємо повідомлення, щоб підтвердити дію
#         await callback.message.edit_text(f"💎 Успішно! {saved} грн перераховано в заощадження.")
#         await callback.answer("Гроші відкладено!")
    
#     for r in history:
#         ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Видалити 🗑️", callback_data=f"del_{r['id']}")]])
#         await message.answer(f"{r['user_name']}: {r['category']} ({r['sub']}) - {r['amount']} грн", reply_markup=ikb)
#     await state.clear()

# @dp.callback_query(F.data.startswith("del_"))
# async def delete_cb(callback: types.CallbackQuery):
#     entry_id = callback.data.split("_")[1]
#     @dp.callback_query(F.data.startswith("save10_"))
#     async def callback_save_money(callback: types.CallbackQuery):
#         # Отримуємо суму доходу з callback_data
#         income_amount = float(callback.data.split("_")[1])
    
#         # Викликаємо метод БД для переказу коштів
#         saved = db.save_ten_percent(callback.from_user.id, income_amount)
    
#         # Редагуємо повідомлення, щоб підтвердити дію
#         await callback.message.edit_text(f"💎 Успішно! {saved} грн перераховано в заощадження.")
#         await callback.answer("Гроші відкладено!")
#     if db.delete_entry(entry_id):
#         await callback.message.edit_text("❌ Запис видалено, баланс перераховано.")
#     await callback.answer()

# async def main():
#     logging.basicConfig(level=logging.INFO)
#     await dp.start_polling(bot)

# if __name__ == "__main__":
#     asyncio.run(main())





import logging
import asyncio
import re
import sqlite3
from datetime import datetime
from difflib import get_close_matches

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# 1. КОНФІГУРАЦІЯ ТА НАЛАШТУВАННЯ
# ==========================================
API_TOKEN = '8517651425:AAEKUffGx0dmj73YLOwEiFcqnrdOofpVwPU'

USER_MAP = {
    847387368: "Міша",
    854570254: "Настя"
}

EXPENSE_CATS = ["🛒 Продукти", "⚡ Комунальні", "🏠 Для дому", "🏗️ Ремонт", "🚗 Транспорт", 
                "🐱 Тварини", "💊 Здоров'я", "👕 Одяг", "🎉 Відпочинок", "🧴 Догляд", "💸 Борг", "❓ Інше"]

INCOME_CATS = ["💼 Зарплата", "🎁 Премія", "💳 Кешбек", "📈 Відсотки", "🪙 Копійки", "📦 Продаж", "🧧 Подарунок"]

# ==========================================
# 2. МОДУЛЬ БАЗИ ДАНИХ
# ==========================================
class FinanceDB:
    def __init__(self, db_path="finance.db"):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def get_all_balances(self):
        with self.conn:
            return self.conn.execute("SELECT name, value FROM balances").fetchall()

    def save_ten_percent(self, user_id, original_amount):
        savings_amount = round(original_amount * 0.1, 2)
        user_name = USER_MAP.get(user_id, "Гість")
        date = datetime.now().strftime("%Y-%m-%d")
        with self.conn:
            self.conn.execute("""INSERT INTO journal (user_name, type, category, sub, amount, currency, date) 
                               VALUES (?, 'expense', '🏦 Заощадження', 'Авто 10%', ?, 'UAH', ?)""",
                              (user_name, savings_amount, date))
            self.conn.execute("UPDATE balances SET value = value - ? WHERE name = 'UAH'", (savings_amount,))
            self.conn.execute("UPDATE balances SET value = value + ? WHERE name = 'SAVINGS'", (savings_amount,))
        return savings_amount

    def create_tables(self):
        with self.conn:
            self.conn.execute("""CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                user_name TEXT, type TEXT, category TEXT, sub TEXT, 
                amount REAL, currency TEXT, date TEXT)""")
            self.conn.execute("CREATE TABLE IF NOT EXISTS balances (name TEXT PRIMARY KEY, value REAL)")
            for b in ['UAH', 'USD', 'EUR', 'COINS', 'SAVINGS']:
                self.conn.execute("INSERT OR IGNORE INTO balances VALUES (?, 0)", (b,))

    def add_entry(self, user_id, t_type, cat, sub, amount, curr='UAH'):
        user_name = USER_MAP.get(user_id, "Гість")
        date = datetime.now().strftime("%Y-%m-%d")
        with self.conn:
            self.conn.execute("INSERT INTO journal (user_name, type, category, sub, amount, currency, date) VALUES (?,?,?,?,?,?,?)",
                              (user_name, t_type, cat, sub, amount, curr, date))
            mod = 1 if t_type == 'income' else -1
            target_wallet = 'COINS' if cat == "🪙 Копійки" else curr
            self.conn.execute("UPDATE balances SET value = value + ? WHERE name = ?", (amount * mod, target_wallet))
        return self.get_last_id()

    def get_last_id(self):
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def delete_entry(self, entry_id):
        with self.conn:
            entry = self.conn.execute("SELECT * FROM journal WHERE id = ?", (entry_id,)).fetchone()
            if entry:
                mod = -1 if entry['type'] == 'income' else 1
                self.conn.execute("UPDATE balances SET value = value + ? WHERE name = ?", (entry['amount'] * mod, entry['currency']))
                self.conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
                return True
        return False

    def get_stats_monthly(self):
        month = datetime.now().strftime("%Y-%m")
        return self.conn.execute("SELECT category, SUM(amount) FROM journal WHERE type='expense' AND date LIKE ? GROUP BY category", (f"{month}%",)).fetchall()

    def get_history(self, date_str):
        return self.conn.execute("SELECT * FROM journal WHERE date = ?", (date_str,)).fetchall()

# ==========================================
# 3. ЛОГІКА ІНТЕРФЕЙСУ
# ==========================================
class UI:
    @staticmethod
    def main_menu():
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="💸 Витрати"), KeyboardButton(text="💰 Дохід")],
            [KeyboardButton(text="📊 Статистика"), KeyboardButton(text="🏦 Баланс")],
            [KeyboardButton(text="🔍 Пошук/Видалити")]
        ], resize_keyboard=True, is_persistent=True)

    @staticmethod
    def cats_menu(items):
        btns = [KeyboardButton(text=i) for i in items]
        rows = [btns[i:i+3] for i in range(0, len(btns), 3)]
        rows.append([KeyboardButton(text="🔙 Назад")]) # КНОПКА НАЗАД
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

# ==========================================
# 4. ХЕНДЛЕРИ
# ==========================================
db = FinanceDB()
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

class FinanceStates(StatesGroup):
    choosing_cat = State()
    entering_amount = State()
    searching_date = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    name = USER_MAP.get(message.from_user.id, "Користувачу")
    await message.answer(f"Привіт, {name}!", reply_markup=UI.main_menu())

@dp.message(F.text == "🔙 Назад")
async def process_back(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Головне меню", reply_markup=UI.main_menu())

@dp.message(F.text.in_(["💸 Витрати", "💰 Дохід"]))
async def init_trans(message: types.Message, state: FSMContext):
    mode = "expense" if "Витрати" in message.text else "income"
    cats = EXPENSE_CATS if mode == "expense" else INCOME_CATS
    await state.update_data(mode=mode)
    await message.answer("Оберіть категорію:", reply_markup=UI.cats_menu(cats))
    await state.set_state(FinanceStates.choosing_cat)

@dp.message(FinanceStates.choosing_cat)
async def process_cat(message: types.Message, state: FSMContext):
    await state.update_data(cat=message.text)
    await message.answer(f"Введіть суму:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(FinanceStates.entering_amount)

@dp.message(FinanceStates.entering_amount)
async def process_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()
    match = re.search(r"(\d+(\.\d+)?)", message.text)
    if not match: return await message.answer("Введіть число.")
    
    amount = float(match.group(1))
    sub = message.text.replace(match.group(1), "").strip() or "Загальне"
    last_id = db.add_entry(message.from_user.id, data['mode'], data['cat'], sub, amount)
    
    buttons = [[InlineKeyboardButton(text="Скасувати ↩️", callback_data=f"del_{last_id}")]]
    res_text = f"✅ Записано: {data['cat']} — {amount} грн."
    
    if data['mode'] == "income":
        save_val = round(amount * 0.1, 2)
        buttons.append([InlineKeyboardButton(text=f"💎 Відкласти 10% ({save_val} грн)", callback_data=f"save10_{amount}")])
    
    await message.answer(res_text, reply_markup=UI.main_menu())
    await message.answer("Дії:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.clear()

@dp.callback_query(F.data.startswith("save10_"))
async def callback_save_money(callback: types.CallbackQuery):
    income_amount = float(callback.data.split("_")[1])
    saved = db.save_ten_percent(callback.from_user.id, income_amount)
    await callback.message.edit_text(f"💎 Успішно! {saved} грн відкладено.")
    await callback.answer()

@dp.message(F.text == "📊 Статистика")
async def show_stats(message: types.Message):
    rows = db.get_stats_monthly()
    if not rows: return await message.answer("Немає даних.")
    report = "📊 **Витрати:**\n" + "\n".join([f"• {r[0]}: {r[1]:.2f} грн" for r in rows])
    await message.answer(report, parse_mode="Markdown")

@dp.message(F.text == "🏦 Баланс")
async def show_balance(message: types.Message):
    balances = db.get_all_balances()
    report = "🏦 **Баланс:**\n\n"
    icons = {"UAH": "💵", "USD": "💵", "EUR": "💶", "COINS": "🪙", "SAVINGS": "💎"}
    for b in balances:
        report += f"{icons.get(b['name'], '💰')} {b['name']}: {b['value']:.2f}\n"
    await message.answer(report, parse_mode="Markdown")

@dp.message(F.text == "🔍 Пошук/Видалити")
async def search_init(message: types.Message, state: FSMContext):
    await message.answer("Введіть дату (2024-05-20):")
    await state.set_state(FinanceStates.searching_date)

@dp.message(FinanceStates.searching_date)
async def search_res(message: types.Message, state: FSMContext):
    history = db.get_history(message.text)
    if not history: return await message.answer("Нічого не знайдено.")
    for r in history:
        ikb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Видалити 🗑️", callback_data=f"del_{r['id']}")]])
        await message.answer(f"{r['category']} - {r['amount']} грн", reply_markup=ikb)
    await state.clear()

@dp.callback_query(F.data.startswith("del_"))
async def delete_cb(callback: types.CallbackQuery):
    if db.delete_entry(callback.data.split("_")[1]):
        await callback.message.edit_text("❌ Видалено.")
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())