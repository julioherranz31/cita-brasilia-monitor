import os
import re
import time
import random
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# URL do widget (base). Checagem real acontece em /#services
WIDGET_URL = "https://www.citaconsular.es/es/hosteds/widgetdefault/28cf6fbfe043643def303827bba87344a/"
SERVICES_URL_REGEX = re.compile(r".*/#services$")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Envia alerta de teste quando FORCE_TEST_ALERT=1 (via workflow_dispatch input)
FORCE_TEST_ALERT = os.getenv("FORCE_TEST_ALERT", "0") == "1"


def now_br() -> str:
    br_tz = timezone(timedelta(hours=-3))
    return datetime.now(br_tz).strftime("%d/%m/%Y %H:%M:%S")


def tg_send_message(text: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Faltando TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID (GitHub Secrets).")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=30)
    # Se falhar, queremos ver no log
    r.raise_for_status()


def tg_send_photo(photo_path: str, caption: str) -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("Faltando TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID (GitHub Secrets).")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    with open(photo_path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption},
            files={"photo": f},
            timeout=60,
        )
    r.raise_for_status()


def check_once() -> dict:
    """
    Retorna um dict com:
      - ok_services: chegou no /#services?
      - sem_vaga: detectou “no hay horas...”
      - tem_vaga: detectou sinais fortes de vaga
      - url: url atual
      - preview: trecho do body (para log)
      - screenshot: caminho de screenshot (quando necessário)
    """
    # 🛡️ jitter: evita padrão de acesso sempre no mesmo segundo
    time.sleep(random.uniform(2.5, 9.0))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        # 🛡️ bloqueia peso desnecessário
        def block_non_essential(route):
            if route.request.resource_type in ("image", "media", "font"):
                return route.abort()
            return route.continue_()

        page.route("**/*", block_non_essential)

        # aceita dialogs (se aparecer)
        page.on("dialog", lambda d: d.accept())

        page.goto(WIDGET_URL, wait_until="domcontentloaded", timeout=60_000)

        # Clicar Continue/Continuar (se essa tela aparecer)
        try:
            page.get_by_role("button", name=re.compile(r"continue|continuar", re.I)).click(timeout=25_000)
        except PWTimeout:
            # Se não tem o botão, pode já estar direto no fluxo
            pass

        # Esperar /#services (página correta)
        try:
            page.wait_for_url(SERVICES_URL_REGEX, timeout=45_000)
        except PWTimeout:
            # tenta forçar hash depois de base carregar (evita erro de ir direto “a frio”)
            base = page.url.split("#")[0]
            try:
                page.goto(base + "#services", wait_until="domcontentloaded", timeout=45_000)
            except Exception:
                pass

        time.sleep(2.0)
        url = page.url
        ok_services = ("#services" in url)

        body = page.locator("body").inner_text(timeout=20_000)
        preview = body[:500]

        # “Sem vaga”
        sem_vaga = (
            "No hay horas disponibles" in body
            or "Inténtelo de nuevo" in body
            or "No hay horas disponibles." in body
        )

        # “Tem vaga” (sinais fortes)
        tem_hueco = re.search(r"Hueco\s+libre", body, re.I) is not None
        tem_horario = re.search(r"\b\d{2}:\d{2}\b", body) is not None
        tem_vaga = tem_hueco or (tem_horario and not sem_vaga)

        screenshot_path = ""
        # Só tira screenshot quando for teste, vaga, ou estado inesperado.
        if FORCE_TEST_ALERT or tem_vaga or (not ok_services):
            screenshot_path = "status.png"
            page.screenshot(path=screenshot_path, full_page=True)

        context.close()
        browser.close()

        return {
            "ok_services": ok_services,
            "sem_vaga": sem_vaga,
            "tem_vaga": tem_vaga,
            "url": url,
            "preview": preview,
            "screenshot": screenshot_path,
        }


def main():
    t = now_br()

    # ✅ teste forçado (sempre manda mensagem + imagem)
    if FORCE_TEST_ALERT:
        res = check_once()
        msg = (
            f"🧪 TESTE OK — Monitor Cita Brasília\n\n"
            f"🕒 Hora BR: {t}\n"
            f"📍 Cheguei em #services? {'SIM' if res['ok_services'] else 'NÃO'}\n"
            f"🔗 URL: {res['url']}"
        )
        tg_send_message(msg)
        if res["screenshot"]:
            tg_send_photo(res["screenshot"], f"📸 Screenshot do teste\n🕒 {t}\n🔗 {res['url']}")
        return

    # ✅ execução normal
    res = check_once()

    # Se não chegou na página certa, avisa (isso ajuda a detectar bloqueio/layout novo)
    if not res["ok_services"]:
        tg_send_message(
            "⚠️ Monitor Cita Brasília — estado inesperado\n\n"
            f"🕒 Hora BR: {t}\n"
            "Não consegui chegar na etapa de serviços (#services).\n"
            f"🔗 URL: {res['url']}\n"
            "➡️ Dica: abra o link no navegador e veja se apareceu captcha/popup diferente."
        )
        if res["screenshot"]:
            tg_send_photo(res["screenshot"], f"📸 Estado inesperado\n🕒 {t}\n🔗 {res['url']}")
        return

    # Se detectou vaga
    if res["tem_vaga"] and not res["sem_vaga"]:
        tg_send_message(
            "✅ POSSÍVEL VAGA — Cita Brasília\n\n"
            f"🕒 Hora BR: {t}\n"
            "Detectei sinais de horários disponíveis.\n"
            f"🔗 Abra agora: {res['url']}\n"
            "➡️ Se aparecer ‘Hueco libre’, finalize o agendamento rapidamente."
        )
        if res["screenshot"]:
            tg_send_photo(res["screenshot"], f"📸 Evidência (tela)\n🕒 {t}\n🔗 {res['url']}")
        return

    # Sem vaga: silencioso (apenas log)
    print(f"[{t}] Sem vagas. OK.")
    print("Preview:", res["preview"].replace("\n", " ")[:200])


if __name__ == "__main__":
    main()
