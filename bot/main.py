import asyncio
import logging
import re
import sqlite3
import os
from dotenv import load_dotenv
from datetime import datetime
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

load_dotenv(Path(__file__).with_name(".env"))
API_TOKEN = os.environ["BOT_TOKEN"]

DB_PATH = Path(__file__).with_name("finance.db")

USER_MAP = {
    847387368: "Міша",
    854570254: "Настя",
}

EXPENSE_CATS = [
    "🛒 Продукти",
    "⚡ Комунальні",
    "🏠 Для дому",
    "🏗️ Ремонт",
    "🚗 Транспорт",
    "🐱 Тварини",
    "💊 Здоров'я",
    "👕 Одяг",
    "🎉 Відпочинок",
    "🧴 Догляд",
    "💸 Борг",
    "❓ Інше",
]

INCOME_CATS = [
    "💼 Зарплата",
    "🎁 Премія",
    "💳 Кешбек",
    "📈 Відсотки",
    "🪙 Копійки",
    "📦 Продаж",
    "🧧 Подарунок",
]


class FinanceDB:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.create_tables()

    def create_tables(self):
        with self.conn:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT,
                    type TEXT,
                    category TEXT,
                    sub TEXT,
                    amount REAL,
                    currency TEXT,
                    date TEXT
                )"""
            )
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS balances (name TEXT PRIMARY KEY, value REAL)"
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS monthly_expense_plans (
                    month TEXT NOT NULL,
                    category TEXT NOT NULL,
                    planned_amount REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (month, category)
                )"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS monthly_category_totals (
                    month TEXT NOT NULL,
                    category TEXT NOT NULL,
                    actual_amount REAL NOT NULL DEFAULT 0,
                    planned_amount REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (month, category)
                )"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS yearly_category_totals (
                    year TEXT NOT NULL,
                    category TEXT NOT NULL,
                    actual_amount REAL NOT NULL DEFAULT 0,
                    planned_amount REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (year, category)
                )"""
            )
            for balance in ["UAH", "USD", "EUR", "COINS", "SAVINGS"]:
                self.conn.execute(
                    "INSERT OR IGNORE INTO balances VALUES (?, 0)", (balance,)
                )

    def get_all_balances(self):
        return self.conn.execute("SELECT name, value FROM balances").fetchall()

    def add_entry(self, user_id, t_type, cat, sub, amount, curr="UAH"):
        user_name = USER_MAP.get(user_id, "Гість")
        date = datetime.now().strftime("%Y-%m-%d")
        with self.conn:
            self.conn.execute(
                """INSERT INTO journal
                   (user_name, type, category, sub, amount, currency, date)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_name, t_type, cat, sub, amount, curr, date),
            )
            mod = 1 if t_type == "income" else -1
            target_wallet = "COINS" if cat == "🪙 Копійки" else curr
            self.conn.execute(
                "UPDATE balances SET value = value + ? WHERE name = ?",
                (amount * mod, target_wallet),
            )
        self.refresh_current_totals()
        return self.get_last_id()

    def get_last_id(self):
        return self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def delete_entry(self, entry_id):
        with self.conn:
            entry = self.conn.execute(
                "SELECT * FROM journal WHERE id = ?", (entry_id,)
            ).fetchone()
            if not entry:
                return False

            mod = -1 if entry["type"] == "income" else 1
            self.conn.execute(
                "UPDATE balances SET value = value + ? WHERE name = ?",
                (entry["amount"] * mod, entry["currency"]),
            )
            self.conn.execute("DELETE FROM journal WHERE id = ?", (entry_id,))
        self.refresh_current_totals()
        return True

    def save_ten_percent(self, user_id, original_amount):
        savings_amount = round(original_amount * 0.1, 2)
        user_name = USER_MAP.get(user_id, "Гість")
        date = datetime.now().strftime("%Y-%m-%d")
        with self.conn:
            self.conn.execute(
                """INSERT INTO journal
                   (user_name, type, category, sub, amount, currency, date)
                   VALUES (?, 'expense', '🏦 Заощадження', 'Авто 10%', ?, 'UAH', ?)""",
                (user_name, savings_amount, date),
            )
            self.conn.execute(
                "UPDATE balances SET value = value - ? WHERE name = 'UAH'",
                (savings_amount,),
            )
            self.conn.execute(
                "UPDATE balances SET value = value + ? WHERE name = 'SAVINGS'",
                (savings_amount,),
            )
        self.refresh_current_totals()
        return savings_amount

    def set_month_plan(self, month, category, planned_amount):
        now = datetime.now().isoformat(timespec="seconds")
        with self.conn:
            self.conn.execute(
                """INSERT INTO monthly_expense_plans
                   (month, category, planned_amount, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(month, category) DO UPDATE SET
                       planned_amount = excluded.planned_amount,
                       updated_at = excluded.updated_at""",
                (month, category, planned_amount, now),
            )
        self.refresh_period_totals(month)

    def get_history(self, date_str):
        return self.conn.execute(
            "SELECT * FROM journal WHERE date = ? ORDER BY id DESC", (date_str,)
        ).fetchall()

    def get_monthly_expense_report(self, month=None):
        month = month or datetime.now().strftime("%Y-%m")
        self.refresh_period_totals(month)
        return self.conn.execute(
            """SELECT category, actual_amount, planned_amount
               FROM monthly_category_totals
               WHERE month = ?
               ORDER BY category""",
            (month,),
        ).fetchall()

    def get_yearly_expense_report(self, year=None):
        year = year or datetime.now().strftime("%Y")
        self.refresh_year_totals(year)
        return self.conn.execute(
            """SELECT category, actual_amount, planned_amount
               FROM yearly_category_totals
               WHERE year = ?
               ORDER BY category""",
            (year,),
        ).fetchall()

    def refresh_current_totals(self):
        self.refresh_period_totals(datetime.now().strftime("%Y-%m"))

    def refresh_period_totals(self, month):
        now = datetime.now().isoformat(timespec="seconds")
        cats = self._categories_for_month(month)
        with self.conn:
            for cat in cats:
                actual = self._actual_for_category(month, cat)
                planned = self._planned_for_category(month, cat)
                self.conn.execute(
                    """INSERT INTO monthly_category_totals
                       (month, category, actual_amount, planned_amount, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(month, category) DO UPDATE SET
                           actual_amount = excluded.actual_amount,
                           planned_amount = excluded.planned_amount,
                           updated_at = excluded.updated_at""",
                    (month, cat, actual, planned, now),
                )
        self.refresh_year_totals(month[:4])

    def refresh_year_totals(self, year):
        now = datetime.now().isoformat(timespec="seconds")
        cats = set(EXPENSE_CATS)
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM journal WHERE type = 'expense' AND date LIKE ?",
            (f"{year}-%",),
        ).fetchall()
        cats.update(row["category"] for row in rows)
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM monthly_expense_plans WHERE month LIKE ?",
            (f"{year}-%",),
        ).fetchall()
        cats.update(row["category"] for row in rows)

        with self.conn:
            for cat in cats:
                actual = self.conn.execute(
                    """SELECT COALESCE(SUM(amount), 0)
                       FROM journal
                       WHERE type = 'expense' AND category = ? AND date LIKE ?""",
                    (cat, f"{year}-%"),
                ).fetchone()[0]
                planned = self.conn.execute(
                    """SELECT COALESCE(SUM(planned_amount), 0)
                       FROM monthly_expense_plans
                       WHERE category = ? AND month LIKE ?""",
                    (cat, f"{year}-%"),
                ).fetchone()[0]
                self.conn.execute(
                    """INSERT INTO yearly_category_totals
                       (year, category, actual_amount, planned_amount, updated_at)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(year, category) DO UPDATE SET
                           actual_amount = excluded.actual_amount,
                           planned_amount = excluded.planned_amount,
                           updated_at = excluded.updated_at""",
                    (year, cat, actual, planned, now),
                )

    def _categories_for_month(self, month):
        cats = set(EXPENSE_CATS)
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM journal WHERE type = 'expense' AND date LIKE ?",
            (f"{month}%",),
        ).fetchall()
        cats.update(row["category"] for row in rows)
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM monthly_expense_plans WHERE month = ?",
            (month,),
        ).fetchall()
        cats.update(row["category"] for row in rows)
        return sorted(cats)

    def _actual_for_category(self, month, category):
        return self.conn.execute(
            """SELECT COALESCE(SUM(amount), 0)
               FROM journal
               WHERE type = 'expense' AND category = ? AND date LIKE ?""",
            (category, f"{month}%"),
        ).fetchone()[0]

    def _planned_for_category(self, month, category):
        return self.conn.execute(
            """SELECT COALESCE(SUM(planned_amount), 0)
               FROM monthly_expense_plans
               WHERE month = ? AND category = ?""",
            (month, category),
        ).fetchone()[0]


class UI:
    @staticmethod
    def main_menu():
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="💸 Витрати"), KeyboardButton(text="💰 Дохід")],
                [
                    KeyboardButton(text="🗓 Витрати на місяць"),
                    KeyboardButton(text="📊 Статистика"),
                ],
                [KeyboardButton(text="🏦 Баланс"), KeyboardButton(text="🔍 Пошук/Видалити")],
            ],
            resize_keyboard=True,
            is_persistent=True,
        )

    @staticmethod
    def cats_menu(items):
        btns = [KeyboardButton(text=i) for i in items]
        rows = [btns[i : i + 3] for i in range(0, len(btns), 3)]
        rows.append([KeyboardButton(text="🔙 Назад")])
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

    @staticmethod
    def stats_menu():
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📅 Витрати за місяць")],
                [KeyboardButton(text="📆 Витрати за рік")],
                [KeyboardButton(text="🔙 Назад")],
            ],
            resize_keyboard=True,
        )


db = FinanceDB()
bot = Bot(token=API_TOKEN)
dp = Dispatcher()


class FinanceStates(StatesGroup):
    choosing_cat = State()
    entering_amount = State()
    searching_date = State()
    entering_month_plan = State()


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
    mode = "expense" if message.text == "💸 Витрати" else "income"
    cats = EXPENSE_CATS if mode == "expense" else INCOME_CATS
    await state.update_data(mode=mode)
    await message.answer("Оберіть категорію:", reply_markup=UI.cats_menu(cats))
    await state.set_state(FinanceStates.choosing_cat)


@dp.message(FinanceStates.choosing_cat)
async def process_cat(message: types.Message, state: FSMContext):
    await state.update_data(cat=message.text)
    await message.answer("Введіть суму:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(FinanceStates.entering_amount)


@dp.message(FinanceStates.entering_amount)
async def process_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()
    match = re.search(r"(\d+(?:[.,]\d+)?)", message.text)
    if not match:
        return await message.answer("Введіть число.")

    amount = float(match.group(1).replace(",", "."))
    sub = message.text.replace(match.group(1), "").strip() or "Загальне"
    last_id = db.add_entry(message.from_user.id, data["mode"], data["cat"], sub, amount)

    buttons = [
        [InlineKeyboardButton(text="Скасувати ↩️", callback_data=f"del_{last_id}")]
    ]
    res_text = f"✅ Записано: {data['cat']} — {amount:.2f} грн."

    if data["mode"] == "income":
        save_val = round(amount * 0.1, 2)
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"💎 Відкласти 10% ({save_val:.2f} грн)",
                    callback_data=f"save10_{amount}",
                )
            ]
        )

    await message.answer(res_text, reply_markup=UI.main_menu())
    await message.answer("Дії:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await state.clear()


@dp.message(F.text == "🗓 Витрати на місяць")
async def start_month_plan(message: types.Message, state: FSMContext):
    month = datetime.now().strftime("%Y-%m")
    await state.update_data(plan_month=month, plan_index=0)
    await ask_next_plan_category(message, state)


async def ask_next_plan_category(message: types.Message, state: FSMContext):
    data = await state.get_data()
    index = data["plan_index"]
    month = data["plan_month"]

    if index >= len(EXPENSE_CATS):
        await state.clear()
        db.refresh_period_totals(month)
        return await message.answer(
            f"✅ План витрат на {month} збережено.", reply_markup=UI.main_menu()
        )

    category = EXPENSE_CATS[index]
    await message.answer(
        f"{month}\n{category}\nВведіть планову суму або 0, якщо витрат не планується:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await state.set_state(FinanceStates.entering_month_plan)


@dp.message(FinanceStates.entering_month_plan)
async def process_month_plan_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()
    match = re.search(r"(\d+(?:[.,]\d+)?)", message.text)
    if not match:
        return await message.answer("Введіть суму числом. Якщо витрат не буде, введіть 0.")

    amount = float(match.group(1).replace(",", "."))
    index = data["plan_index"]
    month = data["plan_month"]
    db.set_month_plan(month, EXPENSE_CATS[index], amount)

    await state.update_data(plan_index=index + 1)
    await ask_next_plan_category(message, state)


@dp.callback_query(F.data.startswith("save10_"))
async def callback_save_money(callback: types.CallbackQuery):
    income_amount = float(callback.data.split("_")[1])
    saved = db.save_ten_percent(callback.from_user.id, income_amount)
    await callback.message.edit_text(f"💎 Успішно! {saved:.2f} грн відкладено.")
    await callback.answer()


@dp.message(F.text == "📊 Статистика")
async def show_stats_menu(message: types.Message):
    await message.answer("Оберіть статистику:", reply_markup=UI.stats_menu())


@dp.message(F.text == "📅 Витрати за місяць")
async def show_month_stats(message: types.Message):
    month = datetime.now().strftime("%Y-%m")
    rows = db.get_monthly_expense_report(month)
    actual_total = sum(row["actual_amount"] for row in rows)
    planned_total = sum(row["planned_amount"] for row in rows)
    lines = [
        f"📅 **Витрати за {month}:**",
        f"Факт: {actual_total:.2f} грн",
        f"План: {planned_total:.2f} грн",
        "",
    ]
    for row in rows:
        if row["actual_amount"] or row["planned_amount"]:
            lines.append(
                f"• {row['category']}: факт {row['actual_amount']:.2f} / план {row['planned_amount']:.2f} грн"
            )
    if len(lines) == 4:
        lines.append("Поки немає фактичних або запланованих витрат.")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(F.text == "📆 Витрати за рік")
async def show_year_stats(message: types.Message):
    year = datetime.now().strftime("%Y")
    rows = db.get_yearly_expense_report(year)
    actual_total = sum(row["actual_amount"] for row in rows)
    planned_total = sum(row["planned_amount"] for row in rows)
    lines = [
        f"📆 **Витрати за {year}:**",
        f"Факт: {actual_total:.2f} грн",
        f"План: {planned_total:.2f} грн",
        "",
    ]
    for row in rows:
        if row["actual_amount"] or row["planned_amount"]:
            lines.append(
                f"• {row['category']}: факт {row['actual_amount']:.2f} / план {row['planned_amount']:.2f} грн"
            )
    if len(lines) == 4:
        lines.append("Поки немає фактичних або запланованих витрат.")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(F.text == "🏦 Баланс")
async def show_balance(message: types.Message):
    balances = db.get_all_balances()
    report = "🏦 **Баланс:**\n\n"
    icons = {"UAH": "💵", "USD": "💵", "EUR": "💶", "COINS": "🪙", "SAVINGS": "💎"}
    for balance in balances:
        report += f"{icons.get(balance['name'], '💰')} {balance['name']}: {balance['value']:.2f}\n"
    await message.answer(report, parse_mode="Markdown")


@dp.message(F.text == "🔍 Пошук/Видалити")
async def search_init(message: types.Message, state: FSMContext):
    await message.answer("Введіть дату (2024-05-20):")
    await state.set_state(FinanceStates.searching_date)


@dp.message(FinanceStates.searching_date)
async def search_res(message: types.Message, state: FSMContext):
    history = db.get_history(message.text)
    if not history:
        return await message.answer("Нічого не знайдено.", reply_markup=UI.main_menu())

    for row in history:
        ikb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Видалити 🗑️", callback_data=f"del_{row['id']}"
                    )
                ]
            ]
        )
        await message.answer(
            f"{row['user_name']}: {row['category']} ({row['sub']}) - {row['amount']:.2f} грн",
            reply_markup=ikb,
        )
    await state.clear()


@dp.callback_query(F.data.startswith("del_"))
async def delete_cb(callback: types.CallbackQuery):
    if db.delete_entry(callback.data.split("_")[1]):
        await callback.message.edit_text("❌ Видалено. Баланс і статистику оновлено.")
    await callback.answer()


async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
