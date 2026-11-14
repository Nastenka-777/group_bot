import asyncio, json, os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, KeyboardButton,
                           Message, ReplyKeyboardMarkup)

TOKEN = os.environ.get("TELEGRAM_TOKEN") or os.environ["BOT_TOKEN"]
ADMIN_ID = 5132006984
SECRET_CODE = "VoronkoSV98TP"  # кодовое слово для кураторши; /curator 0 — снять

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

REASONS = ["По болезни 🤒", "По заявлению ✍🏻", "По повестке 👨🏽", "По приказу 💼",
           "Без уважительной причины 🤷🏽‍♀️"]
MAX_DAYS = 100  # максимальная длина периода отметки


def load(name, default):
    try:
        with open(name, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(name, data):
    with open(name, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# старые записи в absent.json — просто строки; приводим их к новому виду
def normalize(rec):
    if isinstance(rec, str):
        return {"reason": rec, "hours": None, "cert": None}
    return rec


ABSENT = {d: {n: normalize(r) for n, r in data.items()}
          for d, data in load("absent.json", {}).items()}
BINDINGS = load("bindings.json", {})  # "id аккаунта" -> фамилия
CURATOR = load("curator.json", {})    # {"id": ...} — телеграм-id кураторши
CURATOR_NAME = "Воронько С.В."


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


def parse_hours(s):
    """'2' -> 2, '2 ч'/'2 часа' -> 2, '2,5' -> 2.5, иначе 'bad'."""
    s = (s or "").strip().lower().replace("ч", "").replace(",", ".").strip()
    try:
        h = float(s)
    except ValueError:
        return "bad"
    if 0.5 <= h <= 24:
        return int(h) if h == int(h) else h
    return "bad"


def days_between(start, end):
    d0, d1 = dkey(start), dkey(end)
    out, cur = [], d0
    while cur <= d1:
        out.append(cur.strftime("%d.%m.%Y"))
        cur += timedelta(days=1)
    return out


def is_admin(user_id):
    return user_id == ADMIN_ID


def is_curator(user_id):
    return CURATOR.get("id") == user_id


def is_staff(user_id):
    return is_admin(user_id) or is_curator(user_id)


def name_of(user_id):
    return BINDINGS.get(str(user_id))


def fmt_rec(rec):
    """Красивое представление: причина (часы) + статус справки."""
    if isinstance(rec, str):
        return rec
    s = rec["reason"]
    if rec.get("hours"):
        h = rec["hours"]
        h = int(h) if h == int(h) else h
        s += f" ({h} ч)"
    c = rec.get("cert")
    if c:
        s += " [📄 " + ("ст✅" if c.get("admin") else "ст⏳")
        s += " " + ("кур✅" if c.get("curator") else "кур⏳") + "]"
    return s


async def notify(text):
    """Уведомление старосте и кураторше (кому доступно)."""
    for uid in [ADMIN_ID, CURATOR.get("id")]:
        if uid:
            try:
                await bot.send_message(uid, text)
            except Exception:
                pass


def student_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🙋 Отметиться"),
                   KeyboardButton(text="❌ Отменить отметку")],
                  [KeyboardButton(text="ℹ️ Инструкция")]],
        resize_keyboard=True)


def staff_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📋 Ведомость за сегодня"),
                   KeyboardButton(text="🗓 Будущие отметки")],
                  [KeyboardButton(text="📊 Статистика за месяц"),
                   KeyboardButton(text="🔗 Привязки")],
                  [KeyboardButton(text="📄 Справки"),
                   KeyboardButton(text="ℹ️ Инструкция")]],
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
    # callback_data — только номер причины, текст не влезает в лимит 64 байта
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=r, callback_data=f"rs:{i}")]
        for i, r in enumerate(REASONS)])


def pick_cert():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Есть справка", callback_data="cr:y"),
         InlineKeyboardButton(text="🚫 Справки нет", callback_data="cr:n")]])


