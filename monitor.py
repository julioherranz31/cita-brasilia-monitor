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
        page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=90_000)

        # tenta aceitar cookies (se aparecer)
        for sel in ["button:has-text('Aceitar')", "button:has-text('Aceptar')", "button:has-text('Accept')"]:
            try:
                page.locator(sel).first.click(timeout=1500)
                break
            except Exception:
                pass

        # clica no link (sem depender de abrir nova aba)
        link = page.get_by_role("link", name=re.compile(r"ESCOLHER\s+DATA\s+E\s+HOR", re.I))
        link.click(timeout=30_000)

        # espera: ou abriu nova aba, ou navegou na mesma
        cita = None
        try:
            # se abrir nova aba, ela aparece aqui
            context.wait_for_event("page", timeout=15_000)
            # pega a última aba aberta
            cita = context.pages[-1]
        except Exception:
            # senão, usa a mesma aba
            cita = page

        cita.on("dialog", on_dialog)
        cita.wait_for_load_state("domcontentloaded", timeout=90_000)

        # se estiver no citaconsular e tiver botão Continue
        try:
            cita.get_by_role(
                "button",
                name=re.compile(r"Continue\s*/\s*Continuar", re.I)
            ).click(timeout=30_000)
        except Exception:
            pass

        # às vezes ele já vai direto para #services; em outras, precisa esperar
        try:
            cita.wait_for_url(re.compile(r".*/#services$"), timeout=90_000)
        except Exception:
            # se não chegou em #services, tenta forçar esperar algum conteúdo do widget
            cita.wait_for_timeout(2000)

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
