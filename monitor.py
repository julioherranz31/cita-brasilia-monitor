import os
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

URL_INICIAL = "https://www.exteriores.gob.es/Embajadas/brasilia/pt/Embajada/Paginas/CitaNacionalidadLMD.aspx"

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def tg_send_message(text: str):
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text},
        timeout=30,
    )

def tg_send_photo(photo_path: str, caption: str):
    with open(photo_path, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=60,
        )

def check_once():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        def on_dialog(d):
            try:
                d.accept()
            except Exception:
                pass

        page = context.new_page()
        page.on("dialog", on_dialog)
        page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=60_000)

        with context.expect_page() as newp:
            page.get_by_role("link", name="ESCOLHER DATA E HORÁRIO").click(timeout=30_000)

        cita = newp.value
        cita.on("dialog", on_dialog)
        cita.wait_for_load_state("domcontentloaded", timeout=60_000)

        cita.get_by_role(
            "button",
            name=re.compile(r"Continue\s*/\s*Continuar", re.I)
        ).click(timeout=30_000)

        cita.wait_for_url(re.compile(r".*/#services$"), timeout=60_000)
        cita.wait_for_timeout(1500)

        body = cita.locator("body").inner_text(timeout=10_000)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        if "No hay horas disponibles" in body:
            print(f"[{now}] Sem vagas")
            browser.close()
            return

        slot = cita.locator("text=/\\b\\d{2}:\\d{2}\\b.*Hueco libre/").first
        if slot.count() > 0:
            slot_text = slot.inner_text(timeout=2000).strip()
            slot.click(timeout=5000)
            cita.wait_for_timeout(1500)

            shot = "vaga.png"
            cita.screenshot(path=shot, full_page=True)

            tg_send_photo(
                shot,
                caption=f"✅ VAGA ENCONTRADA E CLICADA!\n{slot_text}\n{now}"
            )
        else:
            shot = "estado.png"
            cita.screenshot(path=shot, full_page=True)
            tg_send_photo(
                shot,
                caption=f"⚠️ Estado inesperado.\n{now}"
            )

        browser.close()

if __name__ == "__main__":
    check_once()