def student_help():
    return (
        "ℹ️ ИНСТРУКЦИЯ ДЛЯ УЧАЩИХСЯ\n\n"
        "1️⃣ Первый запуск\n"
        "Нажми /start (или кнопку «Запустить») и найди себя в списке.\n"
        "Аккаунт закрепится за твоей фамилией - больше это не понадобится.\n\n"
        "2️⃣ Отметиться (сообщить об отсутствии)\n"
        "Кнопка «🙋 Отметиться» → выбери причину → напиши, сколько часов "
        "будешь отсутствовать (например, 2 или 4,5 - столько, сколько "
        "нужно по расписанию твоей подгруппы) → "
        "напиши период: дату или диапазон 06.11.2026 - 12.11.2026, "
        "или 0, если только сегодня → ответь, есть ли справка.\n\n"
        "3️⃣ Если выздоровел(а) раньше\n"
        "Кнопка «❌ Отменить отметку» → выбери: только сегодня или весь период.\n\n"
        "4️⃣ Справка 📄\n"
        "Если отметился(-ась) со справкой - староста и кураторша её подтвердят, "
        "тебе придёт уведомление.\n\n"
        "⚠️ Важно:\n"
        "• Отмечаться можно заранее - на будущее.\n"
        "• Второй раз отметиться до окончания срока нельзя: сначала отмени.\n"
        "• Если сменил(а) аккаунт - попроси старосту отвязать старый («🔗 Привязки»)."
    )


def staff_help():
    return (
        "ℹ️ ИНСТРУКЦИЯ ДЛЯ СТАРОСТЫ И КУРАТОРШИ\n\n"
        "📋 Ведомость за сегодня - кто отсутствует сейчас, с причинами, "
        "часами и статусом справок.\n"
        "🗓 Будущие отметки - кто заранее отметился на будущие даты.\n"
        "📊 Статистика за месяц - сколько раз каждый отсутствовал.\n"
        "🔗 Привязки - кто к какому аккаунту привязан. "
        "Староста может отвязать человека (например, если он сменил аккаунт), "
        "кураторша - просмотр.\n"
        "📄 Справки - список справок, ожидающих подтверждения. "
        "Каждая справка подтверждается дважды: старостой и кураторшей.\n\n"
        "Уведомления о новых отметках, отменах и привязках приходят автоматически."
    )


class Bind(StatesGroup):
    student = State()


class Mark(StatesGroup):
    reason = State()
    hours = State()
    period = State()
    cert = State()


class Unbind(StatesGroup):
    student = State()


bot = Bot(token=TOKEN)
dp = Dispatcher()


@dp.callback_query(F.data == "cancel")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.")
    await cb.answer()


# ---------- команды служебные ----------
@dp.message(Command("myid"))
async def my_id(m: Message):
    await m.answer(f"Твой id: {m.from_user.id}\n"
                   "Отправь этот номер старосте, если она попросила.")


@dp.message(Command("curator"))
async def set_curator(m: Message):
    if not is_admin(m.from_user.id):
        return
    parts = (m.text or "").split()
    if len(parts) == 1:
        await m.answer(f"Назначить кураторшу можно и проще: пусть она отправит боту "
                       f"кодовое слово. А этой командой — по id:\n"
                       f"Формат: /curator 123456789\n"
                       f"id {CURATOR_NAME} узнается так: пусть она отправит боту /myid\n"
                       "и пришлёт тебе номер. /curator 0 — снять куратора.")
        return
    try:
        cid = int(parts[1])
    except ValueError:
        await m.answer("id должен быть числом.")
        return
    if cid == 0:
        CURATOR.clear()
        save("curator.json", CURATOR)
        await m.answer("🔓 Куратор снята.")
        return
    CURATOR["id"] = cid
    save("curator.json", CURATOR)
    await m.answer(f"✅ Куратор назначена (id {cid}). Пусть она отправит боту /start.")


# ---------- кураторша по кодовому слову ----------
@dp.message(lambda m: m.text == SECRET_CODE)
async def join_curator(m: Message):
    if is_admin(m.from_user.id):
        await m.answer("Ты и так староста 😉 Куратором быть не обязательно.")
        return
    if is_curator(m.from_user.id):
        await m.answer(f"Куратор подтвержден, {CURATOR_NAME} 🙌",
                       reply_markup=staff_menu())
        return
    if CURATOR:
        await m.answer("Кураторша уже назначена. Если это нужно поменять - "
                       "пусть староста отправит /curator 0.")
        return
    CURATOR["id"] = m.from_user.id
    save("curator.json", CURATOR)
    await m.answer(f"✅ Здравствуйте, {CURATOR_NAME}! Вы назначены кураторшей. "
                   "Вам доступны ведомости, статистика и подтверждение справок.",
                   reply_markup=staff_menu())
    try:
        await bot.send_message(ADMIN_ID, f"👩‍🏫 Кураторша присоединилась: {CURATOR_NAME} "
                                         f"(id {m.from_user.id}).")
    except Exception:
        pass


