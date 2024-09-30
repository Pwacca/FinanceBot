import os
import telebot
from oauth2client.service_account import ServiceAccountCredentials
import gspread
from datetime import datetime
from telebot import types
from telegram_bot_calendar import DetailedTelegramCalendar, LSTEP
import time
import platform

UNAUTHORIZED_USERS_FILE = 'unauthorized_users.txt'

AUTHORIZED_USERS_FILE = 'authorized_users.txt'

# with open('bot_token.txt', 'r') as file:
#     BOT_TOKEN = file.read().strip()

# Определяем путь к токену в зависимости от операционной системы
if platform.system() == "Darwin":  # macOS
    token_file_path = "/Users/pwacca/pwacca_expeses_bot_token_for_tests.txt"
elif platform.system() == "Linux":  # Linux, например на VM или Docker-контейнере
    token_file_path = "/home/pwacca/pwacca_expeses_bot_token_main.txt"
else:
    raise ValueError("Неподдерживаемая операционная система")

with open(token_file_path, 'r') as file:
    BOT_TOKEN = file.read().strip()

# Чтение токена из файла
with open(token_file_path, "r") as token_file:
    token = token_file.read().strip()

def load_users(file_path):
    """Загружает список пользователей из файла."""
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            return set(line.strip() for line in file)
    return set()

def save_user(file_path, username):
    """Сохраняет пользователя в файл."""
    with open(file_path, 'a') as file:
        file.write(f"{username}\n")

def remove_user(file_path, username):
    """Удаляет пользователя из файла."""
    users = load_users(file_path)
    if username in users:
        users.remove(username)
        with open(file_path, 'w') as file:
            for user in users:
                file.write(f"{user}\n")

# Загрузка списков пользователей
unauthorized_users = load_users(UNAUTHORIZED_USERS_FILE)
authorized_users = load_users(AUTHORIZED_USERS_FILE)

# Инициализация бота
bot = telebot.TeleBot(BOT_TOKEN)
# Удаление существующего webhook
bot.remove_webhook()

# Функция для обработки ошибок polling
def start_polling():
    while True:
        try:
            bot.polling(none_stop=True)
        except Exception as e:
            print(f"Error occurred: {e}")
            bot.stop_polling()
            time.sleep(15)

# Запуск polling
# start_polling()

# Настройка доступа к Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("crypto-reality-348518-2e061a0ac6ec.json", scope)
client = gspread.authorize(creds)

# Открытие таблицы по названию
expenses_sheet = client.open("Бюджет Катя/Лука").worksheet("expenses")
budget_sheet = client.open("Бюджет Катя/Лука").worksheet("P&L")

# Списки категорий
needs_categories = [
    "Продукты", "Дом расходники", "Такси", "Здоровье",
    "Катя Терапия", "Лука Терапия", "Катя Немецкий", "Лука Английский",
    "Моб. интернет", "Электричество", "Аренда", "Газ", "Вода", "Дом интернет", "Налоги",
]
wants_categories = [
    "Кафе/бары", "Чай/кофе", "Катя хобби", "Лука хобби", "Дом аксессуары",
    "Псина", "Подписки", "Настолки", "Маркетплейсы", "Алко домой", "Косметика", "Instax",
    "Outdoor act.", "Одежда",  "Подарки", "Уборка", "Отпуск",
]
income_categories = [
    "Яндекс", "Батон", "Аренда Лука", "Шалаш", "Аренда Катя", "Прочее Лука", "Прочее Катя"
]
currencies = ["Драмы", "Рубли", "Доллары"]

# Хранение данных пользователя
user_data = {}

def generate_markup(options, include_back_button=False):
    """
    Создание клавиатуры с опциями.
    """
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for option in options:
        markup.add(types.KeyboardButton(option))
    if include_back_button:
        markup.add(types.KeyboardButton("Вернуться на главную"))
    return markup

def handle_expense_input(chat_id, text, user_data):
    """
    Обработка ввода категории, суммы и валюты.
    """
    if text in needs_categories + wants_categories + ["Прочее"]:
        user_data[chat_id]["category"] = text
        return "Сумма:", types.ReplyKeyboardRemove()
    else:
        try:
            amount = float(text)
            user_data[chat_id]["amount"] = amount
            return "Валюта:", generate_markup(currencies)
        except ValueError:
            return "Нужны цифры", None

