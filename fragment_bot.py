# File: fragment_bot.py

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
_playwright = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """Launch or reuse a persistent headless Playwright Chromium context."""
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright in headless mode…")
    _playwright = await async_playwright().start()
    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com")
    return _page

async def shutdown_browser():
    """Close context & Playwright to clear session."""
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── /connect HANDLER ────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    """
    /connect →
      1) Click “Connect TON”
      2) Wait for the TON-Connect modal
      3) Click the QR-grid icon (2nd <button> in modal)
      4) Copy the tc://… link
      5) Send link + Logout button
      6) Wait for handshake → “Connected successfully!”
    """
    page = await init_browser()

    # 1) Click “Connect TON”
    await page.click("button:has-text('Connect TON')")

    # 2) Wait for the modal container to appear
    modal = page.locator("div[data-tc-modal='true'][data-tc-wallets-modal-container='true']")
    await modal.wait_for(timeout=10000)

    # 3) Click its second button (the QR-grid icon)
    await modal.locator("button").nth(1).click()

    # 4) Grab the deep-link from the “Copy Link” button inside that modal
    copy_btn = modal.locator("button:has-text('Copy Link')")
    await copy_btn.wait_for(timeout=10000)
    link = await copy_btn.get_attribute("data-clipboard-text")
    if not link:
        return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

    # 5) Send link + inline “Log out” button
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
    ])
    await msg.answer(
        f"🔗 Copy this link into Tonkeeper to connect:\n\n`{link}`",
        parse_mode="Markdown",
        reply_markup=kb
    )

    # 6) Wait up to 60s for the “Connect TON” button to disappear (handshake done)
    try:
        await page.wait_for_selector(
            "button:has-text('Connect TON')",
            state="detached",
            timeout=60000
        )
        await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
    except asyncio.TimeoutError:
        logging.warning("Handshake timeout; you may have already connected.")

# ─── /logout HANDLER ─────────────────────────────────────────────────────────────
async def on_logout_cmd(msg: types.Message):
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    await call.answer()
    await do_logout(call.message)

async def do_logout(destination):
    """Clear browser session and notify user."""
    await shutdown_browser()
    await destination.answer(
        "🔒 You’ve been logged out. Use `/connect` to reconnect.",
        parse_mode="Markdown"
    )

# ─── INLINE QUERY HANDLER ────────────────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    """
    Inline '<suffix>' → fetch login code for +888<suffix>.
    """
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full_number = f"+888{suffix}"
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
        title=f"{full_number} → {code}",
        input_message_content=InputTextMessageContent(f"Login code for {full_number}: {code}")
    )
    await inline_q.answer(results=[result], cache_time=5)

# ─── BOT SETUP & RUN ─────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started. Use /connect, /logout; inline → type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


