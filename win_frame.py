"""
win_frame.py
------------
Windows'un baslik seridini kaldirip pencerenin tamamini uygulamaya verir; pencere
DAVRANISLARI (kenardan boyutlandirma, surukleme, cift tikla buyutme, kenara yaslama,
golge, kucult/buyut animasyonu) Windows'ta kalir.

Yontem (yaygin "cercevesiz ama yerel" teknigi):
  1) Qt'ye FramelessWindowHint: Qt cerceve payi hesaplamaz.
  2) Pencere stiline WS_CAPTION | WS_THICKFRAME geri eklenir: Windows pencereyi hala
     "normal pencere" sayar -> animasyon, yaslama, golge calisir.
  3) WM_NCCALCSIZE: "istemci alani = pencerenin tamami" denir (baslik / cerceve cizilmez).
     Ekrani kaplamisken Windows pencereyi cerceve kalinligi kadar ekran disina tasirir;
     o kadar iceri cekilir (yoksa kenarlar kesilir).
  4) WM_NCHITTEST: kenarlar -> boyutlandirma; bizim seridin bos yeri -> HTCAPTION.

Ana pencere mesajlari kendi nativeEvent'inden yollar (native_event). ILETISIM KUTULARI icin
uygulama geneli bir suzgec vardir (install + attach_dialog): her kutuya nativeEvent yazmak
gerekmez, QMessageBox gibi hazir kutular da ayni yoldan gecer.

Yalnizca Windows. Baska sistemde (ya da REVORA_NATIVE_FRAME=1 ile) hic devreye girmez.
"""
import os
import sys
import weakref

ACTIVE = sys.platform == "win32" and os.environ.get("REVORA_NATIVE_FRAME") != "1"
BORDER = 6                                   # kenardan boyutlandirma payi (ekran pikseli / olcek)

if ACTIVE:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        shell32 = ctypes.windll.shell32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.IsZoomed.argtypes = [wintypes.HWND]
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

        class MARGINS(ctypes.Structure):
            _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                        ("top", ctypes.c_int), ("bottom", ctypes.c_int)]

        class NCCALCSIZE_PARAMS(ctypes.Structure):
            _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]

        class APPBARDATA(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uCallbackMessage", wintypes.UINT),
                        ("uEdge", wintypes.UINT), ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]
    except Exception:
        ACTIVE = False

GWL_STYLE = -16
WS_CAPTION, WS_THICKFRAME = 0x00C00000, 0x00040000
WS_MINIMIZEBOX, WS_MAXIMIZEBOX, WS_SYSMENU = 0x00020000, 0x00010000, 0x00080000
SWP_NOSIZE, SWP_NOMOVE, SWP_NOZORDER, SWP_FRAMECHANGED = 0x0001, 0x0002, 0x0004, 0x0020
WM_NCCALCSIZE, WM_NCHITTEST = 0x0083, 0x0084
WVR_REDRAW = 0x0300
HTCLIENT, HTCAPTION = 1, 2
HTLEFT, HTRIGHT, HTTOP, HTTOPLEFT, HTTOPRIGHT, HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 10, 11, 12, 13, 14, 15, 16, 17
SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER = 32, 33, 92
ABM_GETSTATE, ABM_GETTASKBARPOS, ABS_AUTOHIDE = 4, 5, 1


def setup(win):
    """Pencere gosterilmeden once bir kez cagrilir. Basarili olursa True."""
    if not ACTIVE:
        return False
    try:
        from PySide6.QtCore import Qt
        win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowSystemMenuHint
                           | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        hwnd = int(win.winId())
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX
                              | WS_MAXIMIZEBOX | WS_SYSMENU)
        # golge: cerceve 1 piksel istemci alanina uzatilir (pencere "cercevesiz" sayilmasin)
        m = MARGINS(1, 1, 1, 1)
        dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(m))
        refresh(win)
        return True
    except Exception:
        return False


def needs_border():
    """Windows 10'da cercevesiz pencerenin kenar cizgisi yok (koyu pencere koyu zeminde
    kayboluyor): 1 piksel kenarligi biz cizeriz. Windows 11 kendi kenarligini cizer."""
    try:
        return ACTIVE and sys.getwindowsversion().build < 22000
    except Exception:
        return False


def restore_and_raise(win):
    """Pencereyi one getir (simge durumundaysa geri ac) - Windows'un kendi komutuyla."""
    try:
        hwnd = int(win.winId())
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)                # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass
    win.raise_()
    win.activateWindow()


def is_zoomed(win):
    try:
        return bool(user32.IsZoomed(int(win.winId())))
    except Exception:
        return win.isMaximized()


def toggle_max(win):
    """Ekrani kapla / onceki boyut - WINDOWS'un kendi komutuyla.
    Qt'nin showMaximized()'i cercevesiz pencerede gercek "ekrani kapla" yapmaz: pencereyi
    calisma alanina TASIR (MoveWindow). O zaman Windows pencereyi buyumus saymaz: basliktan
    surukleyince eski boyuta donmez, kenarlari boyutlandirilabilir kalir, animasyon olmaz.
    ShowWindow ile gercek durum degisir; Qt bunu WM_SIZE'dan ogrenir (isMaximized dogru)."""
    hwnd = int(win.winId())
    user32.ShowWindow(hwnd, 9 if user32.IsZoomed(hwnd) else 3)      # SW_RESTORE / SW_MAXIMIZE


