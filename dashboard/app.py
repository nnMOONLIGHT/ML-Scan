import os
from datetime import time
from urllib.parse import urlparse

import requests
import streamlit as st

API = os.getenv("TRAYEYE_API_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_TOKEN = os.getenv("TRAYEYE_ADMIN_TOKEN", "").strip()
st.set_page_config(page_title="TrayEye · Контроль пищевых отходов", page_icon="📷", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
:root { color-scheme: light; }
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap");
html, body, [class*="css"], button, input, textarea { font-family: "Inter", sans-serif !important; }
.stApp, [data-testid="stAppViewContainer"] { background: #FFFFFF; color: #1452C5; }
[data-testid="stHeader"] { background: #FFFFFF; }
[data-testid="stSidebar"] { background: #008E03; border-right: 1px solid #21483b; }
[data-testid="stSidebar"] * { color: #f4faf6 !important; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { background: transparent; border-radius: 8px; padding: .35rem .5rem; }
h1,h2,h3,h4,p,label,span,div { }
h1 { color: #1452C5 !important; font-weight: 750 !important; letter-spacing: -.035em; }
h2,h3,h4 { color: #1452C5 !important; font-weight: 700 !important; }
p, label, .stMarkdown, [data-testid="stCaptionContainer"] { color: #1452C5; }
[data-testid="stMetric"] { background: #fff; border: 1px solid #dce7e0; border-radius: 14px; padding: 18px 20px; box-shadow: 0 2px 8px rgba(20,47,39,.035); }
[data-testid="stMetricLabel"] { color: #1452C5 !important; }
[data-testid="stMetricValue"] { color: #1452C5 !important; }
div.stButton > button, div.stFormSubmitButton > button { background: #FFFFFF; color: #1452C5; border: 1px solid #008E03; border-radius: 9px; font-weight: 650; min-height: 2.6rem; }
div.stButton > button:hover, div.stFormSubmitButton > button:hover { background: #008E03; color: #FFFFFF; border-color: #10583b; }
div[data-baseweb="select"] > div, div[data-baseweb="input"] > div, textarea { background: #fff !important; border-color: #cbd9d1 !important; }
[data-testid="stDataFrame"], [data-testid="stExpander"] { background: #fff; border: 1px solid #dce7e0; border-radius: 12px; }
[data-testid="stFileUploader"] { background: #fff; border: 1px dashed #a9c4b4; border-radius: 12px; padding: 12px; }
.trayeye-eyebrow { color:#17734e; font-size:.78rem; font-weight:800; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.35rem; }
.trayeye-subtitle { color:#607268; font-size:1rem; margin-top:-.65rem; margin-bottom:1.3rem; }
.trayeye-panel { background:#fff; border:1px solid #dce7e0; border-radius:14px; padding:18px 20px; margin-bottom:12px; }
.trayeye-pill { display:inline-block; background:#e0f2e8; color:#176342; border-radius:999px; padding:5px 10px; font-size:.78rem; font-weight:700; }
</style>
""", unsafe_allow_html=True)


def api(method, path, *, show_error=True, **kwargs):
    try:
        headers = dict(kwargs.pop("headers", {}) or {})
        if ADMIN_TOKEN:
            headers["X-Admin-Token"] = ADMIN_TOKEN
        response = requests.request(method, f"{API}{path}", timeout=12, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        if show_error:
            st.error(f"Не удалось связаться с сервером API. Возможно, сервис просыпается после простоя или завершился с ошибкой. Адрес: {API}. Подробности: {exc}")
        return None


def page_header(eyebrow, title, subtitle):
    st.markdown(f'<div class="trayeye-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<div class="trayeye-subtitle">{subtitle}</div>', unsafe_allow_html=True)


st.sidebar.markdown("# TrayEye")
st.sidebar.caption("Умный контроль пищевых отходов")
st.sidebar.markdown("---")
page = st.sidebar.radio("НАВИГАЦИЯ", ["Обзор", "Камера и распознавание", "Меню", "Проверка событий", "Администратор системы", "Настройки"], label_visibility="visible")
st.sidebar.markdown("---")
st.sidebar.markdown('<span class="trayeye-pill">ДЕМО-ПЛАТФОРМА</span>', unsafe_allow_html=True)
st.sidebar.caption("Результаты распознавания требуют проверки человеком.")
if not ADMIN_TOKEN:
    st.sidebar.warning("TRAYEYE_ADMIN_TOKEN не задан: включите токен для защищённого доступа.")

if page == "Обзор":
    page_header("Мониторинг столовой", "Обзор", "Сводка по меню, проверкам и состоянию системы.")
    health = api("GET", "/health", show_error=False)
    schedule = api("GET", "/api/schedule", show_error=False)
    menu = api("GET", "/api/menu", show_error=False)
    events_response = api("GET", "/api/events", show_error=False)
    events = (events_response or {}).get("items", []) if isinstance(events_response, dict) else (events_response or [])
    connected = health is not None
    if connected:
        st.success("API доступен")
    else:
        st.warning(f"API пока недоступен ({API}). Данные не загрузились. Проверьте сервис trayeye-api в Render → Logs.")
    a, b, c, d = st.columns(4)
    a.metric("События проверки", len(events or []))
    b.metric("Блюда в меню", len(menu or []))
    c.metric("Приём пищи", (schedule or {}).get("current_meal", "—"))
    d.metric("Состояние API", "В сети" if connected else "Нет связи")
    st.markdown("### Последние события")
    if events:
        st.dataframe(events[:8], use_container_width=True, hide_index=True)
    else:
        st.info("Пока нет событий для отображения. Когда API заработает, новые проверки появятся здесь.")
    st.markdown("### Быстрые действия")
    left, right = st.columns(2)
    with left:
        st.markdown('<div class="trayeye-panel"><h4>📷 Камера и распознавание</h4><p>Загрузите фотографию подноса и отправьте её на анализ.</p></div>', unsafe_allow_html=True)
        if st.button("Открыть распознавание", use_container_width=True):
            st.session_state["trayeye_page"] = "Камера и распознавание"
            st.rerun()
    with right:
        st.markdown('<div class="trayeye-panel"><h4>🥗 Меню столовой</h4><p>Управляйте блюдами, которые подаются на завтрак и обед.</p></div>', unsafe_allow_html=True)
        if st.button("Открыть меню", use_container_width=True):
            st.session_state["trayeye_page"] = "Меню"
            st.rerun()
    st.caption("Важно: обученные веса модели не включены в репозиторий. Пока модель не подключена, система не должна считаться автоматическим распознавателем.")

elif page == "Камера и распознавание":
    page_header("Компьютерное зрение", "Камера и анализ подноса", "Загрузите изображение для отправки в сервис распознавания.")
    st.info("Модель распознавания должна быть обучена и подключена отдельно. Если весов модели нет, результат будет помечен как требующий проверки.")
    uploaded = st.file_uploader("Выберите фотографию подноса", type=["jpg", "jpeg", "png", "webp"])
    if uploaded:
        col1, col2 = st.columns([1.25, 1])
        with col1:
            st.image(uploaded, caption="Изображение для проверки", use_container_width=True)
        with col2:
            sched = api("GET", "/api/schedule", show_error=False) or {}
            st.markdown('<div class="trayeye-panel">', unsafe_allow_html=True)
            st.markdown("#### Детали проверки")
            st.write("Текущий приём пищи:", sched.get("current_meal", "Не определён"))
            st.write("Файл:", uploaded.name)
            st.write("Размер:", f"{uploaded.size / 1024:.0f} КБ")
            if st.button("Отправить на анализ", type="primary", use_container_width=True):
                result = api("POST", "/api/infer", files={"file": (uploaded.name, uploaded.getvalue(), uploaded.type)})
                if result:
                    inference = result.get("inference", {})
                    plate_status = inference.get("plate_status", "unknown")
                    if plate_status == "empty_detected":
                        st.info("Модель обнаружила пустую тарелку. Подтвердите результат.")
                    elif plate_status == "food_detected":
                        st.success("Модель обнаружила пищу. Подтвердите результат.")
                    else:
                        st.warning("Состояние тарелки не определено. Отсутствие детекций не означает, что тарелка пустая.")
                    st.warning(inference.get("message", "Результат требует ручной проверки."))
                    st.json(result.get("event", result))
                    st.caption("Если сервер создал событие, оно появится в очереди проверки.")
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.markdown('<div class="trayeye-panel"><h4>Как это работает</h4><p>1. Выберите фото подноса.</p><p>2. Отправьте файл на API.</p><p>3. Проверьте результат в очереди событий.</p></div>', unsafe_allow_html=True)
        st.caption("Потоковая камера в реальном времени пока не подключена; сейчас доступна загрузка снимка.")

elif page == "Меню":
    page_header("Питание", "Меню столовой", "Список блюд для выбранных приёмов пищи.")
    items = api("GET", "/api/menu") or []
    if items:
        st.dataframe(items, use_container_width=True, hide_index=True)
    else:
        st.info("Меню пока пусто или API недоступен.")
    st.markdown("### Добавить блюдо")
    with st.form("add_menu"):
        meal = st.selectbox("Приём пищи", ["Завтрак", "Обед"])
        name = st.text_input("Название блюда", placeholder="Например, овощной салат")
        category = st.selectbox("Категория", ["рыба", "мясо", "овощи", "гарнир", "суп", "фрукты", "другое"])
        submitted = st.form_submit_button("Добавить блюдо", type="primary")
        if submitted:
            if not name.strip():
                st.error("Введите название блюда.")
            elif api("POST", "/api/menu", json={"meal": meal, "name": name.strip(), "category": category}):
                st.success("Блюдо добавлено.")
                st.rerun()
    if items:
        st.markdown("### Удалить блюдо")
        chosen = st.selectbox("Позиция меню", items, format_func=lambda x: f'{x["name"]} · {x["meal"]}')
        if st.button("Удалить выбранное"):
            result = api("DELETE", f'/api/menu/{chosen["id"]}')
            if result is not None:
                st.success("Позиция удалена.")
                st.rerun()

elif page == "Проверка событий":
    page_header("Контроль качества", "Очередь проверки", "Просматривайте результаты и подтверждайте или исправляйте решения модели.")
    status_filter = st.selectbox("Статус события", ["Все", "review", "approved", "corrected", "dismissed"])
    kwargs = {} if status_filter == "Все" else {"params": {"status": status_filter}}
    events_response = api("GET", "/api/events", **kwargs)
    events = (events_response or {}).get("items", []) if isinstance(events_response, dict) else (events_response or [])
    if not events:
        st.info("Событий для отображения нет либо API временно недоступен.")
    for event in events:
        with st.expander(f'Событие #{event["id"]} · {event["meal"]} · {event["created_at"]} · {event["status"]}', expanded=event["status"] == "review"):
            st.write("Обнаруженные продукты:", ", ".join(event.get("items") or []) or "Не определены")
            st.write("Состояние тарелки:", {
                "empty_detected": "Обнаружена пустая тарелка",
                "food_detected": "Обнаружена пища",
                "unknown": "Не определено",
            }.get(event.get("plate_status", "unknown"), "Не определено"))
            st.write(event.get("note", ""))
            with st.form(f'review_{event["id"]}'):
                choices = ["review", "approved", "corrected", "dismissed"]
                status = st.selectbox("Решение", choices, index=choices.index(event["status"]))
                items_text = st.text_input("Продукты через запятую", value=", ".join(event.get("items") or []))
                note = st.text_input("Комментарий", value=event.get("note", ""))
                if st.form_submit_button("Сохранить решение", type="primary"):
                    payload = {"status": status, "items": [x.strip() for x in items_text.split(",") if x.strip()], "note": note}
                    if api("PATCH", f'/api/events/{event["id"]}', json=payload):
                        st.success("Изменения сохранены.")
                        st.rerun()


elif page == "Администратор системы":
    page_header("SYSTEM ADMINISTRATION", "Центр управления камерой", "Мониторинг API и модели, настройка IP-камеры, диагностика и обслуживание событий.")
    health = api("GET", "/health", show_error=False)
    events_response = api("GET", "/api/events", show_error=False)
    events = (events_response or {}).get("items", []) if isinstance(events_response, dict) else (events_response or [])
    model_ready = bool((health or {}).get("model_weights_configured"))
    a, b, c, d = st.columns(4)
    a.metric("API", "ONLINE" if health else "OFFLINE")
    b.metric("Модель", "НАСТРОЕНА" if model_ready else "НЕ ПОДКЛЮЧЕНА")
    c.metric("События", len(events))
    d.metric("На проверке", sum(1 for e in events if e.get("status") == "review"))
    st.markdown("### 1. Подключение камеры")
    st.caption("Адрес хранится в текущей сессии панели. Реальный видеопоток требует отдельного подключения камеры к серверу.")
    camera_url = st.text_input("IP / URL камеры", value=st.session_state.get("trayeye_camera_url", "http://192.168.1.100"), placeholder="http://192.168.1.100 или rtsp://...")
    if st.button("Сохранить адрес камеры", use_container_width=True):
        parsed = urlparse(camera_url.strip())
        if parsed.scheme not in {"http", "https", "rtsp"} or not parsed.hostname:
            st.error("Укажи URL с http://, https:// или rtsp://.")
        else:
            st.session_state["trayeye_camera_url"] = camera_url.strip()
            st.success("Адрес сохранён в текущей сессии панели.")
    st.info("RTSP нельзя проверить обычным HTTP-запросом. Live-view требует сетевого доступа к потоку и настройки API.")
    st.markdown("### 2. Диагностика системы")
    st.write("Адрес API:", API)
    st.write("Статус API:", (health or {}).get("status", "Нет связи"))
    st.write("Веса модели заданы:", "Да" if model_ready else "Нет — распознавание не подтверждено")
    st.write("Порог уверенности:", os.getenv("TRAYEYE_CONFIDENCE", "0.25"))
    if st.button("Повторить проверку API", use_container_width=True):
        st.rerun()
    st.markdown("### 3. Демонстрация сканирования еды")
    st.caption("Это условный пример интерфейса, не реальный ответ нейросети.")
    if st.button("Показать пример сканирования", use_container_width=True):
        st.session_state["trayeye_demo_scan"] = True
    if st.session_state.get("trayeye_demo_scan"):
        st.markdown('<div class="trayeye-panel"><h4>Результат · ДЕМО</h4><p>Рыба — 96%</p><p>Овощи — 91%</p><p>Картофель — 88%</p><p>Статус: ожидает проверки сотрудника.</p></div>', unsafe_allow_html=True)
        st.warning("Проценты условные и не получены моделью.")
    st.markdown("### 4. Удаление ошибочного события")
    st.caption("Удаление необратимо для текущего хранилища. Подтверди действие перед удалением.")
    if events:
        chosen_event = st.selectbox("Событие", events, format_func=lambda e: f'#{e["id"]} · {e.get("status", "—")} · {e.get("created_at", "—")}')
        confirmed = st.checkbox(f'Подтверждаю удаление события #{chosen_event["id"]}')
        if st.button("Удалить событие", disabled=not confirmed, use_container_width=True):
            result = api("DELETE", f'/api/events/{chosen_event["id"]}')
            if result is not None:
                st.success("Событие удалено.")
                st.rerun()
    else:
        st.info("Журнал событий пуст.")
    st.markdown("### 5. Памятка администратора")
    st.write("- Обучай модель на размеченных кадрах именно вашей камеры.")
    st.write("- Не удаляй спорные результаты до проверки сотрудником.")
    st.write("- Не публикуй пароли камеры и файлы весов в Git.")
    st.write("- Сейчас события, меню и расписание хранятся в памяти и сбрасываются после перезапуска.")

elif page == "Настройки":
    page_header("Конфигурация", "Настройки системы", "Настройте расписание и проверьте адрес API.")
    sched = api("GET", "/api/schedule") or {"breakfast_start": "08:00", "lunch_start": "12:00"}
    st.markdown("### Расписание столовой")
    with st.form("schedule"):
        breakfast = st.time_input("Начало завтрака", value=time.fromisoformat(sched["breakfast_start"]))
        lunch = st.time_input("Начало обеда", value=time.fromisoformat(sched["lunch_start"]))
        if st.form_submit_button("Сохранить расписание", type="primary"):
            if breakfast >= lunch:
                st.error("Начало завтрака должно быть раньше начала обеда.")
            else:
                result = api("PUT", "/api/schedule", json={"breakfast_start": breakfast.strftime("%H:%M"), "lunch_start": lunch.strftime("%H:%M")})
                if result:
                    st.success(f'Расписание сохранено. Сейчас: {result["current_meal"]}.')
    st.markdown("### Подключение сервера")
    st.code(API, language=None)
    st.caption("Если здесь указан неверный адрес, обновите переменную TRAYEYE_API_URL в настройках сервиса dashboard в Render.")
    st.caption("Для защищённого доступа установите одинаковый TRAYEYE_ADMIN_TOKEN у API и dashboard.")
    st.caption("Telegram-уведомления ещё не реализованы. Для постоянного хранения данных и реального использования в школе понадобится база данных и настройка доступа.")
