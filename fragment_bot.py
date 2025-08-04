import os
import logging
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

        # 1) Navigate
        await page.goto("https://fragment.com", timeout=60000)

        # 2) Click the desktop "Connect TON" button by its visible text
        await page.wait_for_selector("button:has-text('Connect TON')", timeout=10000)
        await page.click("button:has-text('Connect TON')")

        # 3) Wait for the QR modal to appear
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)

        # 4) Click the QR itself to trigger “Link Copied”
        await page.click("#tc-widget-root img", timeout=5000)

        # 5) Wait for the confirmation toast
        await page.wait_for_selector("text=Link Copied", timeout=5000)

        # 6) Read from the clipboard
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

# ─── BOT COMMAND ───────────────────────────────────────────────────────────────
@dp.message(Command("connect"))
async def cmd_connect(message: Message):
    await do_ton_connect(message)

# ─── RUNNER ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True)
