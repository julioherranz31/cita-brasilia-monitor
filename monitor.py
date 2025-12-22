import os
import re
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# Página do consulado (onde existe o link que leva ao citaconsular)
URL_INICIAL = "https://www.exteriores.gob.es/Embajadas/brasilia/pt/Embajada/Paginas/CitaNacionalidadLMD.aspx"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def tg_send_message(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram não configurado (secrets ausentes).")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=30)
    print("Telegram sendMessage:", r.text)


def tg_send_photo(photo_path: str, caption: str):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram não configurado (secrets ausentes).")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=60,
        )
    print("Telegram sendPhoto:", r.text)


def check_once():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_dialog(d):
            try:
                d.accept()
            except:
                pass

        page.on("dialog", on_dialog)
        page.goto(URL_INICIAL, timeout=90_000)

        # aceita cookies se aparecer
        try:
            page.locator("button:has-text('Aceitar'), button:has-text('Aceptar')").click(timeout=3000)
        except:
            pass

        # entra no citaconsular
        page.locator("a[href*='citaconsular']").first.click(timeout=30_000)

        # pega a nova aba
        context.wait_for_event("page", timeout=20_000)
        cita = context.pages[-1]
        cita.on("dialog", on_dialog)
        cita.wait_for_load_state("domcontentloaded")

        # ✅ PASSO QUE FALTAVA: clicar em CONTINUE / CONTINUAR
        cita.get_by_role(
            "button",
            name=re.compile("Continue|Continuar", re.I)
        ).click(timeout=30_000)

        # espera a página de serviços
        cita.wait_for_url(re.compile("#services"), timeout=60_000)
        cita.wait_for_timeout(2000)

        body = cita.locator("body").inner_text()
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        if "No hay horas disponibles" in body:
            print(f"[{now}] Sem vagas")
            browser.close()
            return

        # procura horário livre
        slot = cita.locator(r"text=/\d{2}:\d{2}.*Hueco libre/").first

        if slot.count() > 0:
            txt = slot.inner_text()
            slot.click(force=True)
            cita.wait_for_timeout(1500)

            shot = "vaga.png"
            cita.screenshot(path=shot, full_page=True)

            tg_send_photo(
                shot,
                f"✅ VAGA ENCONTRADA!\n{txt}\n{now}\n{cita.url}"
            )
        else:
            shot = "estado.png"
            cita.screenshot(path=shot, full_page=True)
            tg_send_photo(
                shot,
                f"⚠️ Página carregada mas sem horários visíveis\n{now}\n{cita.url}"
            )

        browser.close()


if __name__ == "__main__":
    check_once()
