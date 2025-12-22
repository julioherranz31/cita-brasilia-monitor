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

        def on_dialog(d):
            try:
                d.accept()
            except Exception:
                pass

        page = context.new_page()
        page.on("dialog", on_dialog)
        page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=90_000)

        # tenta aceitar cookies (se aparecer)
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

        # ✅ CORREÇÃO: clicar pelo href que contém 'citaconsular' (não depende de texto)
        # isso evita quebrar quando mudam o nome do link.
        page.locator("a[href*='citaconsular']").first.click(timeout=30_000)
        page.wait_for_timeout(2000)

        # se abrir nova aba, captura; se não, usa a mesma
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
                name=re.compile(r"Continue\s*/\s*Continuar|Continue|Continuar", re.I),
            ).click(timeout=30_000)
        except Exception:
            pass

        # espera chegar em #services (quando o widget carrega)
        try:
            cita.wait_for_url(re.compile(r".*/#services$"), timeout=90_000)
        except Exception:
            # se não mudou a URL, ainda assim pode ter carregado
            pass

        cita.wait_for_timeout(1500)
        body = cita.locator("body").inner_text(timeout=10_000)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        # 🔕 modo silencioso: não manda mensagem quando não tem vaga
        if "No hay horas disponibles" in body:
            print(f"[{now}] Sem vagas")
            browser.close()
            return

        # ✅ procura e clica no primeiro horário disponível
        slot = cita.locator(r"text=/\b\d{2}:\d{2}\b.*Hueco libre/").first
        if slot.count() > 0:
            slot_text = slot.inner_text(timeout=2000).strip()
            slot.click(timeout=5000, force=True)
            cita.wait_for_timeout(1500)

            final_url = cita.url
            shot = "vaga.png"
            cita.screenshot(path=shot, full_page=True)

            tg_send_photo(
                shot,
                caption=f"✅ VAGA ENCONTRADA E CLICADA!\n{slot_text}\n{now}\nURL: {final_url}",
            )
        else:
            # caso inesperado: manda screenshot para você ver o que apareceu
            shot = "estado.png"
            cita.screenshot(path=shot, full_page=True)
            tg_send_photo(shot, f"⚠️ Estado inesperado.\n{now}\nURL: {cita.url}")

        browser.close()


if __name__ == "__main__":
    check_once()
