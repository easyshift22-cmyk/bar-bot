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
    'charset': 'utf8mb4',
    'use_unicode': True,
    'connect_timeout': 10
}

bot = telebot.TeleBot(TOKEN)
active_sessions = set() 
admin_messages = {}     # {order_id: {admin_id: message_id}}

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def sync_status_update(order_id, new_status):
    status_map = {
        'new': '🆕 Новый',
        'ready': '✅ Готов',
        'cancelled': '❌ Отменён'
    }
    status_text = status_map.get(new_status, new_status)
    
    if order_id in admin_messages:
        for admin_id, msg_id in admin_messages[order_id].items():
            try:
                bot.edit_message_text(
                    chat_id=admin_id,
                    message_id=msg_id,
                    text=f"📢 Заказ №{order_id} обновлен!\n📊 Статус: {status_text}",
                    reply_markup=None
                )
            except Exception as e:
                print(f"Ошибка синхронизации: {e}")

def monitor():
    global active_sessions, last_order_id
    print("--- СИСТЕМА МОНИТОРИНГА ЗАПУЩЕНА ---")
    
    while True:
        # Важно: проверяем, ввел ли кто-то пароль
        if len(active_sessions) > 0:
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor(dictionary=True)
                
                # Проверяем только необработанные заказы
                query = """
                    SELECT o.order_id, o.status, o.comment, u.tg_username, c.name as c_name 
                    FROM Orders o 
                    LEFT JOIN Users u ON o.user_id = u.user_id 
                    LEFT JOIN Cocktails c ON o.cocktail_id = c.id
                    WHERE o.is_notified = 0
                """
                cursor.execute(query)
                new_orders = cursor.fetchall()

                if new_orders:
                    print(f"Найдено новых заказов: {len(new_orders)}")

                for order in new_orders:
                    oid = order['order_id']
                    
                    text = (f"📦 *ЗАКАЗ №{oid}*\n"
                            f"🍹 *Коктейль:* {order['c_name']}\n"
                            f"👤 *Клиент:* @{order['tg_username'] or 'N/A'}\n"
                            f"📝 *Коммент:* {order['comment'] or '-'}\n"
                            f"📊 *Статус:* 🆕 Новый")
                    
                    markup = types.InlineKeyboardMarkup(row_width=2)
                    markup.add(
                        types.InlineKeyboardButton("✅ Применить", callback_data=f"conf_ready_{oid}"),
                        types.InlineKeyboardButton("❌ Отменить", callback_data=f"conf_cancel_{oid}")
                    )
                    
                    if oid not in admin_messages:
                        admin_messages[oid] = {}

                    # Рассылка всем авторизованным
                    for admin_id in list(active_sessions):
                        try:
                            msg = bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
                            admin_messages[oid][admin_id] = msg.message_id
                        except Exception as e:
                            print(f"Не удалось отправить админу {admin_id}: {e}")

                    # Помечаем в БД, что оповещение отправлено
                    cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (oid,))
                    conn.commit()
                    print(f"Заказ №{oid} успешно обработан.")

                cursor.close()
                conn.close()
            except Exception as e:
                print(f"!!! ОШИБКА БД В МОНИТОРИНГЕ !!!")
                print(traceback.format_exc())
                if conn: conn.close()
        else:
            # Если это сообщение спамит в консоль, можно закомментировать
            print("Ожидание авторизации админа (введите пароль в боте)...")
        
        time.sleep(20)

@bot.message_handler(func=lambda m: m.text == PASSWORD_PHRASE)
def auth(message):
    global active_sessions
    active_sessions.add(message.chat.id)
    print(f"Админ {message.chat.id} авторизован.")
    bot.send_message(message.chat.id, "🔓 Доступ разрешен! Ожидайте новые заказы.")

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    # Код обработки кнопок (conf/set/back) оставляем из предыдущего сообщения
    # ... (обязательно скопируй его из прошлого ответа полностью) ...
    pass # Замени на логику из прошлого сообщения

if __name__ == '__main__':
    # Запускаем мониторинг строго ПЕРЕД запуском бота
    t = threading.Thread(target=monitor, daemon=True)
    t.start()
    
    print("Бот запущен и ожидает сообщений...")
    bot.infinity_polling()
