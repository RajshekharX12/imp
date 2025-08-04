import asyncio
import logging
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from playwright.async_api import async_playwright

# ─── Load environment variables from .env ────────────────────────────────────────────
load_dotenv()  # Reads BOT_TOKEN=... from your .env file

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("⚠️  You must set the BOT_TOKEN environment variable in your .env file!")

# ─── Configure logging and bot ──────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


async def do_ton_connect(chat_target: Message):
    """Opens Fragment, triggers TON-Connect QR, copies the link, and sends it back."""
    await chat_target.answer("🔗 Opening Fragment and popping up TON-Connect…")
    playwright = await async_playwright().start()
    browser = context = page = None

    try:
        # Launch headless Chromium
        browser = await playwright.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context()
        page = await context.new_page()

        # 1) Go to Fragment
        await page.goto("https://fragment.com", timeout=60000)

        # 2) Click the desktop "Connect TON" button
        await page.wait_for_selector("button[aria-label='Connect TON']", timeout=10000)
        await page.click("button[aria-label='Connect TON']")

        # 3) Wait for the TON-Connect QR modal
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)

        # 4) Click the QR image itself → this triggers “Link Copied”
        await page.click("#tc-widget-root img", timeout=5000)

        # 5) Wait for the confirmation toast
        await page.wait_for_selector("text=Link Copied", timeout=5000)

        # 6) Read the copied link from the clipboard
        link = await page.evaluate("() => navigator.clipboard.readText()")

        # Send it back to the user
        await chat_target.answer(f"✅ TON-Connect link copied:\n{link}")

    except Exception as e:
        logging.exception(e)
        await chat_target.answer(f"❌ Oops, something went wrong:\n```\n{e}\n```")

    finally:
        # Clean up Playwright resources
        if page:
            await page.close()
        if context:
            await context.close()
        if browser:
            await browser.close()
        await playwright.stop()


@dp.message(Command("connect"))
async def cmd_connect(message: Message):
    await do_ton_connect(message)


async def main():
    try:
        # Start polling for updates
        await dp.start_polling(bot, skip_updates=True)
    finally:
        # Ensure the HTTP session is closed on exit
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
