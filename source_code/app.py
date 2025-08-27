import webview
import threading
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from pathlib import Path
import json
import uuid
import datetime as dt
import sys
import time
from PIL import Image, ImageDraw
import os
import ctypes
from win10toast import ToastNotifier
import pystray
import logging
import urllib.request

try:
    from delete_func_scripts import delete_local_temp, delete_temp, delete_prefetch, delete_recents
except Exception:
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, os.path.join(base_path, 'delete_func_scripts'))
    from delete_func_scripts import delete_local_temp, delete_temp, delete_prefetch, delete_recents

app = Flask(__name__)
CORS(app)

LOG_PATH = Path('data/tempdeleter.log')
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(LOG_PATH),
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

DATA_FILE = Path('data/tasks.json')
DATA_FILE.parent.mkdir(exist_ok=True)

# görev kontrolü için
task_checker_running = False

# tepsi için
tray_icon = None
webview_window = None

# uygulama kapatıldığında bildirim göndermesin diye
is_quitting = False

script_map = {
    "local_temp": delete_local_temp.clean,
    "temp": delete_temp.clean,
    "prefetch": delete_prefetch.clean,
    "recents": delete_recents.clean
}

# Windows sistem tepsisi icon'u için AppID ayarlar
def set_app_id():
    try:
        app_id = u"TikaBasa.TempDeleter.App"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        logging.debug("AppID başarıyla ayarlandı: %s", app_id)
    except Exception as e:
        logging.exception("AppID ayarlanırken hata oluştu: %s", e)

set_app_id()

# sistem tepsisi için bir ikon oluşturur
def create_tray_icon():
    """
    icon.ico'yu kullanır (static/icon.ico). eğer onu bulamazsa icon.png'yi kullanır (static/icon.png).
    onu da bulamazsa kendisi düz bir renk oluşturup tepside kullanmak üzere ekler
    """
    try:
        def resource_path(rel_path):
            if getattr(sys, 'frozen', False):
                base = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
            else:
                base = os.path.dirname(os.path.abspath(__file__))
            return os.path.join(base, rel_path)

        ico_rel = os.path.join('static', 'icon.ico')
        ico_path = resource_path(ico_rel)

        if os.path.exists(ico_path):
            icon_image = Image.open(ico_path)
            icon_image = icon_image.convert('RGBA')
            icon_image.thumbnail((64, 64), Image.LANCZOS)
            return icon_image

        png_rel = os.path.join('static', 'icon.png')
        png_path = resource_path(png_rel)
        if os.path.exists(png_path):
            icon_image = Image.open(png_path).convert('RGBA')
            icon_image.thumbnail((64, 64), Image.LANCZOS)
            return icon_image

        icon_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon_image)
        draw.ellipse([6, 6, 58, 58], fill=(98, 85, 211, 255), outline=(79, 70, 200, 255))
        return icon_image

    except Exception as e:
        logging.exception("create_tray_icon hata")
        icon_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(icon_image)
        draw.ellipse([6, 6, 58, 58], fill=(59, 130, 246, 255), outline=(37, 99, 235, 255))
        return icon_image


_TOASTER = ToastNotifier()
_NOTIFY_LOCK = threading.Lock()

def notify(text: str, *, duration: int = 3, wait_for_previous: bool = False):
    """
    Tek kanaldan, sıralı şekilde toast göndermek için. (işlem sonunda bildirim örtüşmesini önlemek amacıyla yazıldı)
    wait_for_previous=True ise, önceki toast kapanana kadar bekler.
    """
    try:
        # ikon yolu
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.abspath(".")
        icon_path = os.path.join(base_path, "static", "icon.ico")
        icon = icon_path if os.path.exists(icon_path) else None

        with _NOTIFY_LOCK:
            if wait_for_previous:
                # önceki toast kapanana kadar bekler (örtüşme olmasın diye 5 saniye es verilir)
                start = time.time()
                while _TOASTER.notification_active() and (time.time() - start) < 5:
                    time.sleep(0.1)

            # üst üste binmeyi engeller
            _TOASTER.show_toast(
                "Temp Deleter",
                text,
                duration=duration,
                threaded=True,
                icon_path=icon
            )

            # action center'a düşmesin diye ufak gecikme
            time.sleep(0.05)

    except Exception as e:
        logging.debug("Toast gönderilirken hata oluştu: %s", e)


# Windows'a bildirim göndermek için kullanılır.
def show_notification(text, *, wait_for_previous=False):
    notify(text, duration=3, wait_for_previous=wait_for_previous)