def handle_income_input(chat_id, text, user_data):
    """
    Обработка ввода категории, суммы и валюты для доходов.
    """
    if text in income_categories + ["Прочее"]:
        user_data[chat_id]["category"] = text
        return "Сумма:", types.ReplyKeyboardRemove()
    else:
        try:
            amount = float(text)
            user_data[chat_id]["amount"] = amount
            return "Валюта:", generate_markup(currencies)
        except ValueError:
            return "Нужны цифры", None

def handle_currency_input(chat_id, text, user_data, context_type, message):
    """
    Обработка ввода валюты и комментария.
    """
    if text in currencies:
        user_data[chat_id]["currency"] = text
        if user_data[chat_id]["category"] == "Прочее":
            bot.send_message(chat_id, text="Комментарий к расходу:", reply_markup=types.ReplyKeyboardRemove())
        else:
            markup = generate_markup(["Пропустить"], include_back_button=True)
            bot.send_message(chat_id, text="Введите комментарий к расходу или нажмите 'Пропустить':", reply_markup=markup)
    else:
        bot.send_message(chat_id, text="Нет такой валюты")

def save_and_respond_expense(chat_id, text, message):
    """
    Сохранение расхода и отправка ответа пользователю.
    """
    if user_data[chat_id]["category"] == "Прочее" and text == "Пропустить":
        bot.send_message(chat_id, text="Комментарий обязателен для категории 'Прочее'")
    else:
        user_data[chat_id]["comment"] = text if text != "Пропустить" else ""
        response = save_expense(chat_id, user_data, message)
        bot.send_message(chat_id, text=response)
        reset_to_main_menu(chat_id)

def save_and_respond_income(chat_id, text, message):
    """
    Сохранение дохода и отправка ответа пользователю.
    """
    user_data[chat_id]["comment"] = text if text != "Пропустить" else ""
    response = save_income(chat_id, user_data, message)
    bot.send_message(chat_id, text=response)
    reset_to_main_menu(chat_id)

def save_expense(chat_id, user_data, message):
    """
    Сохранение данных расходов в Google Sheets и обработка бюджета.
    """
    timestamp = user_data[chat_id]["date"].strftime("%Y-%m-%d %H:%M:%S")
    user_name = message.from_user.first_name
    category = user_data[chat_id].get("category", "прочее")
    amount = user_data[chat_id]["amount"]
    currency = user_data[chat_id]["currency"]
    comment = user_data[chat_id].get("comment", "")
    current_month = user_data[chat_id]["date"].month

    row = [timestamp, user_name, category, amount, currency, comment, current_month]
    expenses_sheet.append_row(row)

    return get_budget_info(category)

def get_budget_info(category):
    """
    Получение информации о бюджете для указанной категории.
    """
    current_month = datetime.now().strftime("%m.%y")
    budget_data = budget_sheet.get_all_values()
    month_column_index = find_month_column(budget_data, current_month)

    if month_column_index is not None:
        remaining_budget = calculate_remaining_budget(budget_data, month_column_index, category)
        if remaining_budget is not None:
            return f"Инфа сохранена,\n\n" \
                   f"{category}:\n" \
                   f"План: {round(remaining_budget['planned'])}; израсходовано {round(remaining_budget['actual'])} ({round((remaining_budget['actual'] / remaining_budget['planned']) * 100)}%)"
        else:
            return "Инфа сохранена, но не удалось найти информацию о бюджете."
    else:
        return "Инфа сохранена, но не удалось найти колонку с текущим месяцем."

def find_month_column(budget_data, current_month):
    """
    Нахождение индекса колонки для текущего месяца.
    """
    month_column_index = None
    header_row = budget_data[0]

    # Поиск колонки с текущим месяцем
    for i, cell in enumerate(header_row):
        cell = cell.strip()
        if cell.endswith(current_month):
            month_column_index = i
            break

    return month_column_index

def calculate_remaining_budget(budget_data, month_column_index, category):
    """
    Вычисление оставшегося бюджета для указанной категории.
    """
    for row in budget_data[1:]:
        if row[2] == category:  # Предполагается, что категория находится в третьем столбце
            actual_str = row[month_column_index].replace(',', '').replace('\xa0', '')
            planned_str = row[month_column_index + 1].replace(',', '').replace('\xa0', '')

            planned = float(planned_str) if planned_str else 0.0
            actual = float(actual_str) if actual_str else 0.0

            return {"planned": planned, "actual": actual}
    return None