# ---------- привязка при первом запуске ----------
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    if is_admin(m.from_user.id):
        await m.answer("Привет, староста! 💅🏻 \n"
                       "Одногруппники отмечаются сами, все отметки прилетают тебе.",
                       reply_markup=staff_menu())
        return
    if is_curator(m.from_user.id):
        await m.answer(f"Здравствуйте, {CURATOR_NAME}! 👋\n"
                       "Режим куратора: просмотр ведомостей и подтверждение справок.",
                       reply_markup=staff_menu())
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
    await m.answer("📌 Привет! Один раз найди себя в списке — "
                   "этот аккаунт будет закреплён за тобой:",
                   reply_markup=pick_student_free(free))


@dp.callback_query(Bind.student, F.data.startswith("bd:"))
async def do_bind(cb: CallbackQuery, state: FSMContext):
    name = STUDENTS[int(cb.data.split(":")[1])]
    if name in BINDINGS.values():
        await cb.message.edit_text("Эта фамилия уже занята другим аккаунтом. ❌🙅🏽 "
                                   "Если это ты — попроси старосту сбросить привязку.")
        await state.clear()
        await cb.answer()
        return
    BINDINGS[str(cb.from_user.id)] = name
    save("bindings.json", BINDINGS)
    await state.clear()
    # edit_text не принимает reply-клавиатуру — меню отправляем отдельным сообщением
    await cb.message.edit_text(f"✅ Готово! Теперь этот аккаунт — {name}.")
    await cb.message.answer("Что дальше?", reply_markup=student_menu())
    await cb.answer()
    try:
        await notify(f"🔗 Новая привязка: {cb.from_user.full_name} → {name}")
    except Exception:
        pass


# ---------- инструкция ----------
@dp.message(F.text == "ℹ️ Инструкция")
async def help_btn(m: Message):
    if is_staff(m.from_user.id):
        await m.answer(staff_help())
    else:
        await m.answer(student_help())


# ---------- студенты: отметка ----------
@dp.message(F.text == "🙋 Отметиться")
async def mark(m: Message, state: FSMContext):
    name = name_of(m.from_user.id)
    if not name:
        await m.answer("📌 Сначала привяжи аккаунт: отправь /start и найди себя в списке.")
        return
    t = today()
    ahead = [d for d, data in ABSENT.items() if name in data and dkey(d) >= dkey(t)]
    if ahead:
        await m.answer(f"✋🏼 Ты уже отмечен(а) до {max(ahead, key=dkey)}.\n"
                       "Если срок изменился ✏️ — сначала нажми «❌ Отменить отметку», "
                       "потом отметься заново.")
        return
    await state.update_data(name=name)
    await state.set_state(Mark.reason)
    await m.answer(f"{name}, причина отсутствия? 🔍", reply_markup=pick_reason())


@dp.callback_query(Mark.reason, F.data.startswith("rs:"))
async def ask_hours(cb: CallbackQuery, state: FSMContext):
    reason = REASONS[int(cb.data.split(":", 1)[1])]
    await state.update_data(reason=reason)
    await state.set_state(Mark.hours)
    await cb.message.edit_text(
        f"Причина: {reason}.\n\n⏰ Сколько часов будешь отсутствовать?\n"
        "Напиши число (например, 2 или 4.5 или 8) — столько, сколько "
        "нужно по расписанию твоей подгруппы.")
    await cb.answer()


@dp.message(Mark.hours)
async def ask_period(m: Message, state: FSMContext):
    hours = parse_hours(m.text)
    if hours == "bad":
        await m.answer("Не поняла часы ❓ Напиши число от 0,5 до 24 — столько, "
                       "сколько нужно по расписанию твоей подгруппы (например, 6)")
        return
    await state.update_data(hours=hours)
    await state.set_state(Mark.period)
    await m.answer(
        "На сколько дней отметиться? 🔍\n"
        "Напиши период в формате 06.11.2026 - 12.11.2026 (через дефис)\n"
        "или отправь 0 — если только на сегодня.")