# sistem tepsisindeki ikona sağ tık yapılırsa açılacak menüyü hazırlar
def on_tray_click(icon, item):
    try:
        if str(item) == "Temp Deleter":
            show_main_window()
        elif str(item) == "Çıkış":
            quit_application()
    except Exception as e:
        logging.exception("Sistem tepsisi menüsünü yüklerken hata oluştu: %s",e)

# açılan sağ tık menüsünden "Temp Deleter" seçilirse uygulamayı geri açar
def show_main_window():
    global webview_window
    if webview_window:
        try:
            webview_window.show()
            webview_window.restore()
        except Exception as e:
            logging.exception("Uygulama penceresi yüklenirken hata oluştu: %s",e)

# kapatma sürecinde, uygulamanın kapanmasını önler ve pencereyi gizler.
def hide_main_window():
    global webview_window, is_quitting
    if webview_window:
        try:
            webview_window.hide()
            if not is_quitting:  # sadece normal kapatma için göster
                show_notification("Temp deleter arkaplanda çalışmaya devam ediyor.", wait_for_previous=True)
        except Exception as e:
            logging.exception("Uygulama penceresi gizlenirken hata oluştu: %s", e)
            
# tray menü'den "Çıkış"a basılırsa çalışır. Uygulamayı kapatır.
def quit_application():
    global task_checker_running, tray_icon, webview_window, is_quitting
    is_quitting = True  # kapatılırken bildirim atmasın diye engel
    logging.info("Uygulama kapanıyor (quit_application çağrıldı)")
    task_checker_running = False
    try:
        if tray_icon:
            tray_icon.stop()
    except Exception as e:
        logging.debug("tray stop sürecinde hata oluştu: %s", e)
    try:
        if webview_window:
            webview_window.destroy()
    except Exception as e:
        logging.debug("webview destroy sürecinde hata oluştu: %s", e)
    os._exit(0)

# sistem tepsisine item oluşturur
def create_system_tray():
    global tray_icon
    try:
        menu = pystray.Menu(
            pystray.MenuItem("Temp Deleter", on_tray_click),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Çıkış", on_tray_click)
        )
        icon_image = create_tray_icon()
        tray_icon = pystray.Icon("temp_deleter", icon_image, "Temp Deleter", menu)
        tray_icon.on_activate = lambda icon: show_main_window()
        return tray_icon
    except Exception as e:
        logging.exception("Sistem tepsisi ögesini oluştururken hata oluştu: %s",e)
        return None
    
# api kısmı için gerekli fonksiyonlar
def now():
    return dt.datetime.now()

def parse_dt(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None

def load_tasks():
    if DATA_FILE.exists():
        try:
            txt = DATA_FILE.read_text(encoding='utf-8').strip()
            if not txt:
                return []
            tasks = json.loads(txt)

            # front-end kısmındaki görüntüleme seçimi için
            changed = False
            for t in tasks:
                if 'display_format' not in t or t.get('display_format') not in ('compact', 'detailed'):
                    t['display_format'] = 'compact'
                    changed = True
            if changed:
                try:
                    save_tasks(tasks)
                except Exception:
                    logging.exception("load_tasks: display_format defaults kaydedilemedi")
            return tasks

        except Exception as e:
            logging.exception("JSON verisi sorunlu")
            return []
    return []

def save_tasks(tasks):
    DATA_FILE.parent.mkdir(exist_ok=True)
    DATA_FILE.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding='utf-8')

def get_task(task_id):
    tasks = load_tasks()
    for t in tasks:
        if t['id'] == task_id:
            return t
    return None

def upsert_task(updated):
    tasks = load_tasks()
    found = False
    for i, t in enumerate(tasks):
        if t['id'] == updated['id']:
            tasks[i] = updated
            found = True
            break
    if not found:
        tasks.append(updated)
    save_tasks(tasks)

# işlemin aralık dakikasını almaya çalışır. dakikayı alamazsa saati alıp dakikaya çevirir
def get_interval_minutes(task):
    if 'interval_minutes' in task and task['interval_minutes'] is not None:
        try:
            return int(task['interval_minutes'])
        except Exception:
            pass
    if 'interval_hours' in task and task['interval_hours'] is not None:
        try:
            return int(task['interval_hours']) * 60
        except Exception:
            pass
    return None