def save_income(chat_id, user_data, message):
    """
    Сохранение данных доходов в Google Sheets.
    """
    timestamp = user_data[chat_id]["date"].strftime("%Y-%m-%d %H:%М:%С")
    user_name = message.from_user.first_name
    category = user_data[chat_id].get("category", "прочее")
    amount = user_data[chat_id]["amount"]
    currency = user_data[chat_id]["currency"]
    comment = user_data[chat_id].get("comment", "")
    current_month = user_data[chat_id]["date"].month

    row = [timestamp, user_name, category, amount, currency, comment, current_month]
    expenses_sheet.append_row(row)  # Убедимся, что используется корректный лист для доходов

    return f"Доход сохранен: {round(amount)} в категории {category}"

def find_month_column(budget_data, current_month):
    """
    Нахождение индекса колонки для текущего месяца.
    """
    month_column_index = None
    header_row = budget_data[0]

    # Поиск колонки с текущим месяцем
    for i, cell in enumerate(header_row):
        cell = cell.strip()
        if cell.endswith(current_month):
            month_column_index = i
            break

    return month_column_index

def get_summary():
    """
    Получение общей сводки из Google Sheets.
    """
    current_month = datetime.now().strftime("%m.%y")
    budget_data = budget_sheet.get_all_values()
    month_column_index = find_month_column(budget_data, current_month)
    if month_column_index is None:
        return "Не удалось найти данные за текущий месяц."
    try:
        summary_data = extract_summary_data(budget_data, month_column_index)
        return format_summary(summary_data)
    except (IndexError, ValueError):
        return "Не удалось получить корректные данные."

def extract_summary_data(budget_data, month_column_index):
    """
    Извлечение данных для сводки.
    """
    income_actual = float(budget_data[3][month_column_index].replace(',', '').replace('\xa0', ''))
    needs_expenses_actual = float(budget_data[5][month_column_index].replace(',', '').replace('\xa0', ''))
    wants_expenses_actual = float(budget_data[6][month_column_index].replace(',', '').replace('\xa0', ''))
    free_money_str = budget_data[7][month_column_index].replace(',', '').replace('\xa0', '')
    if free_money_str.startswith('(') and free_money_str.endswith(')'):
        free_money = -float(free_money_str.strip('()'))
    else:
        free_money = float(free_money_str)
    income_planned = float(budget_data[3][month_column_index + 1].replace(',', '').replace('\xa0', ''))
    needs_expenses_planned = float(budget_data[5][month_column_index + 1].replace(',', '').replace('\xa0', ''))
    wants_expenses_planned = float(budget_data[6][month_column_index + 1].replace(',', '').replace('\xa0', ''))
    return {
        "income_actual": income_actual,
        "needs_expenses_actual": needs_expenses_actual,
        "wants_expenses_actual": wants_expenses_actual,
        "free_money": free_money,
        "income_planned": income_planned,
        "needs_expenses_planned": needs_expenses_planned,
        "wants_expenses_planned": wants_expenses_planned
    }

def format_summary(summary_data):
    """
    Форматирование сводки для отображения.
    """
    income_percentage = (summary_data["income_actual"] / summary_data["income_planned"]) * 100 if summary_data["income_planned"] else 0
    needs_expenses_percentage = (summary_data["needs_expenses_actual"] / summary_data["needs_expenses_planned"]) * 100 if summary_data["needs_expenses_planned"] else 0
    wants_expenses_percentage = (summary_data["wants_expenses_actual"] / summary_data["wants_expenses_planned"]) * 100 if summary_data["wants_expenses_planned"] else 0

    return (
        f"Общая сводка за текущий месяц:\n"
        f"Доход: {round(summary_data['income_actual'])} ({round(income_percentage)}% от плана)\n"
        f"Расходы на Needs: {round(summary_data['needs_expenses_actual'])} ({round(needs_expenses_percentage)}% от плана)\n"
        f"Расходы на Wants: {round(summary_data['wants_expenses_actual'])} ({round(wants_expenses_percentage)}% от плана)\n"
        f"Свободные деньги: {round(summary_data['free_money'])}"
    )

