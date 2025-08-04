# file: fragment_bot.py

import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
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
_playwright = None      # playwright instance
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """Launch or return a persistent headless Chromium context."""
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright…")
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
    """Close browser context & Playwright to clear session."""
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
    try:
        # 1) Click “Connect TON”
        await page.click("button.ton-auth-link:visible")
        # 2) Wait for the modal
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)
        # 3) Click “Copy Link”
        copy_btn = page.locator("#tc-widget-root button:has-text('Copy Link')")
        await copy_btn.click()
        # 4) Read the link from clipboard
        link = await page.evaluate("() => navigator.clipboard.readText()")
        if not link:
            raise RuntimeError("No link in clipboard")

        # 5) Send link + logout
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 Log out", callback_data="logout")]])
        await msg.answer(f"🔗 TON-Connect link:\n`{link}`", parse_mode="Markdown", reply_markup=kb)

        # 6) Wait for the “Connect TON” button to disappear (handshake)
        try:
            await page.wait_for_selector("button.ton-auth-link", state="detached", timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("Handshake timeout; maybe already connected.")

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
    await destination.answer("🔒 You’ve been logged out. Use `/connect` to reconnect.", parse_mode="Markdown")

# ─── Inline Query ────────────────────────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full = f"+888{suffix}"
    code = "❌ Error"

    page = await init_browser()
    try:
        await page.goto("https://fragment.com/my/numbers", wait_until="domcontentloaded")
        row = await page.wait_for_selector(
            f"xpath=//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']",
            timeout=7000
        )
        await row.click("button:has-text('Get Login Code')")
        el = await page.wait_for_selector("div.login-code", timeout=10000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        code = f"⚠️ {e}"

    result = InlineQueryResultArticle(
        id=suffix,
        title=f"{full} → {code}",
        input_message_content=InputTextMessageContent(f"Login code for {full}: {code}")
    )
    await inline_q.answer(results=[result], cache_time=5)

# ─── BOT SETUP & RUN ─────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # register handlers
    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started: /connect, /logout; inline → type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
