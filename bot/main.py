import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.enums import ParseMode
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from db import (
    init_db, upsert_user, update_location, add_friend, get_friends,
    get_friend_ids, add_marker, get_all_markers, delete_marker, get_user
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
API_SECRET = os.getenv("API_SECRET", "supersecret")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# ==================== Pydantic models ====================

class LocationUpdate(BaseModel):
    lat: float
    lng: float
    battery: Optional[int] = None


class MarkerCreate(BaseModel):
    lat: float
    lng: float
    note: str = ""
    marker_type: str = "custom"  # danger / safe / friend / custom


class SosRequest(BaseModel):
    lat: float
    lng: float
    message: str = "🚨 SOS!"


# ==================== FastAPI ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def check_secret(x_api_secret: str = Header(None)):
    if x_api_secret != API_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/api/markers")
async def api_get_markers(x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    return await get_all_markers()


@app.post("/api/markers")
async def api_create_marker(data: MarkerCreate, tg_id: int, x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    marker_id = await add_marker(data.lat, data.lng, data.note, data.marker_type, tg_id)
    return {"id": marker_id, "ok": True}


@app.delete("/api/markers/{marker_id}")
async def api_delete_marker(marker_id: int, tg_id: int, x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    ok = await delete_marker(marker_id, tg_id)
    return {"ok": ok}


@app.post("/api/location")
async def api_update_location(data: LocationUpdate, tg_id: int, x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    await update_location(tg_id, data.lat, data.lng, data.battery)
    return {"ok": True}


@app.get("/api/friends/{tg_id}")
async def api_get_friends(tg_id: int, x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    return await get_friends(tg_id)


@app.post("/api/sos")
async def api_sos(data: SosRequest, tg_id: int, x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    user = await get_user(tg_id)
    name = user.get("first_name") or user.get("username") or str(tg_id) if user else str(tg_id)

    friends = await get_friend_ids(tg_id)
    if not friends:
        return {"ok": False, "error": "no_friends"}

    text = (
        f"🚨 <b>SOS от {name}!</b>\n\n"
        f"{data.message}\n\n"
        f"📍 <a href='https://maps.google.com/?q={data.lat},{data.lng}'>Открыть на карте</a>\n"
        f"Координаты: {data.lat:.6f}, {data.lng:.6f}"
    )

    sent = 0
    for fid in friends:
        try:
            await bot.send_message(
                fid,
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
            # Также отправляем локацию отдельным сообщением
            await bot.send_location(fid, latitude=data.lat, longitude=data.lng)
            sent += 1
        except Exception as e:
            logger.warning(f"Cannot send SOS to {fid}: {e}")

    return {"ok": True, "sent": sent}


@app.get("/api/me/{tg_id}")
async def api_me(tg_id: int, x_api_secret: str = Header(None)):
    check_secret(x_api_secret)
    user = await get_user(tg_id)
    return user or {}


# ==================== Bot handlers ====================

def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🗺 Открыть карту", web_app=WebAppInfo(url=WEBAPP_URL))],
            [KeyboardButton(text="👥 Мои друзья"), KeyboardButton(text="➕ Добавить друга")],
            [KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )


@dp.message(CommandStart())
async def cmd_start(message: Message):
    await upsert_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name,
        message.from_user.last_name
    )
    await message.answer(
        "👋 Привет! Это <b>SecNVK</b> — карта меток + SOS для своего круга.\n\n"
        "• Долгое нажатие на карте → добавить метку с заметкой\n"
        "• Красная кнопка SOS → мгновенное оповещение всем друзьям\n"
        "• Друзья видят твои метки и твою позицию\n\n"
        "Нажми «Открыть карту» 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=main_keyboard()
    )


@dp.message(Command("map"))
async def cmd_map(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺 Открыть карту", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
    await message.answer("Открываю карту:", reply_markup=kb)


@dp.message(F.text == "🗺 Открыть карту")
async def open_map_btn(message: Message):
    await cmd_map(message)


@dp.message(F.text == "👥 Мои друзья")
async def my_friends(message: Message):
    friends = await get_friends(message.from_user.id)
    if not friends:
        await message.answer("У тебя пока нет друзей.\nНажми «➕ Добавить друга» и отправь @username.")
        return

    lines = []
    for f in friends:
        name = f.get("first_name") or f.get("username") or str(f["tg_id"])
        battery = f"🔋{f['battery']}%" if f.get("battery") is not None else ""
        loc = "✅" if f.get("lat") else "❌"
        lines.append(f"• {name} {battery} {loc}")

    await message.answer(
        "<b>Твои друзья:</b>\n" + "\n".join(lines),
        parse_mode=ParseMode.HTML
    )


@dp.message(F.text == "➕ Добавить друга")
async def add_friend_prompt(message: Message):
    await message.answer(
        "Отправь @username друга (он должен хотя бы раз написать боту /start).\n"
        "Или перешли любое его сообщение боту."
    )


@dp.message(F.text.startswith("@"))
async def add_friend_by_username(message: Message):
    username = message.text.strip().lstrip("@").lower()
    # Ищем пользователя по username в нашей базе
    # Для простоты: пользователь должен сам написать боту
    await message.answer(
        f"Пока ищем @{username}...\n\n"
        "Попроси друга написать боту /start, а потом ты снова отправь его @username "
        "или попроси его добавить тебя."
    )
    # В реальном боте здесь можно сделать поиск, но без полной базы всех TG-юзеров
    # лучше использовать deep-link или пересылку сообщений


@dp.message(F.forward_from | F.forward_origin)
async def add_friend_by_forward(message: Message):
    # Упрощённо: если переслали сообщение от человека
    from_user = message.forward_from
    if not from_user:
        await message.answer("Не могу определить пользователя из пересланного сообщения (приватность).")
        return

    await upsert_user(from_user.id, from_user.username, from_user.first_name, from_user.last_name)
    ok = await add_friend(message.from_user.id, from_user.id)
    if ok:
        await message.answer(f"✅ {from_user.first_name or from_user.username} добавлен в друзья (взаимно).")
        try:
            await bot.send_message(
                from_user.id,
                f"👋 {message.from_user.first_name} добавил тебя в друзья в CarWatch!"
            )
        except Exception:
            pass
    else:
        await message.answer("Не удалось добавить (возможно уже есть).")


@dp.message(F.text == "ℹ️ Помощь")
async def help_cmd(message: Message):
    await message.answer(
        "<b>Как пользоваться:</b>\n\n"
        "1. Открой карту кнопкой\n"
        "2. Долгое нажатие → новая метка (можно указать тип и заметку)\n"
        "3. Тап по метке → подробности\n"
        "4. Красная кнопка SOS → всем друзьям придёт алерт + твоя геолокация\n"
        "5. Добавляй друзей через пересылку сообщения или @username\n\n"
        "Метки видят все, кто пользуется ботом. Позиции друзей — только взаимные друзья.",
        parse_mode=ParseMode.HTML
    )


@dp.message(Command("sos"))
async def cmd_sos(message: Message):
    await message.answer(
        "Лучше нажимай красную кнопку SOS внутри карты — так сразу уйдёт твоя точная геолокация.\n"
        "Или открой карту и нажми SOS."
    )


# ==================== Run ====================

async def run_bot():
    await init_db()
    logger.info("Bot starting...")
    await dp.start_polling(bot)


def run_api():
    uvicorn.run(app, host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", 8000)))


if __name__ == "__main__":
    # Для простоты запускаем только бота.
    # API можно запускать отдельно или через один процесс с asyncio.
    asyncio.run(run_bot())