# "aynı işlem var mı?"yı kontrol eder
def check_duplicate_task(task_id=None, interval_minutes=None, folders=None):
    """
    Filtreleme şu şekilde çalışır. Fonksiyon, gelen işlemin:
    - aralığı (kaç saatte bir)
    - silinecek klasörleri
    özelliklerine sahip başka bir aktif öge bulursa hata döndürür.
    Fakat gelen işlemin aktifliği kapalı ise success döndürür
    """
    if not interval_minutes or not folders:
        return None
    tasks = load_tasks()
    for task in tasks:
        if task_id and task['id'] == task_id:
            continue
        if not task.get('active'):
            continue
        task_interval = get_interval_minutes(task)
        if task_interval != interval_minutes:
            continue
        task_folders = set(task.get('folders', []))
        check_folders = set(folders)
        if task_folders == check_folders:
            return task
    return None

# işlem kontrolünü ve kontrole bağlı çalıştırılmasını ayarlar
def check_and_run_due_tasks():
    tasks = load_tasks()
    current_time = now()
    for task in tasks:
        if not task.get('active'):
            continue
        next_run = parse_dt(task.get('next_run'))
        if next_run and next_run <= current_time:
            # işlemi süresi gelmiş demektir.
            logging.info("[TASK CHECKER] Task %s (%s) çalıştırılıyor", task['id'], task['name'])
            threading.Thread(target=run_task, args=(task['id'],), daemon=True).start()

# işlemlerin bir sonraki işlem zamanlarını kontrol eden bir döngü (5 saniyede bir yapar)
def task_checker_loop():
    global task_checker_running
    task_checker_running = True
    logging.info("task_checker_loop başlatıldı")
    while task_checker_running:
        try:
            check_and_run_due_tasks()
            time.sleep(5)
        except Exception as e:
            logging.exception("İşlem kontrol edilirken sorun oluştu: %s",e)
            time.sleep(5)

# işlemin bir sonraki işlem zamanını ayarlar
# * kullanılmasının sebebi, okunabilirliği artırmak
def schedule_next_run_for_task(task, *, force_from_now=False, interval_changed=False):
    """
    Parametreler :
    - force_from_now = ne olursa olsun hesaplamayı şimdiden itibaren başlat demektir
    - interval_changed = düzenleme sayfasından aralık değişimi yapıldıysa gelir.
    
    İşleyiş :
    - aralık değiştiyse ya da şimdiden itibaren mesajı gelirse aralık belirleme o ana işlem süresini ekler.
    - 'next_run' gelecekte ise, zamanlama korunur.
    - aksi halde, sonraki işlem süresi = now + interval olarak güncellenir.

    """
    minutes = get_interval_minutes(task)
    if not minutes or minutes <= 0:
        return
    n = now()
    existing_next = parse_dt(task.get('next_run'))
    
    if force_from_now or interval_changed:
        nr = n + dt.timedelta(minutes=minutes)
    else:
        if existing_next and existing_next > n:
            nr = existing_next
        else:
            nr = n + dt.timedelta(minutes=minutes)
    task['next_run'] = nr.isoformat()
    upsert_task(task)

# İşlemin progress kısmını geri gönderir
def progress_init_for_task(task):
    progress = {"folders": {}, "done": False}
    for folder in task['folders']:
        progress["folders"][folder] = {"current": 0, "total": 0}
    return progress


def update_progress(task_id, progress_dict):
    """
    İlerleyiş : 
    dosya silme işlemi için ilerleme bilgisini yazar.
    
    Sonuç verisi : 
    - current = silinen dosya sayısı
    - total = toplam hedef dosya sayısı
    
    Örnek yapı : 
    "klasör_adı": {
        "current": 16,
        "total": 16
    },
    
    """
    tasks = load_tasks()
    for t in tasks:
        if t['id'] == task_id:
            t['progress'] = progress_dict
            break
    save_tasks(tasks)

# START ui routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/edit/<task_id>')
def edit(task_id):
    return render_template('edit.html', task_id=task_id)

@app.route('/create')
def create():
    return render_template('create.html')
# END ui routes


# START api
@app.route('/api/tasks', methods=['GET'])
def api_get_tasks():
    return jsonify(load_tasks())

