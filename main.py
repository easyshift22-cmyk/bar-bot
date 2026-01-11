import telebot
import mysql.connector
from mysql.connector import Error
import time
from telebot import types
import threading
import traceback

# --- НАСТРОЙКИ ---
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y'
PASSWORD_PHRASE = "EasyShift123"

DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'port': 3308,
    'charset': 'utf8mb4', # Исправляет "??????"
    'use_unicode': True
}

bot = telebot.TeleBot(TOKEN)
active_sessions = set() # Сет для ID админов
admin_messages = {}     # {order_id: {admin_id: message_id}} для синхронизации

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def send_debug(text):
    """Отправляет отладочную информацию всем залогиненным админам"""
    for admin_id in list(active_sessions):
        try:
            bot.send_message(admin_id, f"🔧 **DEBUG:**\n`{text}`", parse_mode="Markdown")
        except: pass

# --- МОНИТОРИНГ ---

def monitor():
    global active_sessions, admin_messages
    print("--- МОНИТОРИНГ ЗАПУЩЕН ---")
    
    while True:
        # Проверяем базу только если есть хоть один авторизованный админ
        if len(active_sessions) > 0:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # Ищем не оповещенные заказы
                query = """
                    SELECT o.order_id, o.status, o.comment, u.tg_username, c.name as c_name 
                    FROM Orders o 
                    LEFT JOIN Users u ON o.user_id = u.user_id 
                    LEFT JOIN Cocktails c ON o.cocktail_id = c.id
                    WHERE o.is_notified = 0
                """
                cursor.execute(query)
                new_orders = cursor.fetchall()

                for order in new_orders:
                    oid = order['order_id']
                    
                    # Формируем текст
                    status_text = "🆕 Новый" # Раз это новый заказ (is_notified=0)
                    text = (f"📦 *ЗАКАЗ №{oid}*\n"
                            f"🍹 *Коктейль:* {order['c_name']}\n"
                            f"👤 *Клиент:* @{order['tg_username'] or 'N/A'}\n"
                            f"📝 *Коммент:* {order['comment'] or '-'}\n"
                            f"📊 *Статус:* {status_text}")
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
                        types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
                    )
                    
                    if oid not in admin_messages:
                        admin_messages[oid] = {}

                    for admin_id in list(active_sessions):
                        try:
                            msg = bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
                            admin_messages[oid][admin_id] = msg.message_id
                        except: pass

                    # Помечаем в БД
                    cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (oid,))
                    conn.commit()

                cursor.close()
                conn.close()
            except Exception as e:
                error_stack = traceback.format_exc()
                print(f"Ошибка мониторинга: {e}")
                send_debug(error_stack) # Бот сам скажет, если упал запрос к БД
                if conn: conn.close()
        
        time.sleep(20) # Твой интервал

# --- ОБРАБОТЧИКИ ---

@bot.message_handler(func=lambda m: m.text == PASSWORD_PHRASE)
def auth(message):
    global active_sessions
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ разрешен! Ожидайте заказы.")
    print(f"Админ добавлен: {message.chat.id}. Всего: {len(active_sessions)}")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    global admin_messages
    data = call.data.split('_')
    if len(data) < 3: return # Защита от старых кнопок "done_id"

    action, state, oid = data[0], data[1], data[2]

    # Подтверждение
    if action == "conf":
        confirm_markup = types.InlineKeyboardMarkup()
        confirm_markup.add(
            types.InlineKeyboardButton("Да, уверен", callback_data=f"set_{state}_{oid}"),
            types.InlineKeyboardButton("Назад", callback_data=f"back_{oid}")
        )
        msg_text = "Подтвердить готовность?" if state == "ready" else "Точно отменить?"
        bot.answer_callback_query(call.id, msg_text)
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=confirm_markup)

    # Установка статуса
    elif action == "set":
        new_db_status = 'ready' if state == 'ready' else 'cancelled'
        status_label = "✅ ГОТОВ" if state == 'ready' else "❌ ОТМЕНЕН"
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = %s WHERE order_id = %s", (new_db_status, oid))
            conn.commit()
            conn.close()

            # Синхронизация: обновляем сообщение у всех админов
            if int(oid) in admin_messages:
                for admin_id, msg_id in admin_messages[int(oid)].items():
                    try:
                        bot.edit_message_text(
                            chat_id=admin_id,
                            message_id=msg_id,
                            text=f"📦 Заказ №{oid} завершен!\n📊 Статус: {status_label}",
                            reply_markup=None
                        )
                    except: pass
            bot.answer_callback_query(call.id, "Статус обновлен в базе")
        except Exception as e:
            send_debug(traceback.format_exc())

    # Назад
    elif action == "back":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
            types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
        )
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

if __name__ == '__main__':
    # Запускаем мониторинг
    t = threading.Thread(target=monitor, daemon=True)
    t.start()
    bot.infinity_polling()
