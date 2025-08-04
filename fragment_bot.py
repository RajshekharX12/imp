# File: fragment_bot.py

import os
import asyncio
import logging
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    devices,
)

# ─── CONFIG & LOGGING ───────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logging.error("❌ BOT_TOKEN is not set in .env")
    exit(1)

# ─── GLOBAL BROWSER STATE ────────────────────────────────────────────────────────
_playwright = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """
    Launch or return a persistent headless Chromium context,
    emulating iPhone 13 so that Fragment.com shows its mobile UI.
    """
    global _playwright, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching Playwright in headless mobile (iPhone 13) mode…")
    _playwright = await async_playwright().start()

    # pick up the built-in iPhone 13 descriptor
    iphone = devices["iPhone 13"]

    # launch persistent context with mobile emulation + clipboard permission
    user_data = os.path.join(os.getcwd(), "playwright_user_data")
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir=user_data,
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        **iphone,
        permissions=["clipboard-read"],
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com (mobile view)")
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
    """
    /connect → 
      1) Click 'Connect TON'
      2) Wait for the TON-Connect dialog
      3) Tap the QR-icon button
      4) Extract the tc://… link
      5) Send link + “Log out” button
      6) Await handshake → “Connected successfully!”
    """
    page = await init_browser()

    # 1) Tap “Connect TON”
    await page.click("button:has-text('Connect TON')")

    # 2) Wait for the TON-Connect dialog to appear
    dialog = page.locator("div:has-text('Connect your TON wallet')")
    await dialog.wait_for(timeout=10_000)

    # 3) Tap the second button (the QR-grid icon)
    await dialog.locator("button").nth(1).click()

    # 4) Pull the deep-link off the “Copy Link” button
    copy_btn = await dialog.wait_for_selector("button:has-text('Copy Link')", timeout=10_000)
    link = await copy_btn.get_attribute("data-clipboard-text")
    if not link:
        return await msg.answer("⚠️ Couldn’t find the TON-Connect link. Please try again.")

    # 5) Send it with a logout inline button
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
    ])
    await msg.answer(
        f"🔗 Copy this link into Tonkeeper to connect:\n\n`{link}`",
        parse_mode="Markdown",
        reply_markup=kb
    )

    # 6) Wait up to 60s for the connect-button to detach (handshake complete)
    try:
        await page.wait_for_selector(
            "button:has-text('Connect TON')",
            state="detached",
            timeout=60_000
        )
        await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
    except asyncio.TimeoutError:
        logging.warning("Handshake timeout; maybe you’re already connected.")

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

# ─── Inline Query Handler ─────────────────────────────────────────────────────────
async def on_inline_query(inline_q: types.InlineQuery):
    """
    Inline '<suffix>' → fetch login code for +888<suffix>.
    """
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
            timeout=7_000
        )
        await row.click("button:has-text('Get Login Code')")
        el = await page.wait_for_selector("div.login-code", timeout=10_000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        code = f"⚠️ {e}"

    result = InlineQueryResultArticle(
        id=suffix,
        title=f"{full} → {code}",
        input_message_content=InputTextMessageContent(f"Login code for {full}: {code}")
    )
    await inline_q.answer(results=[result], cache_time=5)

# ─── Bot Setup & Run ─────────────────────────────────────────────────────────────
async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started: /connect, /logout; inline → type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
