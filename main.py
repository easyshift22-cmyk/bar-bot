import telebot
import mysql.connector
from mysql.connector import Error
import time
from telebot import types
import threading

# --- НАСТРОЙКИ ---
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y'
PASSWORD_PHRASE = "EasyShift123"

DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'port': 3308,
    'charset': 'utf8mb4',
    'use_unicode': True
}

bot = telebot.TeleBot(TOKEN)
active_sessions = set() # ID админов, которые ввели пароль
admin_messages = {}     # Хранилище {order_id: {admin_id: message_id}} для синхронизации

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

# --- ЛОГИКА ОБНОВЛЕНИЯ ИНТЕРФЕЙСА ---

def sync_status_update(order_id, new_status):
    """Обновляет сообщение у всех админов при изменении статуса"""
    status_map = {
        'new': '🆕 Новый',
        'ready': '✅ Готов',
        'cancelled': '❌ Отменён'
    }
    status_text = status_map.get(new_status, new_status)
    
    if order_id in admin_messages:
        for admin_id, msg_id in admin_messages[order_id].items():
            try:
                # В реальном приложении здесь стоило бы пересобрать весь текст, 
                # но для краткости просто уведомляем о финальном статусе
                bot.edit_message_text(
                    chat_id=admin_id,
                    message_id=msg_id,
                    text=f"Заказ №{order_id} переведен в статус: {status_text}",
                    reply_markup=None # Убираем кнопки после финализации
                )
            except:
                pass

# --- МОНИТОРИНГ ---

def monitor():
    print("--- МОНИТОРИНГ ЗАПУЩЕН (интервал 20 сек) ---")
    while True:
        if active_sessions:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # Ищем не оповещенные заказы (is_notified = 0)
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
                    
                    # Формируем текст с колонкой статуса
                    status_display = "🆕 Новый" if order['status'] == 'new' else order['status']
                    text = (f"📦 *ЗАКАЗ №{oid}*\n"
                            f"🍹 *Коктейль:* {order['c_name']}\n"
                            f"👤 *Клиент:* @{order['tg_username'] or 'N/A'}\n"
                            f"📝 *Коммент:* {order['comment'] or '-'}\n"
                            f"📊 *Статус:* {status_display}")
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
                        types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
                    )
                    
                    if oid not in admin_messages:
                        admin_messages[oid] = {}

                    for admin_id in active_sessions:
                        try:
                            msg = bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
                            admin_messages[oid][admin_id] = msg.message_id
                        except: pass

                    # Помечаем как оповещенный
                    cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (oid,))
                    conn.commit()

                cursor.close()
                conn.close()
            except Exception as e:
                print(f"Ошибка мониторинга: {e}")
                if conn: conn.close()
        
        time.sleep(20)

# --- ОБРАБОТКА КНОПОК ---

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    data = call.data.split('_')
    action = data[0] # conf (подтверждение) или set (финал)
    state = data[1]  # ready или cancel
    oid = data[2]    # ID заказа

    # 1 ЭТАП: Запрос подтверждения
    if action == "conf":
        confirm_markup = types.InlineKeyboardMarkup()
        confirm_markup.add(
            types.InlineKeyboardButton("Да, уверен", callback_data=f"set_{state}_{oid}"),
            types.InlineKeyboardButton("Назад", callback_data=f"back_{oid}")
        )
        confirm_text = "Вы точно хотите ОТМЕНИТЬ заказ?" if state == "cancel" else "Подтвердить ГОТОВНОСТЬ заказа?"
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=confirm_markup)
        bot.answer_callback_query(call.id, confirm_text)

    # 2 ЭТАП: Финальное действие
    elif action == "set":
        db_status = 'ready' if state == 'ready' else 'cancelled'
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = %s WHERE order_id = %s", (db_status, oid))
            conn.commit()
            conn.close()
            
            # Синхронизируем статус у всех админов
            sync_status_update(oid, db_status)
            bot.answer_callback_query(call.id, "Статус обновлен")
        except:
            bot.answer_callback_query(call.id, "Ошибка БД")

    # Возврат назад (отмена подтверждения)
    elif action == "back":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
            types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
        )
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=markup)

# --- СТАНДАРТНЫЕ КОМАНДЫ ---

@bot.message_handler(func=lambda m: m.text == PASSWORD_PHRASE)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ разрешен! Вы будете получать уведомления каждые 20 сек.")

if __name__ == '__main__':
    threading.Thread(target=monitor, daemon=True).start()
    bot.infinity_polling()