@dp.message(Mark.period)
async def ask_cert(m: Message, state: FSMContext):
    period = parse_period(m.text)
    if not period:
        await m.answer("Не поняла даты ❓❌ Формат: 06.11.2026 - 12.11.2026 (через дефис) "
                       "или 0 — если только на сегодня. Попробуй ещё раз:")
        return
    start, end = period
    if (dkey(end) - dkey(start)).days + 1 > MAX_DAYS:
        await m.answer(f"Максимум {MAX_DAYS} дней за раз. Если болеешь дольше — "
                       f"отметься на {MAX_DAYS} дней, а потом продли.")
        return
    await state.update_data(start=start, end=end)
    await state.set_state(Mark.cert)
    await m.answer("Есть ли справка? 📄", reply_markup=pick_cert())


@dp.callback_query(Mark.cert, F.data.startswith("cr:"))
async def save_mark(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    name, reason = data["name"], data["reason"]
    hours, has_cert = data["hours"], cb.data == "cr:y"
    start, end = data["start"], data["end"]
    days = days_between(start, end)
    rec = {"reason": reason, "hours": hours,
           "cert": {"admin": False, "curator": False} if has_cert else None}
    for d in days:
        ABSENT.setdefault(d, {})[name] = rec
    save("absent.json", ABSENT)
    await state.clear()
    text = f"✅ {name} — {fmt_rec(rec)}"
    if start != end:
        text += f"\nПериод: с {start} по {end} ({len(days)} дн.)."
    if has_cert:
        text += "\n📄 Справка/заявление отмечена(-о): ждёт подтверждения старосты и кураторши."
    text += "\nЕсли выздоровеешь раньше — нажми «❌ Отменить отметку»."
    await cb.message.edit_text(text)
    await cb.answer()
    try:
        await notify(f"🆕 {text}\n(отметился: {cb.from_user.full_name})")
    except Exception:
        pass


# ---------- студенты: отмена ----------
@dp.message(F.text == "❌ Отменить отметку")
async def unmark(m: Message):
    name = name_of(m.from_user.id)
    if not name:
        await m.answer("Сначала привяжи аккаунт ✍🏻: отправь /start.")
        return
    t = today()
    ahead = sorted((d for d, data in ABSENT.items() if name in data and dkey(d) >= dkey(t)),
                   key=dkey)
    if not ahead:
        await m.answer("Ты сейчас не отмечен(а) 🙅🏽")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Только сегодня", callback_data="un:today"),
         InlineKeyboardButton(text="Весь период", callback_data="un:all")]])
    await m.answer(f"Ты отмечен(а) до {ahead[-1]}.\nЧто отменить?", reply_markup=kb)


@dp.callback_query(F.data.startswith("un:"))
async def do_unmark(cb: CallbackQuery):
    name = name_of(cb.from_user.id)
    if not name:
        await cb.answer("✍🏻 Сначала привяжи аккаунт через /start", show_alert=True)
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
        f"✅ Сняла отметок: {removed}. {name} снова присутствует.")
    await cb.answer()
    if removed:
        try:
            await notify(f"🔄 {name} отменил(а) {removed} дн. отметок, начиная с {t}.")
        except Exception:
            pass


# ---------- справки: подтверждение ----------
@dp.message(F.text == "📄 Справки")
async def certs_list(m: Message):
    if not is_staff(m.from_user.id):
        return
    role = "a" if is_admin(m.from_user.id) else "c"
    lines = ["📄 Справки:"]
    kb = []
    found = False
    for d in sorted(ABSENT, key=dkey):
        for name, rec in ABSENT[d].items():
            c = rec.get("cert") if isinstance(rec, dict) else None
            if not c:
                continue
            found = True
            st = []
            if c.get("admin"):
                st.append("ст✅")
            if c.get("curator"):
                st.append("кур✅")
            status = " / ".join(st) if st else "ждёт подтверждения"
            lines.append(f"• {d} — {name}: {fmt_rec(rec)} [{status}]")
            mine = c.get("admin") if role == "a" else c.get("curator")
            if not mine:
                kb.append([InlineKeyboardButton(
                    text=f"✅ Подтвердить: {name}, {d}",
                    callback_data=f"cf:{role}:{d}:{STUDENTS.index(name)}")])
    if not found:
        lines.append("Пока справок нет 🌪")
    await m.answer("\n".join(lines))
    if kb:
        await m.answer("Кого подтвердить?", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))


