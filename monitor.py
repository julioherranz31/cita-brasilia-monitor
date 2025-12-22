import os
import re
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

URL_INICIAL = "https://www.exteriores.gob.es/Embajadas/brasilia/es/ServiciosConsulares/Paginas/index.aspx"

BOT_TOKEN = os.getenv("8246994744:AAEqO4B0nm0e8ryd1D1Uxq43B7StpbxfBKQ")
CHAT_ID = os.getenv("6651786553")


def tg_send_message(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram não configurado.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)
    print("Telegram sendMessage:", r.text)


def tg_send_photo(path, caption):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram não configurado.")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=30,
        )
    print("Telegram sendPhoto:", r.text)


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
        page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=90_000)

        # tenta aceitar cookies
        for sel in [
            "button:has-text('Aceitar')",
            "button:has-text('Aceptar')",
            "button:has-text('Accept')",
        ]:
            try:
                page.locator(sel).first.click(timeout=1500)
                break
            except Exception:
                pass

        # clica no link de agendamento
        page.get_by_role(
            "link",
            name=re.compile(r"ESCOLHER\s+DATA\s+E\s+HOR", re.I),
        ).click(timeout=30_000)

        # nova aba ou mesma aba
        try:
            context.wait_for_event("page", timeout=15_000)
            cita = context.pages[-1]
        except Exception:
            cita = page

        cita.on("dialog", on_dialog)
        cita.wait_for_load_state("domcontentloaded", timeout=90_000)

        # botão continuar (se existir)
        try:
            cita.get_by_role(
                "button",
                name=re.compile(r"Continue|Continuar", re.I),
            ).click(timeout=20_000)
        except Exception:
            pass

        # espera serviços
        try:
            cita.wait_for_url(re.compile(r".*/#services$"), timeout=90_000)
        except Exception:
            pass

        time.sleep(2)
        body = cita.locator("body").inner_text(timeout=10_000)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        if "No hay horas disponibles" in body:
            print(f"[{now}] Sem vagas")
            browser.close()
            return

        slot = cita.locator("text=/\\b\\d{2}:\\d{2}\\b.*Hueco libre/").first
        if slot.count() > 0:
            slot_text = slot.inner_text(timeout=2000).strip()
            slot.click(timeout=5000, force=True)
            time.sleep(2)

            final_url = cita.url
            shot = "vaga.png"
            cita.screenshot(path=shot, full_page=True)

            tg_send_photo(
                shot,
                caption=(
                    "✅ VAGA ENCONTRADA E CLICADA!\n"
                    f"{slot_text}\n"
                    f"{now}\n"
                    f"{final_url}"
                ),
            )
        else:
            shot = "estado.png"
            cita.screenshot(path=shot, full_page=True)
            tg_send_photo(shot, f"⚠️ Estado inesperado\n{now}")

        browser.close()


if __name__ == "__main__":
    check_once()
