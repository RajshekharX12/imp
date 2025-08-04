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
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from dotenv import load_dotenv

# ─── CONFIG & LOGGING ───────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logging.error("🚨 BOT_TOKEN not set in .env")
    exit(1)

# ─── GLOBAL STATE ────────────────────────────────────────────────────────────────
_playwright = None      # type: async_playwright.Playwright
_browser: Browser = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """
    Launch (once) a headless iPhone 13 context and page.
    Returns the same Page until shutdown.
    """
    global _playwright, _browser, _context, _page
    if _page:
        return _page

    logging.info("🚀 Launching headless iPhone 13…")
    _playwright = await async_playwright().start()

    # pull the built-in iPhone 13 descriptor
    iphone = _playwright.devices["iPhone 13"]

    # launch a persistent Chromium (so we keep cookies until /logout)
    _browser = await _playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    _context = await _browser.new_context(
        **iphone,
        permissions=["clipboard-read"]
    )
    _page = await _context.new_page()
    await _page.goto("https://fragment.com", wait_until="domcontentloaded")
    logging.info("✅ Navigated to fragment.com (mobile view)")
    return _page

async def shutdown_browser():
    """Closes page, context & browser, wiping session."""
    global _playwright, _browser, _context, _page
    if _page:
        await _page.close()
    if _context:
        await _context.close()
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _browser = None
    _playwright = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    page = await init_browser()
    await msg.answer("🔗 Opening Fragment and popping up TON-Connect…")

    try:
        # 1) Click the VISIBLE "Connect TON" button
        await page.click("button:has-text('Connect TON'):visible", timeout=10000)

        # 2) Wait for the modal root
        await page.wait_for_selector("#tc-widget-root", state="visible", timeout=10000)

        # 3) Click the "Copy Link" button in the QR modal
        await page.click("#tc-widget-root button:has-text('Copy Link')", timeout=5000)

        # 4) Wait for the "Link Copied" confirmation
        await page.wait_for_selector("text=Link Copied", timeout=5000)

        # 5) Read the link from clipboard
        link = await page.evaluate("() => navigator.clipboard.readText()")
        if not link:
            raise RuntimeError("Clipboard was empty")

        # 6) Send the deep-link with a Logout button
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton("🔒 Log out", callback_data="logout")]
            ]
        )
        await msg.answer(
            f"🔗 TON-Connect link:\n\n`{link}`",
            parse_mode="Markdown",
            reply_markup=kb
        )

        # 7) Wait up to 60s for the modal to close (handshake)
        try:
            await page.wait_for_selector("#tc-widget-root", state="detached", timeout=60000)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except asyncio.TimeoutError:
            logging.warning("⌛ Handshake timeout – maybe already connected.")
    except Exception as e:
        logging.exception(e)
        await msg.answer(f"⚠️ Error during /connect:\n```\n{e}\n```")

# ─── /logout ─────────────────────────────────────────────────────────────────────
async def do_logout(destination):
    await shutdown_browser()
    await destination.answer(
        "🔒 You’ve been logged out. Use `/connect` to reconnect.",
        parse_mode="Markdown"
    )

async def on_logout_cmd(msg: types.Message):
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    await call.answer()     # dismiss the spinning loader
    await do_logout(call.message)

# ─── Inline Query (login code) ───────────────────────────────────────────────────
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
        # find the row for our suffix and click "Get Login Code"
        row = await page.wait_for_selector(
            f"xpath=//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']",
            timeout=7000
        )
        await row.click("button:has-text('Get Login Code')")
        el = await page.wait_for_selector("div.login-code", timeout=10000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        logging.error(f"Inline query failed: {e}")
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

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started — /connect, /logout; inline → send digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
