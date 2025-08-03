# File: fragment_bot.py

import os
import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, Text
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from playwright.async_api import async_playwright, BrowserContext, Page
from dotenv import load_dotenv

# ─── CONFIGURE & LOGGING ─────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ─── GLOBAL BROWSER STATE ────────────────────────────────────────────────────────
_playwright = None        # Playwright driver
_context: BrowserContext = None
_page: Page = None        # Main page handle

async def init_browser() -> Page:
    """Launch or reuse a persistent Playwright Chromium context and return the main page."""
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Starting Playwright…")
    _playwright = await async_playwright().start()
    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=False,            # show browser so you can scan QR if needed
        args=["--start-maximized"]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Browser ready at fragment.com")
    return _page

async def shutdown_browser():
    """Close browser context & Playwright driver to clear session."""
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── HANDLERS ───────────────────────────────────────────────────────────────────

async def on_connect(msg: types.Message):
    """Handle /connect: open Fragment, click Connect TON, grab only the Copy Link."""
    page = await init_browser()

    # 1) Open the TON-Connect modal
    await page.click("button:has-text('Connect TON')")

    # 2) Reveal the Copy Link button
    await page.click("button[aria-label='TON Connect QR']")

    # 3) Grab the tc://… link from the Copy Link button's data-clipboard-text
    copy_btn = await page.wait_for_selector("button:has-text('Copy Link')", timeout=10000)
    link = await copy_btn.get_attribute("data-clipboard-text")

    if not link:
        return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

    # 4) Send it with a Log out button
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
    ])
    await msg.answer(
        f"🔗 Copy this link into Tonkeeper to connect:\n\n`{link}`",
        parse_mode="Markdown",
        reply_markup=kb
    )

    # 5) Wait up to 60s for the Connect TON button to vanish → handshake done
    try:
        await page.wait_for_selector("button:has-text('Connect TON')", state="detached", timeout=60000)
        await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
    except:
        logging.warning("Timed out waiting for handshake to finish.")

async def on_logout_cmd(msg: types.Message):
    """Handle /logout command in DM."""
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    """Handle Logout button presses."""
    await call.answer()
    await do_logout(call.message)

async def do_logout(destination):
    """Perform logout: clear browser session and notify user."""
    await shutdown_browser()
    await destination.answer(
        "🔒 You’ve been logged out. Use `/connect` to reconnect.",
        parse_mode="Markdown"
    )

async def on_inline_query(inline_q: InlineQuery):
    """Handle inline queries: `<suffix>` → fetch login code for +888<suffix>."""
    query = inline_q.query.strip()
    if not (query.isdigit() and 3 <= len(query) <= 7):
        # ignore non-numeric or wrong-length queries
        return await inline_q.answer(results=[], cache_time=1)

    suffix = query
    full_number = f"+888{suffix}"

    page = await init_browser()
    code: str
    try:
        # navigate to My Numbers
        await page.goto("https://fragment.com/my/numbers", wait_until="domcontentloaded")
        # find the row and click Get Login Code
        row = await page.wait_for_selector(
            f"xpath=//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']",
            timeout=7000
        )
        await row.click("button:has-text('Get Login Code')")
        # read the code
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
    dp.callback_query.register(on_logout_cb, Text(equals="logout"))
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started. Commands: /connect, /logout. Inline: type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