# işlem oluşturma
@app.route('/api/tasks', methods=['POST'])
def api_create_task():
    """
    İşlem kaydetme ['POST']
    
    Aynı verilere sahip bir işlem yoksa success döner ve tasks.json belgesine işlemi yazar.
    Bir hata oluşması dahilinde
    """
    data = request.json or {}
    task_id = str(uuid.uuid4())
    interval_minutes = data.get('interval_minutes', None)
    interval_hours = data.get('interval_hours', None)
    if interval_minutes is None and interval_hours is not None:
        interval_minutes = float(interval_hours) * 60
    if interval_minutes is not None:
        interval_minutes = float(interval_minutes)
    task = {
        'id': task_id,
        'name': data.get('name') or f"İşlem {task_id[:6]}",
        'active': bool(data.get('active', False)),
        'folders': list(data.get('folders', [])),
        'interval_minutes': interval_minutes,
        'interval_hours': data.get('interval_hours'),
        'last_run': None,
        'next_run': None,
        'progress': None,
        # yeni alan: display_format (compact veya detailed)
        'display_format': data.get('display_format', 'compact')
    }
    if task['active']:
        duplicate = check_duplicate_task(
            interval_minutes=interval_minutes,
            folders=task['folders']
        )
        if duplicate:
            return jsonify({
                'status': 'duplicate',
                'message': f"'{duplicate['name']}' adında aynı özelliklerde aktif bir görev zaten mevcut.",
                'duplicate_task': duplicate
            }), 400
    
    upsert_task(task)
    if task['active']:
        schedule_next_run_for_task(task, force_from_now=True)
    return jsonify({'status': 'ok', 'task': task})

