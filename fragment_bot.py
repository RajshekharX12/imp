# file: fragment_bot.py

import os
import asyncio
import logging
import aiohttp

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
    logging.error("❌ BOT_TOKEN is not set in .env")
    exit(1)

# URL of your Node.js TON-link service (see README)
TON_LINK_SERVICE = os.getenv("TON_LINK_SERVICE", "http://localhost:4000/api/ton-link")

# ─── GLOBAL BROWSER STATE (for inline queries) ─────────────────────────────────
_playwright = None
_context: BrowserContext = None
_page: Page = None

async def init_browser() -> Page:
    """
    Launch a headless Chromium once and keep it running,
    so inline queries can reuse the logged-in session.
    """
    global _playwright, _context, _page
    if _page:
        return _page

    _playwright = await async_playwright().start()
    _context = await _playwright.chromium.launch_persistent_context(
        user_data_dir="./playwright_data",
        headless=True,
        args=["--no-sandbox","--disable-dev-shm-usage"]
    )
    _page = await _context.new_page()
    return _page

async def shutdown_browser():
    """Closes the browser—used if you ever want to nuke the session."""
    global _playwright, _context, _page
    if _context:
        await _context.close()
    if _playwright:
        await _playwright.stop()
    _page = None
    _context = None
    _playwright = None

# ─── /connect ───────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    """
    1) Hit TON_LINK_SERVICE to get a fresh deep-link
    2) Send it with a “Log out” button
    """
    await msg.answer("🔗 Generating your TON-Connect link…")
    async with aiohttp.ClientSession() as session:
        try:
            resp = await session.post(TON_LINK_SERVICE, json={
                "allowedWallets": ["tonkeeper","tonhub","mytonwallet","telegram"]
            })
            resp.raise_for_status()
            data = await resp.json()
            link = data.get("connectUrl")
            if not link:
                raise ValueError("no connectUrl in response")

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [ InlineKeyboardButton("🔒 Log out", callback_data="logout") ]
            ])
            await msg.answer(
                f"✅ Here’s your TON-Connect link:\n\n`{link}`",
                parse_mode="Markdown",
                reply_markup=kb
            )
        except Exception as e:
            logging.exception(e)
            await msg.answer(f"❌ Failed to generate link:\n`{e}`")

# ─── /logout ────────────────────────────────────────────────────────────────────
async def on_logout_cmd(msg: types.Message):
    await do_logout(msg)

async def on_logout_cb(call: types.CallbackQuery):
    await call.answer()
    await do_logout(call.message)

async def do_logout(dest):
    # If you had a persistent Playwright session for /connect,
    # you could shut it down here. We only use playwright for inline,
    # so we leave it running.
    await dest.answer("🔒 Logged out. Run `/connect` again to start over.", parse_mode="Markdown")

# ─── inline query: fetch login code for +888<suffix> ─────────────────────────────
@dp.inline_query()
async def on_inline_query(inline_q: InlineQuery):
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full = f"+888{suffix}"
    code = "❌ Error"

    page = await init_browser()
    try:
        # navigate to your Numbers page
        await page.goto("https://fragment.com/my/numbers", wait_until="domcontentloaded")
        # find the row for this suffix
        row = await page.wait_for_selector(
            f"xpath=//div[contains(.,'{suffix}')]/ancestor::div[@role='row']",
            timeout=7000
        )
        # click “Get Login Code”
        await row.click("button:has-text('Get Login Code')")
        # scrape the code
        el = await page.wait_for_selector("div.login-code", timeout=10000)
        code = (await el.text_content() or "").strip() or "❌ No code"
    except Exception as e:
        logging.exception(e)
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

    dp.message.register(on_connect, Command("connect"))
    dp.message.register(on_logout_cmd, Command("logout"))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("Bot is up. Commands: /connect, /logout. Inline: type 3–7 digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
