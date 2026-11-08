import asyncio, json
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton,
                           Message, ReplyKeyboardMarkup)

TOKEN = "9103418650:AAHt8Z3oY4Q4t7wEjxa-D56ApFq136pyD2w"
ADMIN_ID = 5132006984

STUDENTS = [
    "Абитковская Карина", "Бертош Виктория", "Будник София", "Веремейчик Станислав",
    "Вильтовская Надежда", "Елисеенко Никита", "Жуковский Иван", "Захарчения Юлия",
    "Иванова Елизавета", "Игнатович Анастасия", "Кислая Софья-Любовь", "Козырев Валентин",
    "Кореневская Маргарита", "Коршун Маргарита", "Куц Даниил", "Ложникова Екатерина",
    "Подобед Елизавета", "Попов Родион", "Прачковский Денис", "Расолько Виктория",
    "Рончик Павел", "Рыжкина Полина", "Славашевич Алина", "Смолич Арина",
    "Сырников Владислав", "Фандо Егор", "Филимонов Александр", "Шманай Тимофей",
    "Шустов Матвей", "Юстимчук Анастасия",
]

REASONS = ["По болезни", "По заявлению", "По повестке", "По приказу",
           "Без уважительной причины"]
MAX_DAYS = 90  # максимальная длина периода отметки

def load(name, default):
    try:
        with open(name, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save(name, data):
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

ABSENT = load("absent.json", {})      # дата -> {фамилия: причина}
BINDINGS = load("bindings.json", {})  # "id аккаунта" -> фамилия

def today():
    return datetime.now().strftime("%d.%m.%Y")

def dkey(s):
    """Превращает '05.12.2026' в настоящую дату, чтобы сравнивать правильно."""
    return datetime.strptime(s, "%d.%m.%Y")

def parse_date(s):
    try:
        return datetime.strptime(s.strip(), "%d.%m.%Y").strftime("%d.%m.%Y")
    except ValueError:
        return None

def parse_period(text):
    """'06.11.2026 - 12.11.2026' или '0' (только сегодня)."""
    text = (text or "").strip().replace(" ", "")
    if text == "0":
        d = today()
        return d, d
    parts = text.split("-")
    if len(parts) != 2:
        return None
    start, end = parse_date(parts[0]), parse_date(parts[1])
    if not start or not end or dkey(start) > dkey(end):
        return None
    return start, end

def days_between(start, end):
    d0, d1 = dkey(start), dkey(end)
    out, cur = [], d0
    while cur <= d1:
        out.append(cur.strftime("%d.%m.%Y"))
        cur += timedelta(days=1)
    return out

def is_admin(user_id):
    return user_id == ADMIN_ID

def name_of(user_id):
    return BINDINGS.get(str(user_id))

def student_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🙋 Отметиться"),
                   KeyboardButton(text="❌ Отменить отметку")]],
        resize_keyboard=True)

def admin_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Ведомость за сегодня"),
                   KeyboardButton(text="🗓 Будущие отметки")],
                  [KeyboardButton(text="📊 Статистика за месяц"),
                   KeyboardButton(text="🔗 Привязки")]],
        resize_keyboard=True)

def pick_student_free(free):
    kb, row = [], []
    for name in free:
        row.append(InlineKeyboardButton(text=name, callback_data=f"bd:{STUDENTS.index(name)}"))
        if len(row) == 2:
            kb.append(row); row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def pick_reason():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r, callback_data=f"rs:{r}")] for r in REASONS])

class Bind(StatesGroup):
    student = State()

class Mark(StatesGroup):
    reason = State()
    period = State()

class Unbind(StatesGroup):
    student = State()

bot = Bot(token=TOKEN)
dp = Dispatcher()

@dp.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")
    await cb.answer()

# ---------- привязка при первом запуске ----------
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    if is_admin(m.from_user.id):
        await m.answer("Привет, староста! 👑\n"
                       "Одногруппники отмечаются сами, все отметки прилетают тебе.",
                       reply_markup=admin_menu())
        return
    key = str(m.from_user.id)
    if key in BINDINGS:
        await m.answer(f"С возвращением, {BINDINGS[key]}! 👋",
                       reply_markup=student_menu())
        return
    free = [s for s in STUDENTS if s not in BINDINGS.values()]
    if not free:
        await m.answer("Все фамилии уже заняты. Если это твой первый запуск — "
                       "попроси старосту сбросить привязку («🔗 Привязки»).")
        return
    await state.set_state(Bind.student)
    await m.answer("Привет! 👋 Один раз найди себя в списке — "
                   "этот аккаунт будет закреплён за тобой:",
                   reply_markup=pick_student_free(free))