def get_category_summary(category):
    """
    Получение сводки по категории из Google Sheets.
    """
    current_month = datetime.now().strftime("%m.%y")
    budget_data = budget_sheet.get_all_values()
    month_column_index = find_month_column(budget_data, current_month)

    if month_column_index is None:
        return "Не удалось найти данные за текущий месяц."

    try:
        for row in budget_data:
            if row[2] == category:
                actual_str = row[month_column_index].replace(',', '').replace('\xa0', '')
                planned_str = row[month_column_index + 1].replace(',', '').replace('\xa0', '')
                actual = float(actual_str) if actual_str else 0.0
                planned = float(planned_str) if planned_str else 0.0
                if planned != 0:
                    remaining = planned - actual
                    remaining_percentage = ((planned - actual) / planned) * 100
                    remaining_info = f"({round(remaining_percentage)}%)"
                else:
                    remaining = planned - actual
                    remaining_info = ""
                return f"Категория: '{category}':\n" \
                       f"Факт: {round(actual)}\n" \
                       f"План: {round(planned)}\n" \
                       f"Осталось: {round(remaining)} {remaining_info}"
    except (IndexError, ValueError):
        return "Не удалось получить корректные данные."

    return "Не удалось найти данные для указанной категории."
def start(message):
    """
    Обработка команды /start, приветствие пользователя.
    """
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции", "Общая сводка", "Сводка по категории"])
    bot.send_message(message.chat.id, text="Привет, {0.first_name}!".format(message.from_user), reply_markup=markup)

@bot.message_handler(content_types=['text'])

@bot.message_handler(content_types=['text'])
def handle_text(message):
    """
    Обработка текстовых сообщений от пользователя.
    """
    chat_id = message.chat.id
    username = message.from_user.username

    # Проверка авторизации
    if not handle_authorization(chat_id, username):
        return

    text = message.text

    # Обработка команд
    if text == "Вернуться на главную":
        handle_main_menu(chat_id)
    elif text == "Добавить расход":
        start_add_expense(chat_id, username)
    elif text == "Добавить приход":
        start_add_income(chat_id, username)
    elif text == "Технические операции":
        start_technical_operations(chat_id, username)
    elif text == "Общая сводка":
        show_summary(chat_id)
    elif text == "Сводка по категории":
        start_category_summary(chat_id, username)
    else:
        handle_contextual_input(chat_id, text, message)

def handle_authorization(chat_id, username):
    """
    Проверка авторизации пользователя.
    """
    if username not in authorized_users:
        if username not in unauthorized_users:
            unauthorized_users.add(username)
            save_user(UNAUTHORIZED_USERS_FILE, username)
            user_data[chat_id] = {'username': username}
            bot.send_message(chat_id, "Вы не авторизованы для использования этого бота. Запрос на авторизацию отправлен владельцу.")
            notify_admin_for_authorization(username)
        return False
    return True

def notify_admin_for_authorization(username):
    """
    Уведомление администратора о запросе на авторизацию.
    """
    notification_chat_id = 64003764
    markup = types.InlineKeyboardMarkup()
    authorize_button = types.InlineKeyboardButton(text="Авторизовать пользователя", callback_data=f"authorize_{username}")
    ignore_button = types.InlineKeyboardButton(text="Игнорировать", callback_data=f"ignore_{username}")
    markup.add(authorize_button, ignore_button)
    bot.send_message(notification_chat_id, f"Неавторизованный пользователь: @{username} пытался получить доступ к боту.", reply_markup=markup)

def handle_main_menu(chat_id):
    """
    Возврат на главный экран.
    """
    user_data.pop(chat_id, None)
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции", "Общая сводка", "Сводка по категории"])
    bot.send_message(chat_id, text="Что вы хотите сделать дальше?", reply_markup=markup)

def start_add_expense(chat_id, username):
    """
    Начало процесса добавления расхода.
    """
    user_data[chat_id] = {"context": "add_expense", "username": username, "date": datetime.now()}
    markup = generate_markup(["Needs", "Wants", "Прочее"], include_back_button=True)
    inline_markup = types.InlineKeyboardMarkup()
    change_date_button = types.InlineKeyboardButton(text="Поменять дату", callback_data="change_date")
    inline_markup.add(change_date_button)
    bot.send_message(chat_id, text="Тип расхода:", reply_markup=markup)
    bot.send_message(chat_id, text="Выберите действие:", reply_markup=inline_markup)

