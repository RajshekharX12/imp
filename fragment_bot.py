import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import Command  # only Command, no Text

from playwright.async_api import async_playwright

API_TOKEN = "YOUR_BOT_TOKEN_HERE"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

async def do_ton_connect(chat):
    """
    Opens fragment.com headlessly, clicks the Connect TON button,
    copies the TON-Connect link, and sends it back to the user.
    """
    await chat.answer("⏳ Opening fragment.com and copying your TON-Connect link…")
    playwright = await async_playwright().start()
    browser = context = page = None

    try:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        # 1) Navigate & click “Connect TON”
        await page.goto("https://fragment.com", timeout=60000)
        await page.wait_for_selector("button[aria-label='Connect TON']", timeout=10000)
        await page.click("button[aria-label='Connect TON']")

        # 2) Wait for the TON-Connect modal
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)

        # 3) Click the QR image itself (this triggers “Link Copied”)
        await page.click("#tc-widget-root img", timeout=5000)
        await page.wait_for_selector("text=Link Copied", timeout=5000)

        # 4) Read from the clipboard
        link = await page.evaluate("() => navigator.clipboard.readText()")

        # 5) Send it back
        await chat.answer(f"✅ Here’s your TON-Connect link:\n{link}")

    except Exception as e:
        logging.exception(e)
        await chat.answer(f"❌ Oops, something went wrong:\n{e}")

    finally:
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        await playwright.stop()


@dp.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [ InlineKeyboardButton("🔗 Connect TON", callback_data="connect_ton") ]
    ])
    await message.answer(
        "Welcome! Tap the button below to copy your TON-Connect link:",
        reply_markup=kb
    )


# instead of aiogram.filters.Text, just match the callback_data manually
@dp.callback_query(lambda c: c.data == "connect_ton")
async def on_connect_ton(call: CallbackQuery):
    # remove the inline keyboard so they can’t tap it twice
    await call.message.edit_reply_markup(None)
    await call.answer()  # ack the tap
    await do_ton_connect(call.message)


if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