@dp.callback_query(Bind.student, F.data.startswith("bd:"))
async def do_bind(cb: CallbackQuery, state: FSMContext):
    name = STUDENTS[int(cb.data.split(":")[1])]
    if name in BINDINGS.values():
        await cb.message.edit_text("Эта фамилия уже занята другим аккаунтом. "
                                   "Если это ты — попроси старосту сбросить привязку.")
        await state.clear()
        await cb.answer()
        return
    BINDINGS[str(cb.from_user.id)] = name
    save("bindings.json", BINDINGS)
    await state.clear()
    await cb.message.edit_text(
        f"✅ Готово! Теперь этот аккаунт — {name}.",
        reply_markup=student_menu())
    await cb.answer()
    try:
        await bot.send_message(ADMIN_ID, f"🔗 Новая привязка: {cb.from_user.full_name} → {name}")
    except Exception:
        pass

# ---------- студенты: отметка ----------
@dp.message(F.text == "🙋 Отметиться")
async def mark(m: Message, state: FSMContext):
    name = name_of(m.from_user.id)
    if not name:
        await m.answer("Сначала привяжи аккаунт: отправь /start и найди себя в списке.")
        return
    t = today()
    ahead = [d for d, data in ABSENT.items() if name in data and dkey(d) >= dkey(t)]
    if ahead:
        await m.answer(f"Ты уже отмечен(а) до {max(ahead, key=dkey)}.\n"
                       "Если срок изменился — сначала нажми «Отменить отметку», потом отметься заново.")
        return
    await state.update_data(name=name)
    await state.set_state(Mark.reason)
    await m.answer(f"{name}, причина отсутствия?", reply_markup=pick_reason())

@dp.callback_query(Mark.reason, F.data.startswith("rs:"))
async def ask_period(cb: CallbackQuery, state: FSMContext):
    reason = cb.data.split(":", 1)[1]
    await state.update_data(reason=reason)
    await state.set_state(Mark.period)
    await cb.message.edit_text(
        f"Причина: {reason}.\n\nНа сколько дней отметиться?\n"
        "Напиши период в формате 06.11.2026 - 12.11.2026 (через дефис)\n"
        "или отправь 0 — если только на сегодня.")
    await cb.answer()

@dp.message(Mark.period)
async def save_period(m: Message, state: FSMContext):
    data = await state.get_data()
    name, reason = data["name"], data["reason"]
    period = parse_period(m.text)
    if not period:
        await m.answer("Не поняла даты 🤔 Формат: 06.11.2026 - 12.11.2026 (через дефис) "
                        "или 0 — если только на сегодня. Попробуй ещё раз:")
        return
    start, end = period
    if (dkey(end) - dkey(start)).days + 1 > MAX_DAYS:
        await m.answer(f"Максимум {MAX_DAYS} дней за раз. Если болеешь дольше — "
                       f"отметься на {MAX_DAYS} дней, а потом продли.")
        return
    days = days_between(start, end)
    for d in days:
        ABSENT.setdefault(d, {})[name] = reason
    save("absent.json", ABSENT)
    await state.clear()
    if start == end:
        text = f"✅ {name} — {reason} ({start})."
    else:
        text = (f"✅ {name} — {reason}.\n"
                f"Период: с {start} по {end} ({len(days)} дн.).")
    await m.answer(text + "\nЕсли выздоровеешь раньше — нажми «Отменить отметку».")
    try:
        await bot.send_message(ADMIN_ID, f"🆕 {text}\n(отметился: {m.from_user.full_name})")
    except Exception:
        pass

# ---------- студенты: отмена ----------
@dp.message(F.text == "❌ Отменить отметку")
async def unmark(m: Message):
    name = name_of(m.from_user.id)
    if not name:
        await m.answer("Сначала привяжи аккаунт: отправь /start.")
        return
    t = today()
    ahead = sorted((d for d, data in ABSENT.items() if name in data and dkey(d) >= dkey(t)),
                   key=dkey)
    if not ahead:
        await m.answer("Ты сейчас не отмечен(а) 🤔")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Только сегодня", callback_data="un:today"),
         InlineKeyboardButton(text="Весь период", callback_data="un:all")]])
    await m.answer(f"Ты отмечен(а) до {ahead[-1]}.\nЧто отменить?", reply_markup=kb)