def start_add_income(chat_id, username):
    """
    Начало процесса добавления дохода.
    """
    user_data[chat_id] = {"context": "add_income", "username": username, "date": datetime.now()}
    markup = generate_markup(income_categories, include_back_button=True)
    inline_markup = types.InlineKeyboardMarkup()
    change_date_button = types.InlineKeyboardButton(text="Поменять дату", callback_data="change_date")
    inline_markup.add(change_date_button)
    bot.send_message(chat_id, text="Тип дохода:", reply_markup=markup)
    bot.send_message(chat_id, text="Выберите действие:", reply_markup=inline_markup)

def start_technical_operations(chat_id, username):
    """
    Начало процесса выполнения технических операций.
    """
    user_data[chat_id] = {"context": "technical_operations", "username": username, "date": datetime.now()}
    markup = generate_markup(["Конвертация рубли->драмы", "Отложить Лука", "Отложить Катя"], include_back_button=True)
    bot.send_message(chat_id, text="Выберите операцию:", reply_markup=markup)

def show_summary(chat_id):
    """
    Отображение общей сводки.
    """
    summary = get_summary()
    bot.send_message(chat_id, text=summary)

def start_category_summary(chat_id, username):
    """
    Начало процесса отображения сводки по категории.
    """
    user_data[chat_id] = {"context": "category_summary", "username": username}
    markup = generate_markup(["Needs", "Wants"], include_back_button=True)
    bot.send_message(chat_id, text="Выберите группу категорий:", reply_markup=markup)

def handle_contextual_input(chat_id, text, message):
    """
    Обработка контекстного ввода на основании текущего состояния пользователя.
    """
    if text == "Вернуться на главную":
        handle_main_menu(chat_id)
        return

    context = user_data.get(chat_id, {}).get("context")

    if context == "add_expense":
        handle_add_expense(chat_id, text, message)
    elif context == "add_income":
        handle_add_income(chat_id, text, message)
    elif context == "category_summary":
        handle_category_summary(chat_id, text)
    elif context == "technical_operations":
        handle_technical_operations(chat_id, text, message)

def handle_add_expense(chat_id, text, message):
    """
    Обработка ввода для добавления расхода.
    """
    if text in ["Needs", "Wants"]:
        user_data[chat_id]["type"] = text
        categories = needs_categories if text == "Needs" else wants_categories
        markup = generate_markup(categories, include_back_button=True)
        bot.send_message(chat_id, text="Категория:", reply_markup=markup)
    elif text in needs_categories + wants_categories + ["Прочее"]:
        user_data[chat_id]["category"] = text
        bot.send_message(chat_id, text="Сумма:", reply_markup=types.ReplyKeyboardRemove())
    elif "category" in user_data[chat_id] and "amount" not in user_data[chat_id]:
        response, markup = handle_expense_input(chat_id, text, user_data)
        bot.send_message(chat_id, text=response, reply_markup=markup)
    elif "amount" in user_data[chat_id] and "currency" not in user_data[chat_id]:
        handle_currency_input(chat_id, text, user_data, "expense", message)
    elif "currency" in user_data[chat_id] and "comment" not in user_data[chat_id]:
        save_and_respond_expense(chat_id, text, message)

def handle_add_income(chat_id, text, message):
    """
    Обработка ввода для добавления дохода.
    """
    if text in income_categories + ["Прочее"]:
        user_data[chat_id]["category"] = text
        bot.send_message(chat_id, text="Сумма:", reply_markup=types.ReplyKeyboardRemove())
    elif "category" in user_data[chat_id] and "amount" not in user_data[chat_id]:
        response, markup = handle_income_input(chat_id, text, user_data)
        bot.send_message(chat_id, text=response, reply_markup=markup)
    elif "amount" in user_data[chat_id] and "currency" not in user_data[chat_id]:
        handle_currency_input(chat_id, text, user_data, "income", message)
    elif "currency" in user_data[chat_id] and "comment" not in user_data[chat_id]:
        save_and_respond_income(chat_id, text, message)

