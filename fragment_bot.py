# file: fragment_bot.py

import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from playwright.async_api import async_playwright, BrowserContext, Page
from dotenv import load_dotenv

# ─── CONFIG & LOGGING ───────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logging.error("BOT_TOKEN is not set in .env")
    exit(1)

# ─── GLOBAL BROWSER STATE ────────────────────────────────────────────────────────
_playwright = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright in headless mode…")
    _playwright = await async_playwright().start()
    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        permissions=["clipboard-read"]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com")
    return _page

async def shutdown_browser():
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    page = await init_browser()
    await msg.answer("🔗 Opening Fragment and popping up TON-Connect…")

    try:
        # 1) Click the *visible* Connect TON button
        btn = page.locator("button.ton-auth-link:visible").first
        await btn.click()

        # 2) **Wait for the QR image** to become visible (instead of the wrapper div)
        await page.wait_for_selector("#tc-widget-root img", state="visible", timeout=10000)

        # 3) Extract the deep-link
        link = None
        open_a = page.locator("#tc-widget-root a:has-text('Open Link')").first
        if await open_a.count():
            link = await open_a.get_attribute("href")
        if not link:
            copy_btn = page.locator("#tc-widget-root button:has-text('Copy Link')").first
            if await copy_btn.count():
                link = await copy_btn.get_attribute("data-clipboard-text")

        if not link:
            return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

        # 4) Send link + logout button
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
        ])
        await msg.answer(
            f"🔗 Copy this link into your TON wallet to connect:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb
        )

        # 5) Wait for handshake (button disappears)
        try:
            await page.wait_for_selector("button.ton-auth-link:visible", state="detached", timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("Handshake timeout; you may already be connected.")
    except Exception as e:
        logging.exception(e)
        await msg.answer(f"⚠️ Error during /connect:\n```\n{e}\n```")

# ─── /logout ─────────────────────────────────────────────────────────────────────
async def on_logout_cmd(msg: types.Message):
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    await call.answer()
    await do_logout(call.message)

async def do_logout(destination):
    await shutdown_browser()
    await destination.answer(
        "🔒 You’ve been logged out. Use `/connect` to reconnect.",
        parse_mode="Markdown"
    )

# ─── Bot Setup & Run ─────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")

    logging.info("🤖 Bot started; commands: /connect, /logout")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
