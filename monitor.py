import os
import re
import time
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

URL_INICIAL = "https://www.exteriores.gob.es/Embajadas/brasilia/pt/Embajada/Paginas/CitaNacionalidadLMD.aspx"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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

def check_once(debug_send_estado=False) -> bool:
    """True = achou vaga; False = não achou/sem vagas/estado."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        def on_dialog(d):
            try: d.accept()
            except: pass

        page.on("dialog", on_dialog)
        page.goto(URL_INICIAL, wait_until="domcontentloaded", timeout=90_000)

        # cookies (se aparecer)
        for sel in ["button:has-text('Aceitar')", "button:has-text('Aceptar')", "button:has-text('Accept')"]:
            try:
                page.locator(sel).first.click(timeout=1500)
                break
            except:
                pass

        # entrar no citaconsular (não depende de texto)
        page.locator("a[href*='citaconsular']").first.click(timeout=30_000)
        page.wait_for_timeout(1500)

        # nova aba OU mesma aba (não falha)
        cita = page
        try:
            context.wait_for_event("page", timeout=5000)
            cita = context.pages[-1]
        except:
            cita = page

        cita.on("dialog", on_dialog)
        cita.wait_for_load_state("domcontentloaded", timeout=90_000)

        # --- PASSO CRÍTICO: clicar no Continue / Continuar de forma mais forte ---
        # tenta por "role button", e se não achar, tenta por texto
        clicked = False
        for _ in range(3):
            try:
                cita.get_by_role("button", name=re.compile(r"Continue|Continuar", re.I)).click(timeout=10_000)
                clicked = True
                break
            except:
                try:
                    cita.locator("text=Continue / Continuar").click(timeout=10_000)
                    clicked = True
                    break
                except:
                    cita.wait_for_timeout(1000)

        # Depois do clique, aguarda #services
        base_url = cita.url.split("#")[0]
        try:
            cita.wait_for_url(re.compile(r"#services"), timeout=25_000)
        except:
            # se não entrou no #services, força o hash APÓS a base carregar (isso evita o erro de ir direto)
            try:
                cita.goto(base_url + "#services", wait_until="domcontentloaded", timeout=60_000)
            except:
                pass

        cita.wait_for_timeout(2000)
        body = cita.locator("body").inner_text(timeout=10_000)
        now = datetime.now().strftime("%d/%m/%Y %H:%M")

        # sem vagas (modo silencioso)
        if "No hay horas disponibles" in body:
            print(f"[{now}] Sem vagas")
            browser.close()
            return False

        # achou vaga
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

        # estado inesperado (mandar só se debug)
        if debug_send_estado:
            shot = "estado.png"
            cita.screenshot(path=shot, full_page=True)
            tg_send_photo(shot, f"⚠️ Estado inesperado.\n{now}\nURL: {cita.url}")

        browser.close()
        return False


if __name__ == "__main__":
    # 🔁 tentativas contínuas por ~10 minutos (10 tentativas, 1 por minuto)
    # IMPORTANTÍSSIMO: NÃO spammar Telegram com "estado inesperado" a cada tentativa
    for i in range(10):
        try:
            found = check_once(debug_send_estado=(i == 0))  # só manda estado na 1ª tentativa
            if found:
                break
        except Exception as e:
            print("Erro:", e)
        time.sleep(60)
