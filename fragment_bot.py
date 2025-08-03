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
_playwright = None        # Playwright driver handle
_context: BrowserContext = None
_page: Page = None        # Main page instance

async def init_browser() -> Page:
    """Launch or reuse a persistent Playwright Chromium context."""
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright…")
    _playwright = await async_playwright().start()
    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=False,            # show browser so you can interact
        args=["--start-maximized"]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com")
    return _page

async def shutdown_browser():
    """Close context & Playwright to clear session (logout)."""
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── HANDLER: /connect ────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    """
    /connect → 
      1) Go to fragment.com 
      2) Click the big 'Connect TON' button 
      3) Click the QR‐icon to reveal the Copy Link button 
      4) Grab the tc://… link from Copy Link's data‐clipboard‐text 
      5) Send it + a Log out button 
      6) Wait for the TON button to disappear → 'Connected successfully!'
    """
    page = await init_browser()

    # 1) Click "Connect TON"
    await page.click("button:has-text('Connect TON')")

    # 2) Click the little QR‐grid icon
    await page.click("button[aria-label='TON Connect QR']")

    # 3) Grab the tc://… URL
    copy_btn = await page.wait_for_selector("button:has-text('Copy Link')", timeout=10000)
    link = await copy_btn.get_attribute("data-clipboard-text")
    if not link:
        return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

    # 4) Reply with the link + a Log out button
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
    ])
    await msg.answer(
        f"🔗 Copy this link into Tonkeeper to connect:\n\n`{link}`",
        parse_mode="Markdown",
        reply_markup=kb
    )

    # 5) Wait up to 60s for the Connect TON button to vanish
    try:
        await page.wait_for_selector("button:has-text('Connect TON')",
                                     state="detached",
                                     timeout=60000)
        await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
    except:
        logging.warning("Timeout waiting for handshake to complete.")

# ─── HANDLER: /logout ─────────────────────────────────────────────────────────────
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

# ─── HANDLER: INLINE QUERY ────────────────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    """
    Inline query '1234567' → 
      fetch login code for +8881234567 and return as tappable result.
    """
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full = f"+888{suffix}"
    page = await init_browser()
    code = "⚠️ Error"
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

# ─── BOT SETUP & START ───────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, Text(equals="logout"))
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot running: /connect, /logout; inline → type digits")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