# işlem güncelleme
@app.route('/api/tasks/<task_id>', methods=['PUT'])
def api_update_task(task_id):
    """
    Güncelleme ['PUT']

    İşleyiş :
    - Gelen yeni işlem verisi ile o ID'ye sahip veri güncellenir. 
    
    - İşlem aktif hale getirildiyse,
    - Daha önce aktif değilse,
    - İşlem aralığı değiştiyse,
    - Silinecek klasörler değiştiyse,
    Aynı özelliklerde başka bir işlem var mı diye kontrol eder. 

    
    Geri dönümler:
        'not_found': İşlem bulunamadı,
        'duplicate': Aynı özelliklere sahip başka bir işlem bulundu,
        'ok': İşleyiş başarılı
    """
    data = request.json or {}
    task = get_task(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    old_active = bool(task.get('active', False))
    old_interval_minutes = get_interval_minutes(task)
    if 'name' in data:
        task['name'] = data['name']
    if 'folders' in data:
        task['folders'] = list(data['folders'])
    if 'active' in data:
        task['active'] = bool(data['active'])
    interval_minutes = data.get('interval_minutes')
    interval_hours = data.get('interval_hours')
    if interval_minutes is None and interval_hours is not None:
        interval_minutes = int(interval_hours) * 60
        task['interval_hours'] = interval_hours
    if interval_minutes is not None:
        task['interval_minutes'] = int(interval_minutes)

    # formatlama için
    if 'display_format' in data:
        val = data.get('display_format')
        if val in ('compact', 'detailed'):
            task['display_format'] = val

    if task['active']:
        if not old_active or (old_interval_minutes != get_interval_minutes(task)) or 'folders' in data:
            duplicate = check_duplicate_task(
                task_id=task_id,
                interval_minutes=get_interval_minutes(task),
                folders=task['folders']
            )
            if duplicate:
                return jsonify({
                    'status': 'duplicate',
                    'message': f"'{duplicate['name']}' adında aynı özelliklerde aktif bir görev zaten mevcut.",
                    'duplicate_task': duplicate
                }), 400
    upsert_task(task)
    new_interval_minutes = get_interval_minutes(task)
    interval_changed = (old_interval_minutes != new_interval_minutes)
    if task['active']:
        if not old_active:
            next_run = parse_dt(task.get('next_run'))
            if next_run and next_run > now():
                logging.info("İşlem %s aktifleştirildi; mevcut next_run korunuyor: %s", task_id, next_run)
            else:
                logging.info("İşlem %s aktifleştirildi; yeni next_run hesaplanıyor", task_id)
                schedule_next_run_for_task(task, force_from_now=True)
        elif interval_changed:
            schedule_next_run_for_task(task, interval_changed=True)
        else:
            schedule_next_run_for_task(task)
    else:
        upsert_task(task)
    return jsonify({'status': 'ok', 'task': task})

# display format'ı güncellemek için
@app.route('/api/tasks/<task_id>/display_format', methods=['PATCH'])
def api_update_display_format(task_id):
    data = request.json or {}
    fmt = data.get('display_format')
    if fmt not in ('compact', 'detailed'):
        return jsonify({'status': 'invalid_format', 'message': 'display_format must be "compact" or "detailed"'}), 400
    task = get_task(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    task['display_format'] = fmt
    upsert_task(task)
    return jsonify({'status': 'ok', 'task': task})

# işlem silme
@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def api_delete_task(task_id):
    tasks = [t for t in load_tasks() if t['id'] != task_id]
    save_tasks(tasks)
    return jsonify({'status': 'deleted'})

# İşlem kontrolü
@app.route('/api/tasks/<task_id>/status', methods=['GET'])
def api_task_status(task_id):
    """ 
    İşlem kontrolü
    
    İşleyiş : 
    - ID'si gelen görevin durumunu kontrol eder
    
    Geri dönümler : 
    - 'not_found': ID'ye sahip işlem bulunamadı.
    - 'ok': İşleyiş başarılı. Geriye progress döner.
    
    Örnek veri : 
    
    "progress": {
      "folders": {
        "klasör_adı": {
          "current": 16,
          "total": 16
        },
      },
      "done": true,
      "last_run": "2025-08-23T19:24:55.929319"
    }
    
    """
    task = get_task(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    return jsonify({'status': 'ok', 'progress': task.get('progress')})

# bug ve hata bulmak için debug
@app.route('/api/debug/tasks', methods=['GET'])
def api_debug_tasks():    
    tasks = load_tasks()
    current_time = now()
    task_info = []
    for task in tasks:
        if task.get('active'):
            next_run = parse_dt(task.get('next_run'))
            time_until_run = None
            if next_run:
                diff = (next_run - current_time).total_seconds()
                time_until_run = diff
            task_info.append({
                'id': task['id'],
                'name': task['name'],
                'next_run': task.get('next_run'),
                'time_until_run_seconds': time_until_run,
                'is_due': next_run and next_run <= current_time if next_run else False
            })
    return jsonify({
        'task_checker_running': task_checker_running,
        'current_time': current_time.isoformat(),
        'active_tasks': task_info
    })

# işlemi anlık çalıştırmak için
@app.route('/api/run/<task_id>', methods=['POST'])
def api_run_now(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify({'status': 'not_found'}), 404
    threading.Thread(target=run_task, args=(task_id,), daemon=True).start()
    return jsonify({'status': 'ok', 'message': 'Task started'})
# END api


# işlem çalıştırma
def run_task(task_id):
    start_time = time.process_time()
    """
    İşlem Çalıştırma

    İşleyiş:
    - ID'si verilmiş işlemi alır,
    - İlgili klasörlerde temizlik işlemlerini başlatır.
    - Her klasör için ilerleme durumu takip edilir ve işlem sonunda görev güncellenir.
    - İşlem için için bir sonraki çalıştırma zamanı planlanır.

    Geri Dönümler:
    - 'not_found': İşlem bulunamadı,
    - 'callback_error': Progress kısmında sorun oluştu,
    - 'clean_func_error': Silme script'lerinde sorun oluştu,
    - 'task_not_found': ID'ye sahip işlem bulunamadı,
    
    """


    show_notification("Silme işlemi başlatıldı.", wait_for_previous=False)
    logging.info("[RUN TASK] Task %s başlatılıyor...", task_id)
    with app.app_context():
        task = get_task(task_id)
        if not task:
            logging.exception("run_task: İşlem bulunamadı %s", task_id)
            return
        progress = progress_init_for_task(task)
        update_progress(task_id, progress)
        def make_progress_callback(folder_name):
            def _cb(p):
                try:
                    current_state = get_task(task_id)
                    pg = current_state.get('progress') or {"folders": {}, "done": False}
                    pg['folders'][folder_name] = {
                        "current": int(p.get('current', 0)),
                        "total": int(p.get('total', 0)),
                    }
                    pg['done'] = False
                    update_progress(task_id, pg)
                except Exception:
                    logging.exception("Progress callback verilirken hata oluştu")
            return _cb
        for folder in task['folders']:
            clean_func = script_map.get(folder)
            if not clean_func:
                cb = make_progress_callback(folder)
                cb({"current": 0, "total": 0})
                continue
            cb = make_progress_callback(folder)
            try:
                clean_func(cb)
            except Exception as e:
                logging.exception("Silme fonksiyonlarında hata oluştu (%s): %s", folder, e)
            current_state = get_task(task_id)
            pg = current_state.get('progress') or {"folders": {}, "done": False}
            if folder in pg["folders"]:
                tot = pg["folders"][folder].get("total", 0)
                pg["folders"][folder]["current"] = tot
                update_progress(task_id, pg)
        finished_at = now().isoformat()
        t = get_task(task_id)
        if not t:
            logging.warning("run_task: görev tamamlandı ancak task record bulunamadı")
            return
        t['last_run'] = finished_at
        pg = t.get('progress') or {"folders": {}, "done": False}
        pg['done'] = True
        pg['last_run'] = finished_at
        t['progress'] = pg
        upsert_task(t)
        end_time = time.process_time()
        elapsed_time = end_time - start_time
        print(f"Elapsed CPU time: {elapsed_time} seconds")
        if t.get('active'):
            schedule_next_run_for_task(t, force_from_now=True)
            logging.info("[RUN TASK] Task %s tamamlandı (%s), bir sonraki çalışma planlandı", task_id, elapsed_time)
        else:
            logging.info("[RUN TASK] Task %s tamamlandı (%s) (pasif)", task_id, elapsed_time)
        show_notification(f"Silme işlemi tamamlandı ({elapsed_time:.2f} sn).", wait_for_previous=True)

    

def start_flask():
    logging.info("Flask başlatılıyor")
    app.run(debug=False, use_reloader=False, threaded=True)

def wait_for_flask(url="http://127.0.0.1:5000", timeout=20):
    start = time.time()
    while True:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    logging.info("Flask hazır")
                    return True
        except Exception as e:
            logging.debug("wait_for_flask bekliyor: %s", e)
        if time.time() - start > timeout:
            logging.error("Flask servisi %s içinde çalışmadı (timeout).", url)
            return False
        time.sleep(0.5)

def start_gui():
    global webview_window, tray_icon
    try:
        if tray_icon is None:
            tray_icon = create_system_tray()
        webview_window = webview.create_window(
            "Temp Deleter",
            "http://127.0.0.1:5000",
            width=1024,
            height=768,
            maximized=True
        )
        
        # Uygulamayı gizler. "return False" ile kapanmasını önler.
        def on_closing():
            hide_main_window()
            return False
        webview_window.events.closing += on_closing
        
        def on_closed():
            logging.info("Uygulama penceresi kapandı")
        webview_window.events.closed += on_closed

        # tepsiye ekleme
        if tray_icon:
            try:
                threading.Thread(target=tray_icon.run, daemon=False, name="tray").start()
                logging.info("Tepsi işlemi başlatıldı")
            except Exception as e:
                logging.exception("Tepsi işlemi başlatılamadı: %s",e)
                
        webview.start(gui='edgechromium')
    except Exception as e:
        logging.exception("GUI başlatılamadı: %s",e)
        # eğer GUI başlatılamazsa process'i açık bırakır
        while True:
            time.sleep(1)

def start_task_checker_thread():
    """ işlemlerin sürelerini kontrol eder ve süresi geldiğinde çalıştırır """

    tasks = load_tasks()
    for task in tasks:
        if task.get('active'):
            next_run = parse_dt(task.get('next_run'))
            if not next_run or next_run <= now():
                schedule_next_run_for_task(task, force_from_now=True)
                
    # kontrol döngüsünü başlatır
    t = threading.Thread(target=task_checker_loop, daemon=False, name="task-checker")
    t.start()
    return t

if __name__ == "__main__":
    logging.info("TempDeleter başlatılıyor")
    try:
        if not DATA_FILE.exists():
            save_tasks([])
        
        # başlangıçta kontrolü çalıştırır, ki uygulama kapalı kaldığında süresi geçmiş aktif işlemler çalışsın.
        task_checker_thread = start_task_checker_thread()
        logging.info("task checker thread başlatıldı")
    except Exception as e:
        logging.exception("İşlem kontrolü başlatılamadı: %s",e)

    try:
        flask_thread = threading.Thread(target=start_flask, daemon=False, name="flask-server")
        flask_thread.start()
        logging.info("Flask başlatıldı")
    except Exception as e:
        logging.exception("Flask başlatılırken sorun oluştu: %s",e)

    # flask gelene kadar gui oluşturma
    if not wait_for_flask("http://127.0.0.1:5000", timeout=20):
        logging.error("Flask starting is caught to timeout. Check the logs here: %s", LOG_PATH)
    else:
        logging.info("Flask is ready. Starting GUI")
        try:
            start_gui()  # webview.start bloklayacak (ana thread)
        except Exception as e:
            logging.exception("start_gui kısmında hata oluştu: %s",e)

    # Eğer webview geri dönerse veya GUI kapanırsa join'lerle bekle
    try:
        flask_thread.join()
        task_checker_thread.join()
    except Exception as e:
        logging.exception("main join kısmında hata oluştu: %s",e)
