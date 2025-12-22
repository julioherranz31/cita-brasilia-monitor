import os
import re
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

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


def check_once() -> bool:
    """Retorna True se encontrou vaga (e avisou). False caso contrário."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def on_dialog(d):
            try:
                d.accept()
            except Exception:
                pass

        page.on("dialog", on_dialog)
        page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=90_000)

        # cookies (se aparecer)
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

        # clica no link que leva ao citaconsular (robusto)
        page.locator("a[href*='citaconsular']").first.click(timeout=30_000)
        page.wait_for_timeout(1500)

        # ✅ não depende de nova aba: se abrir, pega; se não, segue na mesma
        cita = page
        try:
            # se uma nova aba abrir rapidamente, pegamos ela
            context.wait_for_event("page", timeout=5000)
            cita = context.pages[-1]
        except Exception:
            cita = page

        cita.on("dialog", on_dialog)
        cita.wait_for_load_state("domcontentloaded", timeout=90_000)

        # se estiver na tela do botão Continue / Continuar, clica
        try:
            cita.get_by_role("button", name=re.compile(r"Continue|Continuar", re.I)).click(timeout=30_000)
            cita.wait_for_timeout(1500)
        except Exception:
            pass

        # tenta aguardar #services (às vezes não muda a URL, mas o conteúdo carrega)
        try:
            cita.wait_for_url(re.compile(r"#services"), timeout=60_000)
        except Exception:
            pass

        cita.wait_for_timeout(1500)
        body = cita.locator("body").inner_text(timeout=10_000)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        # silencioso quando sem vagas
        if "No hay horas disponibles" in body:
            print(f"[{now}] Sem vagas")
            browser.close()
            return False

        # procurar “Hueco libre”
        slot = cita.locator(r"text=/\b\d{2}:\d{2}\b.*Hueco libre/").first
        if slot.count() > 0:
            slot_text = slot.inner_text(timeout=2000).strip()
            slot.click(timeout=5000, force=True)
            cita.wait_for_timeout(1500)

            shot = "vaga.png"
            cita.screenshot(path=shot, full_page=True)
            tg_send_photo(shot, f"✅ VAGA ENCONTRADA E CLICADA!\n{slot_text}\n{now}\nURL: {cita.url}")

            browser.close()
            return True

        # se chegou aqui, é um estado diferente (manda print para diagnóstico)
        shot = "estado.png"
        cita.screenshot(path=shot, full_page=True)
        tg_send_photo(shot, f"⚠️ Estado inesperado.\n{now}\nURL: {cita.url}")

        browser.close()
        return False


if __name__ == "__main__":
    # 🔁 tentativas contínuas por ~10 minutos (10 tentativas, 1 por minuto)
    for i in range(10):
        try:
            found = check_once()
            if found:
                break
        except Exception as e:
            print("Erro:", e)
        time.sleep(60)
