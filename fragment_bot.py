import os
import logging
import asyncio

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from playwright.async_api import async_playwright

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("⚠️  You must set the BOT_TOKEN environment variable!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ─── TON-CONNECT FLOW ──────────────────────────────────────────────────────────
async def do_ton_connect(chat_target: Message):
    await chat_target.answer("🔗 Opening Fragment and popping up TON-Connect…")
    playwright = await async_playwright().start()
    browser = context = page = None

    try:
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        # 1) Go to Fragment
        await page.goto("https://fragment.com", timeout=60000)

        # 2) Click the desktop "Connect TON" button by its text
        await page.wait_for_selector("button:has-text('Connect TON')", timeout=10000)
        await page.click("button:has-text('Connect TON')")

        # 3) Wait for the QR modal
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)

        # 4) Tap the QR image → triggers “Link Copied”
        await page.click("#tc-widget-root img", timeout=5000)

        # 5) Wait for “Link Copied” toast
        await page.wait_for_selector("text=Link Copied", timeout=5000)

        # 6) Read from clipboard
        link = await page.evaluate("() => navigator.clipboard.readText()")
        await chat_target.answer(f"✅ TON-Connect link copied:\n{link}")

    except Exception as e:
        logging.exception(e)
        await chat_target.answer(f"❌ Oops, something went wrong:\n```\n{e}\n```")

    finally:
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        await playwright.stop()

# ─── COMMAND HANDLER ───────────────────────────────────────────────────────────
@dp.message(Command("connect"))
async def cmd_connect(message: Message):
    await do_ton_connect(message)

# ─── RUN IT ────────────────────────────────────────────────────────────────────
async def main():
    # start_polling takes the Bot instance and your Dispatcher
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
