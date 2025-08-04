import asyncio
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=TOKEN)

async def check_bookings_loop():
    while True:
        now = datetime.now()

        conn = sqlite3.connect("users.db")
        cursor = conn.cursor()

        # --- Удаление конфликтующих записей ---
        cursor.execute("""
            SELECT id, telegram_id, date, time_from, time_to
            FROM bookings
            WHERE confirmed >= 0
            ORDER BY date, time_from
        """)
        bookings = cursor.fetchall()

        booked_map = {}  # (date, hour) → booking_id

        for b_id, user_id, date_str, t_from, t_to in bookings:
            for h in range(int(t_from), int(t_to)):
                key = (date_str, h)
                if key in booked_map:
                    # Конфликт: отменяем эту запись
                    cursor.execute("UPDATE bookings SET confirmed = -1 WHERE id = ?", (b_id,))
                    conn.commit()

                    # Уведомим пользователя
                    await bot.send_message(
                        user_id,
                        "⚠️ Ваша запись была автоматически отменена, т.к. кто-то уже занял это время."
                    )
                else:
                    booked_map[key] = b_id

        # --- Получаем все записи для уведомлений ---
        cursor.execute("""
            SELECT id, telegram_id, date, time_from, time_to, confirmed
            FROM bookings
        """)
        rows = cursor.fetchall()

        for booking_id, user_id, date_str, time_from, time_to, confirmed in rows:
            dt_start = datetime.strptime(f"{date_str} {int(time_from) % 24:02d}:00", "%Y-%m-%d %H:%M")
            dt_end = datetime.strptime(f"{date_str} {int(time_to) % 24:02d}:00", "%Y-%m-%d %H:%M")
            diff = dt_start - now

            if int(time_from) > 23:
                time_from = int(time_from) - 24
            if int(time_to) > 23:
                time_to = int(time_to) - 24

            # --- Уведомление за 24 часа ---
            if confirmed >= 0 and 23.9 < diff.total_seconds() / 3600 < 24.1:
                await bot.send_message(
                    user_id,
                    f"📅 До вашей записи осталось 24 часа!\nДата: {date_str}, Время: {time_from:02d}:00–{time_to:02d}:00"
                )

            # --- Подтверждение за 1 час ---
            elif confirmed == 0 and 0.9 < diff.total_seconds() / 3600 < 1.1:
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Я приду", callback_data=f"confirm_booking|{booking_id}")]
                ])
                await bot.send_message(
                    user_id,
                    f"⏰ Ваша сессия скоро начнётся!\nПодтвердите, что вы придёте.",
                    reply_markup=kb
                )

            # --- Автоотмена за 10 минут до начала ---
            elif confirmed == 0 and 0 < diff.total_seconds() < 600:
                cursor.execute("UPDATE bookings SET confirmed = -1 WHERE id = ?", (booking_id,))
                conn.commit()
                await bot.send_message(
                    user_id,
                    "❌ Ваша запись была отменена, так как вы не подтвердили участие за 10 минут до начала."
                )

        # --- Отправка администратору для завершённых ---
        cursor.execute("""
            SELECT id, telegram_id, date, time_from, time_to
            FROM bookings
            WHERE confirmed = 1
        """)
        passed = cursor.fetchall()

        for b_id, user_id, date_str, t_from, t_to in passed:
            dt_end = datetime.strptime(f"{date_str} {int(t_to) % 24:02d}:00", "%Y-%m-%d %H:%M")
            if dt_end < now:
                cursor.execute("UPDATE bookings SET confirmed = 3 WHERE id = ?", (b_id,))
                conn.commit()

                try:
                    user = await bot.get_chat(user_id)
                    username = f"@{user.username}" if user.username else f"id:{user.id}"
                except:
                    username = f"id:{user_id}"

                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Пришёл", callback_data=f"user_came|{b_id}")]
                ])
                await bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        f"📌 <b>Прошла запись пользователя</b> {username}\n"
                        f"📅 {date_str} ⏰ {t_from}:00–{t_to}:00\n\n"
                        f"Нажмите, если он <b>пришёл</b> ⬇️"
                    ),
                    reply_markup=kb,
                    parse_mode="HTML"
                )

        conn.close()
        await asyncio.sleep(60)