@dp.callback_query(F.data.startswith("cf:"))
async def confirm_cert(cb: CallbackQuery):
    _, role, day, idx = cb.data.split(":")
    if role == "a" and not is_admin(cb.from_user.id):
        await cb.answer("Только староста может это подтвердить.", show_alert=True)
        return
    if role == "c" and not is_curator(cb.from_user.id):
        await cb.answer("Только куратор может это подтвердить.", show_alert=True)
        return
    name = STUDENTS[int(idx)]
    rec = ABSENT.get(day, {}).get(name)
    if not rec or not rec.get("cert"):
        await cb.answer("Запись уже неактуальна.")
        return
    rec["cert"]["admin" if role == "a" else "curator"] = True
    save("absent.json", ABSENT)
    c = rec["cert"]
    if c.get("admin") and c.get("curator"):
        await cb.message.edit_text(
            f"✅ Справка {name} за {day} подтверждена старостой и кураторшей.")
        tg_id = next((uid for uid, n in BINDINGS.items() if n == name), None)
        if tg_id:
            try:
                await bot.send_message(int(tg_id),
                                       f"📄✅ Твоя справка за {day} подтверждена.")
            except Exception:
                pass
    else:
        await cb.message.edit_text(
            f"✅ Принято: {name}, {day}. Осталось подтвердить "
            f"{'кураторше' if role == 'a' else 'старосте'}.")
    await cb.answer()


# ---------- староста и кураторша: просмотр ----------
def vedomost(day):
    data = ABSENT.get(day, {})
    lines = [f"📋👫 ВЕДОМОСТЬ, группа 9️⃣8️⃣ТП — {day}",
             f"Всего учащихся: {len(STUDENTS)}",
             f"Отсутствуют: {len(data)} чел.", ""]
    if not data:
        lines.append("Отсутствующих нет ❌💻")
    for i, (name, rec) in enumerate(data.items(), 1):
        lines.append(f"{i}. {name} — {fmt_rec(rec)}")
    return "\n".join(lines)


@dp.message(F.text == "📋 Ведомость за сегодня")
async def vedomost_today(m: Message):
    await m.answer(vedomost(today()))


@dp.message(F.text == "🗓 Будущие отметки")
async def future_marks(m: Message):
    if not is_staff(m.from_user.id):
        return
    t = today()
    lines = ["🗓 Предварительные отметки на будущее:"]
    found = False
    for d in sorted(ABSENT, key=dkey):
        if dkey(d) > dkey(t) and ABSENT[d]:
            found = True
            people = ", ".join(f"{n} ({fmt_rec(r)})" for n, r in ABSENT[d].items())
            lines.append(f"{d}: {people}")
    if not found:
        lines.append("Пока никто не отметился на будущее ✋🏼")
    await m.answer("\n".join(lines))


@dp.message(F.text == "📊 Статистика за месяц")
async def stats(m: Message):
    if not is_staff(m.from_user.id):
        return
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
        lines.append("Пока что пусто 🌪")
    await m.answer("\n".join(lines))


@dp.message(F.text == "🔗 Привязки")
async def bindings_list(m: Message, state: FSMContext):
    if not is_staff(m.from_user.id):
        return
    lines = ["🔗 Привязки аккаунтов:"]
    for tg_id, surname in BINDINGS.items():
        lines.append(f"• {surname} → id {tg_id}")
    free = [s for s in STUDENTS if s not in BINDINGS.values()]
    if free:
        lines.append("")
        lines.append("Ещё не привязались ❓❌: " + ", ".join(free))
    await m.answer("\n".join(lines))
    if not is_admin(m.from_user.id):
        return  # кураторша только смотрит, отвязывать может староста
    bound = [s for s in STUDENTS if s in BINDINGS.values()]
    if bound:
        await state.set_state(Unbind.student)
        await m.answer("Кого отвязать? (если человек сменил аккаунт):",
                       reply_markup=pick_student_free(bound))


@dp.callback_query(Unbind.student, F.data.startswith("bd:"))
async def do_unbind(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id):
        await cb.answer("Отвязывать может только староста.", show_alert=True)
        return
    name = STUDENTS[int(cb.data.split(":")[1])]
    for k in [k for k, v in BINDINGS.items() if v == name]:
        BINDINGS.pop(k)
    save("bindings.json", BINDINGS)
    await state.clear()
    await cb.message.edit_text(
        f"🔓 {name} отвязан(а). ❌ Пусть зайдёт в бота и привяжется заново через /start.")
    await cb.answer()


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


asyncio.run(main())
