import telebot
import mysql.connector
from mysql.connector import Error
import time
from telebot import types
import threading

# --- НАСТРОЙКИ ---
TOKEN = '8285671558:AAHsrgoANT0OjE4yy1G_frBktvkkdUauT-Y'
PASSWORD_PHRASE = "EasyShift123"

# Данные твоего сервера SpaceWeb
DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'port': 3308
}

bot = telebot.TeleBot(TOKEN)
active_sessions = set()
last_order_id = 0

# --- ФУНКЦИИ РАБОТЫ С БД ---

def get_db_connection():
    """Создает надежное подключение к БД"""
    return mysql.connector.connect(**DB_CONFIG)

def fetch_orders(last_id):
    """Получает новые заказы из базы"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Запрос с объединением таблиц для получения имен коктейлей и юзернеймов
        query = """
            SELECT o.order_id, o.status, o.comment, 
                   u.tg_username, c.name as cocktail_name 
            FROM Orders o 
            LEFT JOIN Users u ON o.user_id = u.user_id 
            LEFT JOIN Cocktails c ON o.cocktail_id = c.id
            WHERE o.order_id > %s
            ORDER BY o.order_id ASC
        """
        cursor.execute(query, (last_id,))
        rows = cursor.fetchall()
        cursor.close()
        return rows
    except Error as e:
        print(f"Ошибка БД: {e}")
        return []
    finally:
        if conn and conn.is_connected():
            conn.close()

def update_order_status(order_id, new_status):
    """Обновляет статус заказа в базе"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE Orders SET status = %s WHERE order_id = %s", (new_status, order_id))
        conn.commit()
        cursor.close()
        return True
    except Error as e:
        print(f"Ошибка обновления: {e}")
        return False
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- ЛОГИКА БОТА ---

def monitor():
    """Фоновая проверка заказов каждые 15 секунд"""
    global last_order_id
    print(f"--- МОНИТОРИНГ ЗАПУЩЕН (SpaceWeb IP: 77.222.40.251) ---")
    
    while True:
        # Мониторим, только если есть хоть один авторизованный админ
        if active_sessions:
            new_orders = fetch_orders(last_order_id)
            for order in new_orders:
                oid = order['order_id']
                last_order_id = oid
                
                # Формируем сообщение
                text = (f"🆕 *ЗАКАЗ №{oid}*\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🍹 *Коктейль:* {order['cocktail_name']}\n"
                        f"👤 *Клиент:* @{order['tg_username'] or 'N/A'}\n"
                        f"📝 *Коммент:* {order['comment'] or 'нет'}")
                
                # Кнопки
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{oid}"),
                    types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{oid}")
                )
                
                for admin_id in active_sessions:
                    try:
                        bot.send_message(admin_id, text, reply_markup=markup, parse_mode="Markdown")
                    except:
                        pass
        time.sleep(15)

# --- ОБРАБОТЧИКИ КОМАНД ---

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "🤖 Бар-система активна. Введите пароль:")

@bot.message_handler(func=lambda m: m.text == PASSWORD_PHRASE)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ разрешен! Теперь вы получаете уведомления.")

@bot.callback_query_handler(func=lambda call: True)
def callback_handle(call):
    action, oid = call.data.split('_')
    status = 'ready' if action == 'done' else 'cancelled'
    
    if update_order_status(oid, status):
        status_msg = "✅ Выполнен" if action == 'done' else "❌ Отменен"
        bot.edit_message_text(f"Заказ #{oid}: {status_msg}", call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "Ошибка связи с БД")

if __name__ == '__main__':
    # Запуск мониторинга в отдельном потоке
    threading.Thread(target=monitor, daemon=True).start()
    # Запуск бота
    print("Бот запущен...")
    bot.infinity_polling()
