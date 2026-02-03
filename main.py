import telebot
import mysql.connector
import time
import threading
from telebot import types
from mysql.connector import Error

# --- НАСТРОЙКИ ---
TOKEN = '8112243924:AAGv-nqJx-ld1oKm8fEQGk0-1J9eWs0A0Nk' 
bot = telebot.TeleBot(TOKEN)

DB_CONFIG = {
    'user': 'easyshift2',
    'password': 'EasyShift123321',
    'host': '77.222.40.251',
    'database': 'easyshift2',
    'port': 3308,
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'use_unicode': True
}

PASSWORD = "EasyShift123"
active_sessions = set()

def get_db_connection():
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"Ошибка подключения к БД: {e}")
        return None

# --- ФУНКЦИЯ СОЗДАНИЯ КЛАВИАТУРЫ ---
def get_order_markup(order_id, status='new'):
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if status == 'new':
        markup.add(
            types.InlineKeyboardButton("👨‍🍳 В процессе", callback_data=f"cook_{order_id}"),
            types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order_id}"),
            types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}")
        )
    elif status == 'cooking':
        markup.add(
            types.InlineKeyboardButton("✅ Готово", callback_data=f"done_{order_id}"),
            types.InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_{order_id}")
        )
    else: # ready или cancelled
        markup.add(types.InlineKeyboardButton("⬅️ Вернуть в список", callback_data=f"reset_{order_id}"))
    
    if status in ['new', 'cooking']:
        markup.add(types.InlineKeyboardButton("💬 Добавить комментарий", callback_data=f"comment_{order_id}"))

    markup.add(types.InlineKeyboardButton("🔄 Обновить статус", callback_data=f"refresh_{order_id}"))
    return markup

