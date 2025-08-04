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
from dotenv import load_dotenv

# Selenium imports
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ─── CONFIG & LOGGING ───────────────────────────────────────────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    logging.error("BOT_TOKEN is not set in .env")
    exit(1)

# ─── GLOBAL DRIVER STATE ─────────────────────────────────────────────────────────
_driver: webdriver.Chrome | None = None
_wait: WebDriverWait | None = None

def init_driver():
    global _driver, _wait
    if _driver:
        return _driver, _wait

    # ensure chromedriver is installed
    chromedriver_autoinstaller.install()

    chrome_opts = Options()
    chrome_opts.add_argument("--headless=new")
    chrome_opts.add_argument("--no-sandbox")
    chrome_opts.add_argument("--disable-dev-shm-usage")
    chrome_opts.add_experimental_option("prefs", {
        "profile.default_content_setting_values.clipboard": 1
    })

    service = ChromeService()
    _driver = webdriver.Chrome(service=service, options=chrome_opts)
    _driver.set_window_size(1200, 800)
    _wait = WebDriverWait(_driver, 20)
    return _driver, _wait

def shutdown_driver():
    global _driver, _wait
    if _driver:
        _driver.quit()
    _driver = None
    _wait = None
    logging.info("🔒 Browser closed, session cleared.")

# ─── /connect ─────────────────────────────────────────────────────────────────────
async def on_connect(msg: types.Message):
    driver, wait = init_driver()
    try:
        driver.get("https://fragment.com")

        # 1) Click “Connect TON”
        btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.ton-auth-link")))
        btn.click()

        # 2) Wait for TON-Connect modal
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#tc-widget-root")))

        # 3) Click the “Copy Link” button inside it
        copy_btn = wait.until(EC.element_to_be_clickable((
            By.CSS_SELECTOR,
            "#tc-widget-root button[data-clipboard-text]"
        )))
        link = copy_btn.get_attribute("data-clipboard-text")
        if not link:
            raise RuntimeError("Couldn’t extract the TON-Connect link")

        # 4) Send link + “Log out”
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔒 Log out", callback_data="logout")]])
        await msg.answer(f"🔗 TON-Connect link:\n`{link}`", parse_mode="Markdown", reply_markup=kb)

        # 5) Wait up to 60s for handshake (button disappears)
        try:
            wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, "button.ton-auth-link")), timeout=60)
            await msg.answer("✅ Connected successfully!", parse_mode="Markdown")
        except:
            logging.warning("Handshake timeout or already connected.")

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
    shutdown_driver()
    await destination.answer("🔒 You’ve been logged out. Use `/connect` to reconnect.", parse_mode="Markdown")

# ─── Inline Query ────────────────────────────────────────────────────────────────
async def on_inline_query(inline_q: InlineQuery):
    q = inline_q.query.strip()
    if not (q.isdigit() and 3 <= len(q) <= 7):
        return await inline_q.answer(results=[], cache_time=1)

    suffix = q
    full = f"+888{suffix}"
    code = "❌ Error"

    driver, wait = init_driver()
    try:
        driver.get("https://fragment.com/my/numbers")
        row = wait.until(EC.element_to_be_clickable((
            By.XPATH,
            f"//div[contains(text(), '{suffix}')]/ancestor::div[@role='row']//button[text()='Get Login Code']"
        )))
        row.click()
        el = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "div.login-code")))
        code = el.text.strip() or "❌ No code"
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

    dp.message.register(on_connect, Command(commands=["connect"]))
    dp.message.register(on_logout_cmd, Command(commands=["logout"]))
    dp.callback_query.register(on_logout_cb, lambda c: c.data == "logout")
    dp.inline_query.register(on_inline_query)

    logging.info("🤖 Bot started: /connect, /logout; inline → type digits.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
