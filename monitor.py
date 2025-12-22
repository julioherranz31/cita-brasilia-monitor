import os
import re
import time
from datetime import datetime
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

WIDGET_URL = "https://www.citaconsular.es/es/hosteds/widgetdefault/28cf6fbfe043643def303827bba87344a"
SERVICES_URL_REGEX = re.compile(r".*/#services$")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Se você rodar com FORCE_TEST_ALERT=1, ele manda alerta mesmo sem vaga.
FORCE_TEST_ALERT = os.getenv("FORCE_TEST_ALERT", "").strip() == "1"


def send_telegram(msg: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID não configurados.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=20)
    if r.status_code != 200:
        print("⚠️ Falha ao enviar Telegram:", r.status_code, r.text)
    else:
        print("📨 Telegram enviado com sucesso.")


def check_once():
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        def auto_accept_dialog(d):
            try:
                d.accept()
            except:
                pass

        page = context.new_page()
        page.on("dialog", auto_accept_dialog)

        print(f"[{now}] Abrindo widget: {WIDGET_URL}")
        page.goto(WIDGET_URL, timeout=60000, wait_until="domcontentloaded")

        # Clica Continue/Continuar (pode estar como botão)
        # Alguns casos: role=button name contém Continue / Continuar
        try:
            page.get_by_role("button", name=re.compile(r"continue|continuar", re.I)).click(timeout=30000)
        except PWTimeout:
            # fallback: tenta clicar pelo texto
            page.locator("text=Continue / Continuar").click(timeout=30000)

        # Espera ir para /#services
        try:
            page.wait_for_url(SERVICES_URL_REGEX, timeout=45000)
        except PWTimeout:
            # Às vezes muda sem atualizar a URL imediatamente; tenta detectar pelo conteúdo
            time.sleep(3)

        current = page.url
        print(f"[{now}] URL atual: {current}")

        # Confere se chegou na etapa certa
        on_services = current.endswith("/#services") or "#services" in current

        body = page.locator("body").inner_text(timeout=20000)

        # Critérios de "sem vaga"
        sem_vaga = (
            "No hay horas disponibles" in body
            or "Inténtelo de nuevo" in body
            or "No hay horas disponibles." in body
        )

        # Critérios de "tem vaga"
        tem_vaga = (
            re.search(r"Hueco\s+libre", body, re.I) is not None
            or re.search(r"\b\d{2}:\d{2}\b", body) is not None  # horários visíveis
        )

        browser.close()

        return {
            "now": now,
            "url": current,
            "on_services": on_services,
            "sem_vaga": sem_vaga,
            "tem_vaga": tem_vaga,
            "body_preview": body[:500],
        }


def main():
    result = check_once()

    now = result["now"]
    url = result["url"]

    # Modo teste (força mensagem)
    if FORCE_TEST_ALERT:
        send_telegram(f"🧪 TESTE OK [{now}]\nCheguei em: {url}\n(Alerta de teste)")
        return

    # Se nem chegou em services, avisa
    if not result["on_services"]:
        send_telegram(f"⚠️ Estado inesperado [{now}]\nNão cheguei em /#services.\nURL: {url}")
        return

    # Se tem vaga
    if result["tem_vaga"] and not result["sem_vaga"]:
        send_telegram(f"✅ VAGA POSSÍVEL! [{now}]\nURL: {url}\nVerifique agora no site!")
        return

    # Sem vaga (opcional: NÃO mandar telegram toda vez pra não spam)
    print(f"[{now}] Sem vagas. OK.")
    print("Preview:", result["body_preview"].replace("\n", " ")[:200])


if __name__ == "__main__":
    main()