# Строка 392
def handle_technical_operations(chat_id, text, message):
    """
    Обработка ввода для технических операций.
    """
    if text == "Конвертация рубли->драмы":
        user_data[chat_id]["category"] = text
        bot.send_message(chat_id, text="Введите сумму в рублях:", reply_markup=types.ReplyKeyboardRemove())
    elif text == "Отложить Лука":
        user_data[chat_id]["category"] = "Отложено Лука"
        bot.send_message(chat_id, text="Выберите валюту:", reply_markup=generate_markup(currencies, include_back_button=True))
    elif text == "Отложить Катя":
        user_data[chat_id]["category"] = "Отложено Катя"
        bot.send_message(chat_id, text="Выберите валюту:", reply_markup=generate_markup(currencies, include_back_button=True))
    elif user_data[chat_id]["category"] in ["Отложено Лука", "Отложено Катя"] and "currency" not in user_data[chat_id]:
        if text in currencies:
            user_data[chat_id]["currency"] = text
            bot.send_message(chat_id, text="Введите сумму:", reply_markup=types.ReplyKeyboardRemove())
        else:
            bot.send_message(chat_id, text="Нет такой валюты", reply_markup=None)
    elif user_data[chat_id]["category"] in ["Отложено Лука", "Отложено Катя"] and "amount" not in user_data[chat_id]:
        try:
            amount = float(text)
            user_data[chat_id]["amount"] = amount
            save_and_respond_saving(chat_id, message)
        except ValueError:
            bot.send_message(chat_id, text="Нужны цифры", reply_markup=None)
    elif "category" in user_data[chat_id] and user_data[chat_id]["category"] == "Конвертация рубли->драмы" and "amount_rub" not in user_data[chat_id]:
        try:
            amount_rub = float(text)
            user_data[chat_id]["amount_rub"] = amount_rub
            bot.send_message(chat_id, text="Введите сумму в драмах:")
        except ValueError:
            bot.send_message(chat_id, text="Нужны цифры", reply_markup=None)
    elif "amount_rub" in user_data[chat_id] and "amount_dram" not in user_data[chat_id]:
        try:
            amount_dram = float(text)
            user_data[chat_id]["amount_dram"] = amount_dram
            save_and_respond_conversion(chat_id, message)
        except ValueError:
            bot.send_message(chat_id, text="Нужны цифры", reply_markup=None)

def save_and_respond_saving(chat_id, message):
    """
    Сохранение данных откладывания денег и отправка ответа пользователю.
    """
    timestamp = user_data[chat_id]["date"].strftime("%Y-%m-%d %H:%М:%С")
    user_name = message.from_user.first_name
    category = user_data[chat_id]["category"]
    currency = user_data[chat_id]["currency"]
    amount = user_data[chat_id]["amount"]
    current_month = user_data[chat_id]["date"].month

    # Определяем полное название категории
    if currency == "Драмы":
        full_category = f"{category} д"
    else:
        full_category = f"{category} р"

    # Сохранение данных в таблицу
    row = [timestamp, user_name, full_category, amount, currency, "", current_month]
    expenses_sheet.append_row(row)

    bot.send_message(chat_id, text="Данные сохранены.")
    reset_to_main_menu(chat_id)

def save_and_respond_conversion(chat_id, message):
    """
    Сохранение данных конвертации и отправка ответа пользователю.
    """
    # Получение данных для расхода в рублях
    timestamp = user_data[chat_id]["date"].strftime("%Y-%m-%d %H:%M:%S")
    user_name = message.from_user.first_name
    amount_rub = user_data[chat_id]["amount_rub"]
    amount_dram = user_data[chat_id]["amount_dram"]
    current_month = user_data[chat_id]["date"].month

    # Сохранение расхода в рублях
    expense_row = [timestamp, user_name, "Конвертация руб", amount_rub, "Рубли", "", current_month]
    expenses_sheet.append_row(expense_row)

    # Сохранение дохода в драмах
    income_row = [timestamp, user_name, "Доход от конверт.", amount_dram, "Драмы", "", current_month]
    expenses_sheet.append_row(income_row)  # Если доходы и расходы в одной таблице

    bot.send_message(chat_id, text="Конвертация завершена. Данные сохранены.")
    reset_to_main_menu(chat_id)

