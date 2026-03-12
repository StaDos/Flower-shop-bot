# main bot
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import telebot
from telebot import types
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from config import MAIN_BOT_TOKEN, API_KEY, MAIN_CHANNEL_ID, API_KEY_LLM
import requests

bot = telebot.TeleBot(MAIN_BOT_TOKEN)


CHANNEL = MAIN_CHANNEL_ID
API_WEATHER = API_KEY
API_LLM = API_KEY_LLM         # ← твой ключ от OpenRouter / Mistral / любого
waiting_for_question = {}
SPREADSHEET_ID = '1f6NqR2uBoRqLm4EhbuqA1Q0LNxIrO-nythY8TLeqiPI'
CREDENTIALS_FILE = 'sheetmarket-12363ab675da.json'          # положи json рядом с ботом
SHEET_CATALOG = 'Каталог'
SHEET_ORDERS  = 'Замовлення'

scope = [
    'https://spreadsheets.google.com/feeds',
    'https://www.googleapis.com/auth/drive'
]
creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scope)
client = gspread.authorize(creds)
spreadsheet = client.open_by_key(SPREADSHEET_ID)

test_sheet = spreadsheet.worksheet(SHEET_CATALOG)
print("Лист найден:", test_sheet.title)

ADMIN_IDS = [7504177685]

# Колонки
COL_ID    = 1
COL_NAME  = 2
COL_PRICE = 3
COL_DESC  = 4
COL_PHOTO = 5
COL_STOCK = 6



def load_catalog():
    try:
        sheet = spreadsheet.worksheet(SHEET_CATALOG)
        data = sheet.get_all_values()
        if not data or len(data) < 2:
            return []

        products = []
        for row in data[1:]:
            if len(row) < COL_STOCK:
                continue
            try:
                products.append({
                    'id': row[COL_ID-1].strip(),
                    'name': row[COL_NAME-1].strip(),
                    'price': float(row[COL_PRICE-1].replace(' ', '').replace(',', '.')) if row[COL_PRICE-1].strip() else 0,
                    'desc': row[COL_DESC-1].strip(),
                    'photo': row[COL_PHOTO-1].strip(),
                    'stock': int(row[COL_STOCK-1]) if row[COL_STOCK-1].strip().isdigit() else 0
                })
            except:
                pass  # пропускаем битые строки
        return products
    except Exception as e:
        print(f"Ошибка загрузки каталога: {e}")
        return []

PRODUCTS = load_catalog()                  # загружаем при старте
carts = {}                                 # {user_id: {prod_id: qty}}
carousel_pos = {}                          # {user_id: current_index}



# ──────────────────────────────────────────────
# АДМИН-ПАНЕЛЬ: Добавление и удаление товаров по ID
# ──────────────────────────────────────────────

admin_states = {}  # {user_id: {'mode': 'add'/'delete', 'data': {}, 'step': ...}}

# Авто-генерация ID: берём максимальный существующий +1
def get_next_id():
    try:
        sheet = spreadsheet.worksheet(SHEET_CATALOG)
        ids = sheet.col_values(1)[1:]  # столбец A, без заголовка
        if not ids:
            return "1"
        numeric_ids = [int(i) for i in ids if i.isdigit()]
        return str(max(numeric_ids) + 1) if numeric_ids else "1"
    except:
        return "1"