@dp.callback_query(F.data.startswith("un:"))
async def do_unmark(cb: CallbackQuery):
    name = name_of(cb.from_user.id)
    if not name:
        await cb.answer("Сначала привяжи аккаунт через /start", show_alert=True)
        return
    mode = cb.data.split(":")[1]
    t = today()
    if mode == "today":
        days = [t]
    else:
        days = sorted((d for d, data in ABSENT.items() if name in data and dkey(d) >= dkey(t)),
                      key=dkey)
    removed = 0
    for d in days:
        if d in ABSENT and name in ABSENT[d]:
            del ABSENT[d][name]
            removed += 1
            if not ABSENT[d]:
                del ABSENT[d]
    save("absent.json", ABSENT)
    await cb.message.edit_text(
        f"✅ Сняла отметок: {removed}. {name} снова в строю!")
    await cb.answer()
    if removed:
        try:
            await bot.send_message(ADMIN_ID,
                f"↩️ {name} отменил(а) {removed} дн. отметок, начиная с {t}.")
        except Exception:
            pass

# ---------- староста ----------
def vedomost(day):
    data = ABSENT.get(day, {})
    lines = [f"📋 ВЕДОМОСТЬ, группа 98ТП — {day}",
             f"Всего учащихся: {len(STUDENTS)}",
             f"Отсутствуют: {len(data)} чел.", ""]
    if not data:
        lines.append("Отсутствующих нет 🎉")
    for i, (name, reason) in enumerate(data.items(), 1):
        lines.append(f"{i}. {name} — {reason}")
    return "\n".join(lines)

@dp.message(F.text == "📋 Ведомость за сегодня")
async def vedomost_today(m: Message):
    await m.answer(vedomost(today()))

@dp.message(F.text == "🗓 Будущие отметки")
async def future_marks(m: Message):
    t = today()
    lines = ["🗓 Предварительные отметки на будущее:"]
    found = False
    for d in sorted(ABSENT, key=dkey):
        if dkey(d) > dkey(t) and ABSENT[d]:
            found = True
            people = ", ".join(f"{n} ({r})" for n, r in ABSENT[d].items())
            lines.append(f"{d}: {people}")
    if not found:
        lines.append("Пока никто не отметился на будущее 🙂")
    await m.answer("\n".join(lines))

@dp.message(F.text == "📊 Статистика за месяц")
async def stats(m: Message):
    month = datetime.now().strftime("%m.%Y")
    counts = {s: 0 for s in STUDENTS}
    for day, data in ABSENT.items():
        if day.endswith(month):
            for name in data:
                if name in counts:
                    counts[name] += 1
    lines = [f"📊 Пропуски за {month}:"]
    rows = sorted(counts.items(), key=lambda x: -x[1])
    for name, c in rows:
        if c:
            lines.append(f"{name} — {c} раз(а)")
    if all(c == 0 for _, c in rows):
        lines.append("Пока что пусто 🙂")
    await m.answer("\n".join(lines))

@dp.message(F.text == "🔗 Привязки")
async def bindings_list(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    lines = ["🔗 Привязки аккаунтов:"]
    for tg_id, surname in BINDINGS.items():
        lines.append(f"• {surname} → id {tg_id}")
    free = [s for s in STUDENTS if s not in BINDINGS.values()]
    if free:
        lines.append("")
        lines.append("Ещё не привязались: " + ", ".join(free))
    await m.answer("\n".join(lines))
    bound = [s for s in STUDENTS if s in BINDINGS.values()]
    if bound:
        await state.set_state(Unbind.student)
        await m.answer("Кого отвязать? (если человек сменил аккаунт):",
                       reply_markup=pick_student_free(bound))

@dp.callback_query(Unbind.student, F.data.startswith("bd:"))
async def do_unbind(cb: CallbackQuery, state: FSMContext):
    name = STUDENTS[int(cb.data.split(":")[1])]
    for k in [k for k, v in BINDINGS.items() if v == name]:
        BINDINGS.pop(k)
    save("bindings.json", BINDINGS)
    await state.clear()
    await cb.message.edit_text(f"🔓 {name} отвязан(а). Пусть зайдёт в бота и привяжется заново через /start.")
    await cb.answer()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

asyncio.run(main())