def refresh(win):
    """Cerceveyi yeniden hesaplat (stil degisince / baska olcekli ekrana gecince)."""
    if not ACTIVE:
        return
    try:
        from PySide6.QtWidgets import QWidget
        user32.SetWindowPos(int(QWidget.winId(win)), None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
    except Exception:
        pass


def _frame(hwnd, horizontal):
    """Ekrani kaplamis pencerenin ekran disina tasan cerceve kalinligi (ekran pikseli)."""
    idx = SM_CXSIZEFRAME if horizontal else SM_CYSIZEFRAME
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        return user32.GetSystemMetricsForDpi(idx, dpi) + user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
    except Exception:                         # Windows 10 1607 oncesi
        return user32.GetSystemMetrics(idx) + user32.GetSystemMetrics(SM_CXPADDEDBORDER)


def _autohide_edge():
    """Gorev cubugu "otomatik gizle" ise kenari: 0 sol, 1 ust, 2 sag, 3 alt; degilse None."""
    try:
        d = APPBARDATA()
        d.cbSize = ctypes.sizeof(APPBARDATA)
        if not shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(d)) & ABS_AUTOHIDE:
            return None
        shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(d))
        return d.uEdge
    except Exception:
        return None


# ------------------------------------------------------------------ iletisim kutulari
_dialogs = {}            # hwnd -> (zayif referans, is_caption, boyutlandirilabilir_mi())
_filter = None


def install(app):
    """Uygulama geneli yerel olay suzgeci (bir kez). Yalnizca attach_dialog ile kaydedilen
    pencerelerin cerceve mesajlarina bakar; digerlerinde hemen cikar."""
    global _filter
    if not ACTIVE or _filter is not None:
        return
    from PySide6.QtCore import QAbstractNativeEventFilter

    class _Filter(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            try:
                msg = wintypes.MSG.from_address(int(message))
                ent = _dialogs.get(msg.hWnd)
                if ent is None or msg.message not in (WM_NCCALCSIZE, WM_NCHITTEST):
                    return False, 0
                win = ent[0]()
                if win is None:
                    _dialogs.pop(msg.hWnd, None)
                    return False, 0
                return native_event(win, message, ent[1], ent[2])
            except Exception:
                return False, 0

    _filter = _Filter()
    app.installNativeEventFilter(_filter)


def attach_dialog(dlg, is_caption, resizable):
    """Iletisim kutusunun (FramelessWindowHint verilmis) yerel penceresini hazirla: golge ve
    surukleme icin stil + suzgece kayit. Pencere yeniden olusturulursa tekrar cagrilir."""
    if not ACTIVE or _filter is None:
        return False
    try:
        from PySide6.QtWidgets import QWidget
        hwnd = int(QWidget.winId(dlg))             # (dlg.winId() degil: ad cakismasi olabilir)
        for h in [h for h, e in _dialogs.items() if e[0]() is None or e[0]() is dlg]:
            _dialogs.pop(h, None)
        _dialogs[hwnd] = (weakref.ref(dlg), is_caption, resizable)
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        user32.SetWindowLongW(hwnd, GWL_STYLE, style | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU)
        m = MARGINS(1, 1, 1, 1)
        dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(hwnd), ctypes.byref(m))
        refresh(dlg)
        return True
    except Exception:
        return False


def native_event(win, message, is_caption, resizable=None):
    """QMainWindow.nativeEvent icinden (ya da kutular icin suzgecten) cagrilir -> (islendi_mi, sonuc).
    is_caption(QPoint pencere koordinati) -> o nokta surukleme (baslik) alani mi?
    resizable() False donerse kenarlardan boyutlandirma yok (sabit boyutlu kutu)."""
    if not ACTIVE:
        return False, 0
    msg = wintypes.MSG.from_address(int(message))
    if not msg.hWnd:
        return False, 0
    if msg.message == WM_NCCALCSIZE:
        if msg.wParam:
            rc = NCCALCSIZE_PARAMS.from_address(msg.lParam).rgrc[0]
        else:
            rc = wintypes.RECT.from_address(msg.lParam)
        if user32.IsZoomed(msg.hWnd):
            fx, fy = _frame(msg.hWnd, True), _frame(msg.hWnd, False)
            rc.left += fx
            rc.right -= fx
            rc.top += fy
            rc.bottom -= fy
            edge = _autohide_edge()           # gizli gorev cubugu fareyle cikabilsin: 2 px birak
            if edge == 0:
                rc.left += 2
            elif edge == 1:
                rc.top += 2
            elif edge == 2:
                rc.right -= 2
            elif edge == 3:
                rc.bottom -= 2
        return True, (WVR_REDRAW if msg.wParam else 0)
    if msg.message == WM_NCHITTEST:
        from PySide6.QtCore import QPoint
        wr = wintypes.RECT()
        user32.GetWindowRect(msg.hWnd, ctypes.byref(wr))
        sx = ctypes.c_short(msg.lParam & 0xFFFF).value          # ekran pikseli (negatif olabilir)
        sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
        from PySide6.QtWidgets import QWidget
        k = QWidget.devicePixelRatioF(win) or 1.0
        x, y = (sx - wr.left) / k, (sy - wr.top) / k
        w, h = (wr.right - wr.left) / k, (wr.bottom - wr.top) / k
        if not user32.IsZoomed(msg.hWnd) and (resizable is None or resizable()):
            left, right, top, bottom = x < BORDER, x >= w - BORDER, y < BORDER, y >= h - BORDER
            if top and left:
                return True, HTTOPLEFT
            if top and right:
                return True, HTTOPRIGHT
            if bottom and left:
                return True, HTBOTTOMLEFT
            if bottom and right:
                return True, HTBOTTOMRIGHT
            if left:
                return True, HTLEFT
            if right:
                return True, HTRIGHT
            if top:
                return True, HTTOP
            if bottom:
                return True, HTBOTTOM
        if is_caption(QPoint(int(x), int(y))):
            return True, HTCAPTION
        return False, 0
    return False, 0