# ── Добавление товара ────────────────────────────────────────────────────────
@bot.message_handler(commands=['add'])
def cmd_add(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Доступа нет, извини 😏")
        return

    user_id = message.from_user.id
    admin_states[user_id] = {
        'mode': 'add',
        'step': 'name',
        'data': {}
    }
    bot.reply_to(message, "Окей, добавляем новый товар.\n\n1. Название 🌹")
    bot.register_next_step_handler(message, add_step_handler)

def add_step_handler(message):
    uid = message.from_user.id
    state = admin_states.get(uid)
    if not state or state['mode'] != 'add':
        return

    step = state['step']
    data = state['data']

    print(f"DEBUG: шаг {step}, текст: '{message.text}'")

    if step == 'name':
        data['name'] = message.text.strip()
        state['step'] = 'price'
        bot.reply_to(message, "2. Цена (число)")
        admin_states[uid] = state
        bot.register_next_step_handler(message, add_step_handler)  # ← привязываем к ответу бота
    elif step == 'price':
        try:
            data['price'] = float(message.text.replace(',', '.').strip())
            state['step'] = 'desc'
            bot.reply_to(message, "3. Описание (можно с эмодзи)")
            admin_states[uid] = state
            bot.register_next_step_handler(message, add_step_handler)
        except ValueError:
            bot.reply_to(message, "Только число, попробуй снова")
            return

    elif step == 'desc':
        data['desc'] = message.text.strip()
        state['step'] = 'photo'
        bot.reply_to(message, "4. Фото товара (отправь фото или напиши /skip)")
        admin_states[uid] = state
        bot.register_next_step_handler(message, add_step_handler)

    elif step == 'photo':
        if message.photo:
            file_id = message.photo[-1].file_id
            data['photo'] = file_id
            state['step'] = 'stock'
            bot.reply_to(message, "Фото принято. 5. Остаток на складе (число)")
            admin_states[uid] = state
            bot.register_next_step_handler(message, add_step_handler)
        elif message.text and message.text.strip().lower() in ['/skip', 'без', 'нет']:
            data['photo'] = ''
            state['step'] = 'stock'
            bot.reply_to(message, "Без фото ок. 5. Остаток на складе (число)")
            admin_states[uid] = state
            bot.register_next_step_handler(message, add_step_handler)
        else:
            bot.reply_to(message, "Отправь фото или /skip")
            return

    elif step == 'stock':
        try:
            data['stock'] = int(message.text.strip())
            # Финальный просмотр
            text = f"Проверь перед добавлением:\n\n" \
                   f"ID: (авто) {get_next_id()}\n" \
                   f"Название: {data.get('name')}\n" \
                   f"Цена: {data.get('price')} грн\n" \
                   f"Описание: {data.get('desc')}\n" \
                   f"Фото: {'есть' if data.get('photo') else 'нет'}\n" \
                   f"Остаток: {data.get('stock')} шт."

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("Добавить ✅", callback_data='add_confirm'),
                types.InlineKeyboardButton("Отмена ❌", callback_data='add_cancel')
            )
            bot.reply_to(message, text, reply_markup=markup)
        except ValueError:
            bot.reply_to(message, "Только целое число")
            return

    admin_states[uid] = state  # сохраняем изменения

# ── Подтверждение добавления ─────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: call.data in ['add_confirm', 'add_cancel'])
def handle_add_confirm(call):
    uid = call.from_user.id
    state = admin_states.get(uid)
    if not state or state['mode'] != 'add':
        bot.answer_callback_query(call.id)
        return

    if call.data == 'add_cancel':
        del admin_states[uid]
        bot.edit_message_text("Добавление отменено.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    data = state['data']
    try:
        sheet = spreadsheet.worksheet(SHEET_CATALOG)
        new_id = get_next_id()

        row = [new_id, data['name'], data['price'], data['desc'], data['photo'], data['stock']]
        sheet.append_row(row)

        global PRODUCTS
        PRODUCTS = load_catalog()
        print(f"Каталог перезагружен после добавления: {len(PRODUCTS)} товаров")  # для дебага в консоль
        bot.edit_message_text(
            f"Товар добавлен!\nID: {new_id}\nНазвание: {data['name']}",
            call.message.chat.id,
            call.message.message_id
        )
    except gspread.exceptions.WorksheetNotFound:
        bot.edit_message_text("Ошибка: лист 'Каталог' не найден в таблице! Проверь имя вкладки.", call.message.chat.id, call.message.message_id)
    except Exception as e:
        bot.edit_message_text(f"Ошибка при записи: {type(e).__name__} — {str(e)}", call.message.chat.id, call.message.message_id)
        print(f"ПОЛНАЯ ОШИБКА: {type(e).__name__} — {str(e)}")  # в консоль для дебага

    del admin_states[uid]
    bot.answer_callback_query(call.id)

# ── Удаление товара ──────────────────────────────────────────────────────────
@bot.message_handler(commands=['delete', 'del'])
def cmd_delete(message):
    if message.from_user.id not in ADMIN_IDS:
        bot.reply_to(message, "Не положено 😤")
        return

    try:
        sheet = spreadsheet.worksheet(SHEET_CATALOG)
        rows = sheet.get_all_values()
        if len(rows) <= 1:
            bot.reply_to(message, "Каталог пустой, удалять нечего.")
            return

        text = "Список товаров (ID | Название | Цена | Остаток):\n\n"
        for row in rows[1:]:
            if len(row) < 6: continue
            id_ = row[0]
            name = row[1][:40] + ('...' if len(row[1]) > 40 else '')
            price = row[2]
            stock = row[5]
            text += f"{id_} | {name} | {price} грн | {stock} шт.\n"

        text += "\nВведи ID товара, который хочешь удалить:"
        sent = bot.reply_to(message, text)
        bot.register_next_step_handler(sent, process_delete_id)
    except Exception as e:
        bot.reply_to(message, f"Не смог загрузить список: {str(e)}")

def process_delete_id(message):
    uid = message.from_user.id
    id_to_del = message.text.strip()

    try:
        sheet = spreadsheet.worksheet(SHEET_CATALOG)
        rows = sheet.get_all_values()

        row_index = None
        product_name = None
        for i, row in enumerate(rows):
            if len(row) > 0 and row[0] == id_to_del:
                row_index = i + 1  # gspread 1-based
                product_name = row[1]
                break

        if row_index is None:
            bot.reply_to(message, f"Товар с ID {id_to_del} не найден.")
            return

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Да, удалить ❌", callback_data=f'del_confirm_{row_index}'),
            types.InlineKeyboardButton("Нет, оставить", callback_data='del_cancel')
        )

        bot.reply_to(
            message,
            f"Удалить товар?\nID: {id_to_del}\nНазвание: {product_name}",
            reply_markup=markup
        )
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('del_confirm_') or call.data == 'del_cancel')
def handle_delete_confirm(call):
    if call.data == 'del_cancel':
        bot.edit_message_text("Удаление отменено.", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)
        return

    if not call.data.startswith('del_confirm_'):
        return

    row_index = int(call.data.split('_')[2])

    try:
        sheet = spreadsheet.worksheet(SHEET_CATALOG)
        sheet.delete_rows(row_index)

        global PRODUCTS
        PRODUCTS = load_catalog()

        bot.edit_message_text(
            f"Строка {row_index} (товар) удалена успешно.",
            call.message.chat.id,
            call.message.message_id
        )
    except Exception as e:
        bot.edit_message_text(f"Не удалось удалить: {str(e)}", call.message.chat.id, call.message.message_id)

    bot.answer_callback_query(call.id)