def save_and_respond_technical_operation(chat_id, text, message):
    """
    Сохранение технической операции и отправка ответа пользователю.
    """
    user_data[chat_id]["comment"] = text if text != "Пропустить" else ""
    if user_data[chat_id]["category"] == "Конвертация руб":
        response = save_expense(chat_id, user_data, message)
    elif user_data[chat_id]["category"] == "Доход от конверт.":
        response = save_income(chat_id, user_data, message)
    bot.send_message(chat_id, text=response)
    reset_to_main_menu(chat_id)

def handle_category_summary(chat_id, text):
    """
    Обработка ввода для отображения сводки по категории.
    """
    if text in ["Needs", "Wants"]:
        user_data[chat_id]["group"] = text
        categories = needs_categories if text == "Needs" else wants_categories
        markup = generate_markup(categories, include_back_button=True)
        bot.send_message(chat_id, text="Выберите категорию:", reply_markup=markup)
    elif text in needs_categories + wants_categories:
        response = get_category_summary(text)
        bot.send_message(chat_id, text=response)
        reset_to_main_menu(chat_id)

def reset_to_main_menu(chat_id):
    """
    Сброс данных пользователя и возврат к главному меню.
    """
    user_data.pop(chat_id, None)
    markup = generate_markup(["Добавить расход", "Добавить приход", "Технические операции", "Общая сводка", "Сводка по категории"])
    bot.send_message(chat_id, text="Добавить еще информацию?", reply_markup=markup)

def create_compact_day_selection_keyboard():
    """
    Создание компактной клавиатуры для выбора дня.
    """
    markup = types.InlineKeyboardMarkup()
    days = [types.InlineKeyboardButton(text=str(day), callback_data=f"day_{day}") for day in range(1, 32)]
    for i in range(0, len(days), 7):
        markup.row(*days[i:i+7])
    markup.add(types.InlineKeyboardButton(text="Изменить месяц", callback_data="change_month"))
    markup.add(types.InlineKeyboardButton(text="Изменить год", callback_data="change_year"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data == "change_date")
def callback_change_date(call):
    """
    Обработка нажатия кнопки "Поменять дату".
    """
    markup = create_compact_day_selection_keyboard()
    bot.edit_message_text("Выберите день:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("day_"))
def callback_select_day(call):
    """
    Обработка выбора дня.
    """
    day = int(call.data.split("_")[1])
    now = datetime.now()
    try:
        selected_date = now.replace(day=day)
    except ValueError:
        selected_date = now.replace(day=28)  # Если день выходит за пределы текущего месяца
    user_data[call.message.chat.id]["date"] = selected_date
    bot.edit_message_text(f"Выбрана дата: {selected_date.strftime('%Y-%m-%d')}", call.message.chat.id, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data == "change_month")
def callback_change_month(call):
    """
    Обработка нажатия кнопки "Изменить месяц".
    """
    now = datetime.now().date()
    calendar, step = DetailedTelegramCalendar(min_date=now.replace(day=1), locale='ru', start_from=LSTEP['m']).build()
    bot.edit_message_text(f"Выберите {step}", call.message.chat.id, call.message.message_id, reply_markup=calendar)

@bot.callback_query_handler(func=lambda call: call.data == "change_year")
def callback_change_year(call):
    """
    Обработка нажатия кнопки "Изменить год".
    """
    now = datetime.now().date()
    calendar, step = DetailedTelegramCalendar(min_date=now.replace(day=1), locale='ru', start_from=LSTEP['y']).build()
    bot.edit_message_text(f"Выберите {step}", call.message.chat.id, call.message.message_id, reply_markup=calendar)

@bot.callback_query_handler(func=DetailedTelegramCalendar.func())
def handle_calendar(call):
    """
    Обработка выбора даты из календаря.
    """
    now = datetime.now().date()
    result, key, step = DetailedTelegramCalendar(min_date=now.replace(day=1), locale='ru').process(call.data)
    if not result and key:
        bot.edit_message_text(f"Выберите {step}", call.message.chat.id, call.message.message_id, reply_markup=key)
    elif result:
        user_data[call.message.chat.id]["date"] = result
        bot.edit_message_text(f"Выбрана дата: {result.strftime('%Y-%m-%d')}", call.message.chat.id, call.message.message_id)

# Удаление существующего webhook
# bot.remove_webhook()
bot.polling(none_stop=True)