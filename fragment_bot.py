import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command
from aiogram.filters.text import Text

from playwright.async_api import async_playwright

API_TOKEN = "YOUR_BOT_TOKEN_HERE"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# — reusable connect logic —
async def do_ton_connect(message: Message):
    await message.answer("⏳ Opening fragment.com and copying your TON-Connect link…")
    playwright, browser, context, page = await async_playwright().start(), None, None, None
    try:
        # 1) start browser
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        # 2) go & click desktop “Connect TON”
        await page.goto("https://fragment.com", timeout=60000)
        await page.wait_for_selector("button[aria-label='Connect TON']", timeout=10000)
        await page.click("button[aria-label='Connect TON']")

        # 3) wait for TON-Connect modal
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)

        # 4) click the QR image itself → triggers copy
        await page.click("#tc-widget-root img", timeout=5000)

        # 5) wait for “Link Copied”
        await page.wait_for_selector("text=Link Copied", timeout=5000)

        # 6) read clipboard
        link = await page.evaluate("() => navigator.clipboard.readText()")

        # 7) send link
        await message.answer(f"✅ Here’s your TON-Connect link:\n{link}")

    except Exception as e:
        logging.exception(e)
        await message.answer(f"❌ Oops, something broke:\n```\n{e}\n```")
    finally:
        if page:    await page.close()
        if context: await context.close()
        if browser: await browser.close()
        await playwright.stop()

# — /start → show inline button —
@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ InlineKeyboardButton("🔗 Connect TON", callback_data="connect_ton") ]
    ])
    await message.answer(
        "Welcome! Tap the button below to open Fragment and copy your TON-Connect link:",
        reply_markup=kb
    )

# — handle button press —
@dp.callback_query(Text("connect_ton"))
async def on_connect_ton(call: CallbackQuery):
    # remove the inline keyboard to avoid double-clicks
    await call.message.edit_reply_markup(None)
    await call.answer()  # acknowledge the tap
    # run our connect routine
    await do_ton_connect(call.message)

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