#start
@bot.message_handler(commands=['start', 'menu'])
def main_menu(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(InlineKeyboardButton("Каталог 📔/ Зробити замовлення ✅", callback_data="catalog"))
    markup.add(
        InlineKeyboardButton("Доставка / оплата 💳", callback_data="delivery"),
        InlineKeyboardButton("Запитати у адміна", callback_data="ask_mi"),
        InlineKeyboardButton("Запитати у ШІ 🤖", callback_data="ask_ai")
    )
    markup.add(InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info"))
    bot.send_message(
        message.chat.id,
        "Обери розділ:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    data = call.data

    if not data:  # защита от None
        bot.answer_callback_query(call.id)
        return



    elif data == "ask_ai":
        bot.send_message(
            call.from_user.id,
            "Задавайте питання по квітам, ШІ дасть відповіді:",
        )
        waiting_for_question[call.from_user.id] = True
        bot.answer_callback_query(call.id)  # убирает loading на кнопке

    elif data == "back":
        main_menu(call.message)


    elif data == "ask_mi":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Задати питання", url="https://t.me/Shdow_Key"))
        markup.add(InlineKeyboardButton("До меню", callback_data="back"))
        markup.add(InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info"))
        markup.add(InlineKeyboardButton("Каталог", callback_data="catalog"))
        bot.edit_message_text(
            "Ваша дія:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)

    elif data == "delivery":
        text = (
            "  🚚 ДОСТАВКА:\n\n"
            "- Кропивницький:\n"
            '  самовивіз або по домовленності тут 👉: url="https://t.me/Shdow_Key"\n\n'

            "- Інші міста:\n"
            "  Нова Пошта\n\n"

            "💳 ОПЛАТА:\n\n"
            "- Готівкою  або на карту по Кропивницькому\n\n"
            "- Повна передоплата на Mono, Privat Bank при відправленні в інші міста"
        )
        bot.send_message(
            call.from_user.id,
            text
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Зробити замовлення", callback_data="catalog"))
        markup.add(InlineKeyboardButton("Запитати у адміна", callback_data="ask_mi"))
        markup.add(InlineKeyboardButton("До меню", callback_data="back"))
        markup.add(InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info"))
        bot.edit_message_text(
            "Ваша дія:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)

    elif data == 'catalog':
        show_catalog(call)
    elif data == "show_cart":
        show_cart(call)
    elif data.startswith('prev_'):
        carousel_nav(call)
    elif data.startswith('next_'):
        carousel_nav(call)   # можно одну функцию на оба
    elif data.startswith('add_'):
        add_to_cart(call)
    elif data.startswith('checkout_'):
        checkout(call)
    elif data == 'noop':
        bot.answer_callback_query(call.id)

    elif data.startswith('retry_qty_'):
        prod_id = data.split('_')[2]  # retry_qty_ABC123 → ABC123
        prod = next((p for p in PRODUCTS if p['id'] == prod_id), None)

        if not prod:
            bot.answer_callback_query(call.id, "Товар не знайдено 😢")
            return

    # Повторяем запрос количества для этого товара
    # user_id берём из call.from_user.id — он всегда есть
        user_id = call.from_user.id

        bot.send_message(
            call.message.chat.id,
            f"Залишок: {prod['stock']} шт.\nСкільки одиниць бажаєте придбати? (введіть число)"
        )

    # Регистрируем handler заново — теперь с правильными аргументами
        bot.register_next_step_handler(
            call.message,
            process_quantity,
            user_id,
            prod
        )

        bot.answer_callback_query(call.id, "Вводьте нову кількість")
    else:
        print(f"Незнайомий callback: {data} от {call.from_user.id}")
        bot.answer_callback_query(call.id, text="Не зрозумів кнопку 😅", show_alert=False)

@bot.message_handler(func=lambda m: m.text == "Каталог")
def show_catalog(call):
    global PRODUCTS
    PRODUCTS = load_catalog()
    if not PRODUCTS:
        bot.send_message(call.message.chat.id, "Каталог порожній... Очікуємо 😭")
        return

    user_id = call.from_user.id
    carousel_pos[user_id] = 0
    show_product(user_id, call.message.chat.id, None)  # первое сообщение

def show_product(user_id, chat_id, message_id=None):
    idx = carousel_pos.get(user_id, 0)
    if idx >= len(PRODUCTS) or idx < 0:
        idx = 0
        carousel_pos[user_id] = 0

    prod = PRODUCTS[idx]

    caption = f"🌹 *{prod['name']}*\n\n{prod['desc']}\n\n💰 {prod['price']:.0f} грн\nЗалишок: {prod['stock']} шт."

    markup = types.InlineKeyboardMarkup(row_width=3)
    prev_btn = types.InlineKeyboardButton("попер", callback_data=f"prev_{user_id}")
    page_btn = types.InlineKeyboardButton(f"{idx+1}/{len(PRODUCTS)}", callback_data="noop")
    next_btn = types.InlineKeyboardButton("слід", callback_data=f"next_{user_id}")

    add_btn = types.InlineKeyboardButton("Додати до кошика 🛒", callback_data=f"add_{user_id}_{prod['id']}")
    add_btn2 = types.InlineKeyboardButton("До меню", callback_data="back")
    markup.row(prev_btn, page_btn, next_btn)
    markup.row(add_btn)
    markup.row(add_btn2)


    media = types.InputMediaPhoto(media=prod['photo'], caption=caption, parse_mode='Markdown')

    try:
        if message_id:
            bot.edit_message_media(
                media=media,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=markup
            )
        else:
            sent = bot.send_photo(chat_id, photo=prod['photo'], caption=caption, parse_mode='Markdown', reply_markup=markup)
            # можно сохранить sent.message_id если нужно, но edit по callback хватит
    except Exception as e:
        print(e)
        bot.send_message(chat_id, "Наразі це увесь каталог\n" + caption, parse_mode='Markdown', reply_markup=markup)


# Карусель переключение
@bot.callback_query_handler(func=lambda call: call.data.startswith(('prev_', 'next_')))
def carousel_nav(call):
    user_id = int(call.data.split('_')[1])
    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "Не твоя карусель 😏")
        return

    if call.data.startswith('prev_'):
        carousel_pos[user_id] = (carousel_pos[user_id] - 1) % len(PRODUCTS)
    else:
        carousel_pos[user_id] = (carousel_pos[user_id] + 1) % len(PRODUCTS)

    show_product(user_id, call.message.chat.id, call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# Добавить в корзину → спросить количество
@bot.callback_query_handler(func=lambda call: call.data.startswith('add_'))
def add_to_cart(call):
    parts = call.data.split('_')
    if len(parts) != 3:
        return
    _, user_id_str, prod_id = parts
    user_id = int(user_id_str)
    if call.from_user.id != user_id:
        return

    prod = next((p for p in PRODUCTS if p['id'] == prod_id), None)
    if not prod:
        bot.answer_callback_query(call.id, "Товара не бачу 😢")
        return

    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        f"Залишок: {prod['stock']} шт.\nСкільки одиниць бажаєте придбати?:\n"
    )
    #bot.send_message(message.chat.id, "Ваш вибір:", reply_markup=markup)

    bot.register_next_step_handler(msg, process_quantity, user_id, prod)

def process_quantity(message, user_id, prod):

    if user_id not in carts:
        carts[user_id] = {}

    if not message.text.isdigit():
        bot.send_message(message.chat.id, "Тільки  число. Спробуйте щє раз.")
        return

    qty = int(message.text)
    print(f"DEBUG: получил количество- {qty}")

    if qty <= 0:
        bot.send_message(message.chat.id, "Мінімум 1 товар")
        return

    if qty > prod['stock']:
        msg_text = f"На складі тільки {prod['stock']} шт.\nВведіть менше або зачекайте поповнення."
        bot.send_message(message.chat.id, msg_text)

    # Добавляем кнопки прямо здесь
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("Ввести інше кількість", callback_data=f"retry_qty_{prod['id']}"),
            types.InlineKeyboardButton("До каталогу", callback_data="catalog")  #callback_data=f"retry_qty_{prod['id']}_{user_id}"
        )
        markup.add(
            types.InlineKeyboardButton("Написати адміну", callback_data="ask_mi"),
            types.InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info")
        )

        bot.send_message(message.chat.id, "Що робити далі?", reply_markup=markup)

    # Важно: НЕ регистрируем новый handler здесь!
    # Просто выходим, чтобы не висел старый
        return



    current_qty = carts[user_id].get(prod['id'], 0)
    carts[user_id][prod['id']] = current_qty + qty

    total = qty * prod['price']  # или (current_qty + qty) * price, если хочешь общую сумму по товару
    msg_text = f"Добавлено {qty} × {prod['name']} = {total:.0f} грн"
    if current_qty > 0:
        msg_text += f"\n(всього цього товару в кошику: {current_qty + qty})"

    bot.send_message(message.chat.id, msg_text + "\n\nПродовжити? Чи оформити?")

    print(f"DEBUG: корзина пользователя {user_id} после добавления: {carts.get(user_id, 'пусто')}")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Продовжити", callback_data="catalog"))
    markup.add(InlineKeyboardButton("Оформити", callback_data="show_cart"))
    markup.add(InlineKeyboardButton("До меню", callback_data="back"))
    markup.add(InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info"))

    bot.send_message(message.chat.id, "Ваш вибір:", reply_markup=markup)



@bot.message_handler(func=lambda m: m.text == "show_cart")  # или через команду
def show_cart(message):
    user_id = message.from_user.id
    if user_id not in carts or not carts[user_id]:
        bot.send_message(message.chat.id, "Кошик порожній")
        return

    text = "Ваш кошик:\n\n"
    total = 0
    for pid, qty in carts[user_id].items():
        prod = next(p for p in PRODUCTS if p['id'] == pid)
        subtotal = qty * prod['price']
        text += f"{prod['name']} × {qty} шт = {subtotal:.0f} грн\n"
        total += subtotal

    text += f"\nРазом: {total:.0f} грн"

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Оформити замовлення 🚀", callback_data=f"checkout_{user_id}"))
    markup.add(InlineKeyboardButton("До меню", callback_data="back"))
    markup.add(InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info"))


    bot.send_message(message.message.chat.id, text, reply_markup=markup)

# Оформление — сразу в личку админам
@bot.callback_query_handler(func=lambda call: call.data.startswith('checkout_'))
def checkout(call):
    user_id_str = call.data.split('_')[1]
    user_id = int(user_id_str)
    if call.from_user.id != user_id:
        return

    if user_id not in carts or not carts[user_id]:
        bot.answer_callback_query(call.id, "Корзина порожня!")
        return

    user = call.from_user
    username = user.username or "без ника"
    text = f"Новый заказ от @{username} (id: {user_id})\nСсылка: tg://user?id={user_id}\n\n"
    total = 0
    items = []
    for pid, qty in carts[user_id].items():
        prod = next(p for p in PRODUCTS if p['id'] == pid)
        subtotal = qty * prod['price']
        items.append(f"{prod['name']} × {qty} шт = {subtotal:.0f} грн")
        total += subtotal

    text += "\n".join(items) + f"\n\nВсього: {total:.0f} грн\nДата: {datetime.now().strftime('%Y-%m-%d %H:%M')}"

    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, text)
        except:
            print(f"Не зміг відправити адміну {admin_id}")

    # Сохраняем в таблицу Заказы
    try:
        sheet = spreadsheet.worksheet(SHEET_ORDERS)
        row = [user_id, username, datetime.now().strftime('%Y-%m-%d %H:%M'), "\n".join(items), total, "Новый"]
        sheet.append_row(row)
    except Exception as e:
        print(f"Помилка записи заказа: {e}")

    # ←←← ВСТАВЛЯЕМ СЮДА ОБНОВЛЕНИЕ ОСТАТКА ←←←
    try:
        catalog_sheet = spreadsheet.worksheet("Каталог")  # или как у тебя называется лист с товарами

        for pid, ordered_qty in carts[user_id].items():
            # Находим товар по id
            prod = next((p for p in PRODUCTS if p['id'] == pid), None)
            if not prod:
                continue

            # Ищем строку в таблице по id (предполагаем, что id в колонке A=1)
            cell = catalog_sheet.find(pid)  # find ищет по значению
            if cell:
                row_num = cell.row
                # Столбец остатка — подставь свой (например, столбец D=4)
                stock_col = 6  # ← ИЗМЕНИ НА СВОЙ НОМЕР СТОЛБЦА С ОСТАТКОМ!
                current_stock = int(catalog_sheet.cell(row_num, stock_col).value or 0)
                new_stock = max(0, current_stock - ordered_qty)  # не уходим в минус

                # Обновляем ячейку в таблице
                catalog_sheet.update_cell(row_num, stock_col, new_stock)

                # Обновляем и в памяти (чтобы сразу показывало актуально)
                prod['stock'] = new_stock

                print(f"DEBUG: обновлён остаток {prod['name']} → {new_stock}")

    except Exception as e:
        print(f"Ошибка обновления остатка: {e}")



    bot.send_message(call.message.chat.id, "Замовлення відправлено! Ми звʼяжимось найближчим часом 🌹")
    del carts[user_id]  # чистим корзину
    bot.answer_callback_query(call.id, "Замовлення відправлено!")
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Запитати у адміна", callback_data="ask_mi"))
    markup.add(InlineKeyboardButton("До меню", callback_data="back"))
    markup.add(InlineKeyboardButton("Каталог", callback_data="catalog"))
    markup.add(InlineKeyboardButton("Назад до каналу", url="https://t.me/kvitucha_mriya_info"))
    bot.send_message(call.message.chat.id, text, reply_markup=markup)


@bot.message_handler(func=lambda m: True)
def any_message(message):
    uid = message.from_user.id

    if uid in waiting_for_question and waiting_for_question[uid]:
        question = message.text.strip()
        if not question:
            bot.reply_to(message, "Порожньо, потрібен текст 😏")
            return

        bot.reply_to(message, "Зачекайте... 🧠")

        answer = ask_llm(question)  # твоя функция

        bot.reply_to(message, answer or "Упс,щось пішло не так... Щє раз?")

        # сбрасываем состояние
        waiting_for_question[uid] = False

        # опционально — сразу кидаем меню или кнопку "ещё вопрос"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("Щє питання?", callback_data="ask_ai"),
            InlineKeyboardButton("До меню", callback_data="back")
        )
        markup.add(InlineKeyboardButton("Запитати у адміна", callback_data="ask_mi"))
        markup.add(InlineKeyboardButton(" Назад до каналу", url="https://t.me/kvitucha_mriya_info"))
        bot.send_message(message.chat.id, "Далі?", reply_markup=markup)

    #else:
        # сюда попадают все остальные сообщения
        #bot.reply_to(message, "Я в тестовому стані 😅\nТисни меню нижче")


MODEL = "arcee-ai/trinity-large-preview:free"  # или mistral-small-latest,
#AI

def ask_llm(question):
    url = "https://api.mistral.ai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {API_LLM}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": "Ти знаєш все про квіти. Відповіді чесні, без брехні. Якщо щось невідомо - відповідай 'Вибачте,я не можу вам допомогти з цим питаням'"},

            {"role": "user", "content": question}
        ],
        "temperature": 0.9,
        "max_tokens": 400
    }

    try:
        r = requests.post(url, headers=headers, json=data, timeout=20)
        r.encoding = 'utf-8'
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"Ошибка: {str(e)}"


# Запуск
if __name__ == '__main__':
    print("Бот поехал...")


bot.infinity_polling()