# --- ЛОГИКА МОНИТОРИНГА НОВЫХ ЗАКАЗОВ ---
def check_new_orders():
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT o.order_id, o.quantity, o.comment, o.BarmanComment, 
                   c.name as cocktail_name, c.CocktailType,
                   i.glassware, i.ing_1, i.qty_1, i.ing_2, i.qty_2, i.ing_3, i.qty_3,
                   i.ing_4, i.qty_4, i.ing_5, i.qty_5, i.ing_6, i.qty_6,
                   u.username, u.tg_username
            FROM Orders o
            JOIN Cocktails c ON o.cocktail_id = c.id
            LEFT JOIN Ingredients i ON c.id = i.cocktail_id
            LEFT JOIN Users u ON o.user_id = u.user_id
            WHERE o.is_notified = 0
        """
        cursor.execute(query)
        new_orders = cursor.fetchall()

        for order in new_orders:
            ingredients = []
            for num in range(1, 7):
                name, qty = order.get(f'ing_{num}'), order.get(f'qty_{num}')
                if name and name.strip(): ingredients.append(f"  🔹 {name}: {qty}")
            
            ing_text = "\n".join(ingredients) if ingredients else "  Состав не указан"
            b_comment = f"\n📝 **Бармен:** {order['BarmanComment']}" if order['BarmanComment'] else ""
            
            # Формируем данные клиента
            client_info = f"{order['username']} (tg: @{order['tg_username']})" if order['username'] else "Неизвестен"

            msg_text = (
                f"🆕 НОВЫЙ ЗАКАЗ №{order['order_id']}\n"
                f"━━━━━━━━━━━━━━\n"
                f"👤 Клиент: {client_info}\n"
                f"🍸 Коктейль: {order['cocktail_name']} ({order['CocktailType'] or 'Без типа'})\n"
                f"🥤 Тара: {order['glassware'] or 'Не указана'}\n"
                f"🔢 Количество: {order['quantity']}\n"
                f"💬 Коммент клиента: {order['comment'] if order['comment'] else '---'}"
                f"{b_comment}\n"
                f"━━━━━━━━━━━━━━\n"
                f"📜 СОСТАВ:\n{ing_text}"
            )

            markup = get_order_markup(order['order_id'], 'new')
            for admin_id in list(active_sessions):
                try: bot.send_message(admin_id, msg_text, reply_markup=markup, parse_mode="Markdown")
                except: pass
            cursor.execute("UPDATE Orders SET is_notified = 1 WHERE order_id = %s", (order['order_id'],))
        conn.commit()
    except Error as e: print(f"Ошибка мониторинга: {e}")
    finally:
        if conn.is_connected(): cursor.close(); conn.close()

# --- ОБРАБОТЧИК ДОБАВЛЕНИЯ КОММЕНТАРИЯ ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('comment_'))
def handle_add_comment(call):
    order_id = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"📝 Введите комментарий для заказа №{order_id}:")
    bot.register_next_step_handler(msg, process_barman_comment, order_id)
    bot.answer_callback_query(call.id)

def process_barman_comment(message, order_id):
    # Добавляем никнейм в скобках (берем username или имя, если юзернейма нет)
    nick = message.from_user.username or message.from_user.first_name
    full_comment = f"{message.text} ({nick})"
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            query = "UPDATE Orders SET BarmanComment = %s WHERE order_id = %s"
            cursor.execute(query, (full_comment, order_id))
            conn.commit()
            bot.reply_to(message, "✅ Комментарий сохранен! Нажмите 'Обновить статус' в заказе.")
        except Error as e: bot.reply_to(message, "❌ Ошибка БД."); print(e)
        finally: conn.close()

# --- ОБНОВЛЕНИЕ СТАТУСА (СИНХРОНИЗАЦИЯ) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('refresh_'))
def handle_refresh(call):
    order_id = call.data.split('_')[1]
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            query = """
                SELECT o.*, c.name as cocktail_name, c.CocktailType, i.glassware, 
                       i.ing_1, i.qty_1, i.ing_2, i.qty_2, i.ing_3, i.qty_3,
                       i.ing_4, i.qty_4, i.ing_5, i.qty_5, i.ing_6, i.qty_6,
                       u.username, u.tg_username
                FROM Orders o
                JOIN Cocktails c ON o.cocktail_id = c.id
                LEFT JOIN Ingredients i ON c.id = i.cocktail_id
                LEFT JOIN Users u ON o.user_id = u.user_id
                WHERE o.order_id = %s
            """
            cursor.execute(query, (order_id,))
            order = cursor.fetchone()
            
            if order:
                ingredients = []
                for num in range(1, 7):
                    name, qty = order.get(f'ing_{num}'), order.get(f'qty_{num}')
                    if name and name.strip(): ingredients.append(f"  🔹 {name}: {qty}")
                
                # Логика отображения статуса
                labels = {'new': '🆕 Ожидает', 'cooking': '👨‍🍳 В процессе', 'ready': '✅ Выполнен', 'cancelled': '❌ Отменен'}
                
                if order['status'] == 'cancelled' and not order['worker_name']:
                    status_display = "❌ Отменено заказчиком"
                else:
                    status_display = f"{labels.get(order['status'], order['status'])} ({order['worker_name'] or 'Никто'})"

                client_info = f"{order['username']} (tg: @{order['tg_username']})"
                b_comment = f"\n📝 **Бармен:** {order['BarmanComment']}" if order['BarmanComment'] else ""

                new_text = (
                    f"🆕 НОВЫЙ ЗАКАЗ №{order_id}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"👤 Клиент: {client_info}\n"
                    f"🍸 Коктейль: {order['cocktail_name']} ({order['CocktailType'] or '---'})\n"
                    f"🥤 Тара: {order['glassware'] or '---'}\n"
                    f"🔢 Количество: {order['quantity']}\n"
                    f"💬 Коммент клиента: {order['comment'] if order['comment'] else '---'}"
                    f"{b_comment}\n"
                    f"━━━━━━━━━━━━━━\n"
                    f"📜 СОСТАВ:\n{'\n'.join(ingredients) if ingredients else 'Нет'}\n\n"
                    f"Статус: {status_display}"
                )

                bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                                      text=new_text, reply_markup=get_order_markup(order_id, order['status']), parse_mode="Markdown")
                bot.answer_callback_query(call.id, "Обновлено")
        finally: conn.close()

# --- ОБРАБОТЧИКИ КНОПОК ДЕЙСТВИЯ (ГОТОВО/ОТМЕНА/В ПРОЦЕССЕ) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith(('done_', 'cancel_', 'cook_')))
def handle_order_action(call):
    action, order_id = call.data.split('_')
    user_name = call.from_user.first_name + (f" {call.from_user.last_name}" if call.from_user.last_name else "")
    
    status_map = {'done': 'ready', 'cancel': 'cancelled', 'cook': 'cooking'}
    new_status = status_map[action]
    
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = %s, worker_name = %s WHERE order_id = %s", (new_status, user_name, order_id))
            conn.commit()
        finally: conn.close()
    
    # После действия сразу вызываем обновление сообщения
    handle_refresh(call)

# --- КНОПКА "НАЗАД" ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('reset_'))
def handle_reset_order(call):
    order_id = call.data.split('_')[1]
    conn = get_db_connection()
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("UPDATE Orders SET status = 'new', worker_name = NULL WHERE order_id = %s", (order_id,))
            conn.commit()
        finally: conn.close()
    handle_refresh(call)

# --- АВТОРИЗАЦИЯ И СТАРТ ---
@bot.message_handler(commands=['start'])
def start(message): bot.send_message(message.chat.id, "👋 Введите пароль:")

@bot.message_handler(func=lambda message: message.text == PASSWORD)
def auth(message):
    active_sessions.add(message.chat.id)
    bot.send_message(message.chat.id, "🔓 Доступ открыт!")

def run_db_monitor():
    while True: check_new_orders(); time.sleep(5)

if __name__ == '__main__':
    threading.Thread(target=run_db_monitor, daemon=True).start()
    bot.polling(none_stop=True)
