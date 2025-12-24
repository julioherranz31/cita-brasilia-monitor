import os
import re
import time
from datetime import datetime, timezone
import requests
from playwright.sync_api import sync_playwright


def now_str():
    # horário Brasilia (aproximação via UTC-3)
    # (se quiser, posso ajustar com pytz, mas aqui evita dependência extra)
    utc = datetime.now(timezone.utc)
    br = utc.timestamp() - (3 * 3600)
    return datetime.fromtimestamp(br).strftime("%d/%m/%Y %H:%M:%S")


def tg_send_message(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=20)
    r.raise_for_status()


def tg_send_photo(token: str, chat_id: str, caption: str, path: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    with open(path, "rb") as f:
        r = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": f},
            timeout=60,
        )
    r.raise_for_status()


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    monitor_url = os.getenv("MONITOR_URL", "").strip()
    test_alert = os.getenv("TEST_ALERT", "0").strip()

    print(f"🟦 Monitor iniciado: {now_str()}")
    print(f"URL: {monitor_url[:80]}{'...' if len(monitor_url) > 80 else ''}")
    print(f"TEST_ALERT={test_alert}")

    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID vazio. Configure em Secrets.")

    if test_alert == "1":
        tg_send_message(token, chat_id, f"✅ Teste OK ({now_str()}) — Telegram configurado.")
        print("✅ Telegram sendMessage OK (teste).")

    if not monitor_url:
        raise RuntimeError("MONITOR_URL está vazio. Configure o secret MONITOR_URL.")

    # reduzir risco de bloqueio:
    # - headless
    # - user-agent comum
    # - pequena espera aleatória antes de acessar
    time.sleep(2)

    screenshot_path = "/tmp/cita.png"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="es-ES",
        )
        page = context.new_page()

        # tenta carregar com mais paciência
        page.goto(monitor_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)

        # espera o BODY ter conteúdo (evita print "branco")
        page.wait_for_selector("body", timeout=60000)

        # Tenta detectar texto esperado
        content = page.content()
        text = page.inner_text("body") if page.locator("body").count() else ""

        # salva screenshot sempre (útil pra depurar)
        page.screenshot(path=screenshot_path, full_page=True)

        browser.close()

    # Regras (ajustei pra ser claro):
    # - Se aparecer "No hay horas disponibles" => sem vagas.
    # - Se aparecer algo como "Elegir fecha/hora" ou botões/slots => possível vaga.
    sem_vagas = bool(re.search(r"No hay horas disponibles", text, re.IGNORECASE))
    pagina_carregou = len(text.strip()) > 30  # evita falso branco total

    if not pagina_carregou:
        msg = (
            f"⚠️ Página carregou vazia/branca ({now_str()})\n"
            f"URL: {monitor_url}\n"
            f"➡️ Pode ser bloqueio/captcha/instabilidade.\n"
            f"Vou continuar tentando no próximo ciclo."
        )
        tg_send_message(token, chat_id, msg)
        tg_send_photo(token, chat_id, "📸 Screenshot (página vazia)", screenshot_path)
        print("⚠️ Página aparentemente vazia. Aviso enviado.")
        return

    if sem_vagas:
        print(f"✅ Sem vagas ({now_str()}).")
        # não spam: só manda screenshot quando for teste
        if test_alert == "1":
            tg_send_photo(
                token,
                chat_id,
                f"📸 Screenshot do teste ({now_str()})\n{monitor_url}",
                screenshot_path,
            )
        return

    # Se NÃO achou a frase de sem-vagas, alerta como "mudança" / possível vaga
    msg = (
        f"🚨 POSSÍVEL MUDANÇA / VAGA ({now_str()})\n"
        f"Não apareceu a mensagem de 'No hay horas disponibles'.\n"
        f"Abra e confira agora:\n{monitor_url}"
    )
    tg_send_message(token, chat_id, msg)
    tg_send_photo(token, chat_id, "📸 Screenshot (possível vaga/mudança)", screenshot_path)
    print("🚨 Alerta enviado: possível vaga/mudança.")


if __name__ == "__main__":
    main()
