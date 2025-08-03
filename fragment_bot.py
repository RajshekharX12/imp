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

# ─── CONFIG & LOGGING ────────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ─── GLOBAL BROWSER STATE ────────────────────────────────────────────────────────
_playwright = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """Launch or reuse a persistent Playwright Chromium context (headless)."""
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Starting Playwright in headless mode…")
    _playwright = await async_playwright().start()
    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=True,               # ← HEADLESS on
        args=[
            "--no-sandbox",          # required on many Linux hosts
            "--disable-dev-shm-usage"
        ]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Browser ready at fragment.com")
    return _page

async def shutdown_browser():
    """Close everything to clear login/session data."""
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── COMMAND HANDLERS ────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    page = await init_browser()
    await page.click("button:has-text('Connect TON')")
    await page.click("button[aria-label='TON Connect QR']")
    link_el = await page.wait_for_selector("a[href^='tc://']", timeout=10000)
    link = await link_el.get_attribute("href")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
    ])
    await msg.answer(
        f"🔗 Open this in Tonkeeper to connect:\n\n`{link}`",
        parse_mode="Markdown",
        reply_markup=kb
    )

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

# ─── INLINE QUERY HANDLER ───────────────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    query = inline_q.query.strip()
    if not (query.isdigit() and 3 <= len(query) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = query
    full_number = f"+888{suffix}"

    page = await init_browser()
    try:
        await page.goto("https://fragment.com/my/numbers", wait_until="domcontentloaded")
        row = await page.wait_for_selector(
            f"xpath=//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']",
            timeout=7000
        )
        await row.click("button:has-text('Get Login Code')")
        code_el = await page.wait_for_selector("div.login-code", timeout=10000)
        code = (await code_el.text_content() or "").strip()
    except Exception as e:
        code = f"⚠️ Error: {e}"

    title = f"{full_number} → {code}"
    content = f"Login code for {full_number}: {code}"
    result = InlineQueryResultArticle(
        id=suffix,
        title=title,
        input_message_content=InputTextMessageContent(content)
    )
    await inline_q.answer(results=[result], cache_time=5)

# ─── BOT SETUP & RUN ────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started. Commands: /connect, /logout. Inline: type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
