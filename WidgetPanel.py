import requests, keyboard, time
from collections import deque
from functools import partial

from PySide6.QtCore import Qt, QEvent, QTimer, Signal, QPoint
from PySide6.QtGui import QFont, QAction, QColor, QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QVBoxLayout, QLabel, QTableView, QHeaderView, QAbstractItemView, QFrame, QStyledItemDelegate

from Display import SimpleTableModel, KLineDelegate, DEFAULT_UP_COLOR, DEFAULT_DOWN_COLOR, DEFAULT_TABLE_COLOR
MIN_FONT_SIZE = 6
class FloatLabel(QWidget):
    hotkey_triggered = Signal()
    def __init__(self, cfg: dict):
        super().__init__()
        self._on_change = (lambda: None)
        self._open_settings_cb = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 加载配置
        codes_cfg               = cfg.get("codes",["sh000001"])             # 自选列表
        checked_codes_cfg       = cfg.get("checked_codes", cfg.get("visible_codes", codes_cfg))  # 在浮窗中显示的股票（新名 checked_codes，兼容 visible_codes）
        self.refresh_seconds    = int(cfg.get("refresh_seconds", 2))        # 刷新间隔
        flags_cfg               = cfg.get("flags", {})                      # 指标开关（字典格式）
        self.short_code         = bool(cfg.get("short_code", False))
        self.name_length        = int(cfg.get("name_length",0))
        # b1s1_display: 'qty'|'price'|'both'。兼容旧配置键 b1s1_price (bool)
        b1s1_display_cfg = cfg.get("b1s1_display", None)
        if isinstance(b1s1_display_cfg, str) and b1s1_display_cfg in ("qty", "price", "both"):
            self.b1s1_display = b1s1_display_cfg
        else:
            # 旧配置兼容：若 b1s1_price 为 True 则默认显示价格，否则显示数量
            self.b1s1_display = "price" if bool(cfg.get("b1s1_price", False)) else "qty"
        
        # 防止买一/卖一同步时触发重复处理
        self._syncing_b1s1 = False

        self.header_visible     = bool(cfg.get("header_visible", False))    # 表头可见
        self.grid_visible       = bool(cfg.get("grid_visible", False))      # 网格可见

        font_family             = cfg.get("font_family", "Microsoft YaHei") # 字体类型
        font_size               = int(cfg.get("font_size", 10))             # 字体大小
        self.line_extra_px      = int(cfg.get("line_extra_px", 1))          # 行间距
        self.fg                 = QColor(cfg.get("fg", DEFAULT_TABLE_COLOR.name(QColor.HexRgb)))   # 表格颜色（中性/表头/网格）
        self.up_color           = QColor(cfg.get("up_color", DEFAULT_UP_COLOR.name(QColor.HexRgb)))   # 涨颜色
        self.down_color         = QColor(cfg.get("down_color", DEFAULT_DOWN_COLOR.name(QColor.HexRgb))) # 跌颜色
        self.grid_alpha_pct     = max(0, min(100, int(cfg.get("grid_alpha_pct", 31))))  # 表格线/边框不透明度(%)
        self.header_alpha_pct   = max(0, min(100, int(cfg.get("header_alpha_pct", 100))))# 表头文字不透明度(%)
        bg                      = cfg.get("bg", {"r":0,"g":0,"b":0,"a":191})# 背景色
        self.opacity_pct        = int(cfg.get("opacity_pct", 90))           # 透明度

        self.hotkey             = cfg.get("hotkey", "Ctrl+Alt+F")           # 快捷键
        self.start_on_boot      = bool(cfg.get("start_on_boot", False))

        # 锚点：'left' 或 'right'，决定窗口宽度变化时保持哪一边对齐
        anchor_cfg = cfg.get("anchor", "left")
        self.anchor = anchor_cfg if anchor_cfg in ("left", "right") else "left"

        # 双模式切换
        self.dual_mode_enabled = bool(cfg.get("dual_mode_enabled", False))  # 是否启用双模式切换
        self.leave_delay_ms = int(cfg.get("leave_delay_ms", 500))           # 鼠标离开后切换简易模式的延迟(ms)
        self._is_hovered = False  # 鼠标是否悬浮在浮窗上
        # 手动模式：当双模式自动切换关闭时生效，可选 "normal"/"simple"
        manual_mode_cfg = str(cfg.get("manual_mode", "normal")).lower()
        self.manual_mode = manual_mode_cfg if manual_mode_cfg in ("normal", "simple") else "normal"

        # 符号设置：日高/日低、涨停/跌停、涨/跌
        self.sym_high       = cfg.get("sym_high", "↑")         # 日高符号
        self.sym_low        = cfg.get("sym_low", "↓")          # 日低符号
        self.sym_limit_up   = cfg.get("sym_limit_up", "⇧")     # 涨停符号
        self.sym_limit_down = cfg.get("sym_limit_down", "⇩")   # 跌停符号
        self.sym_rise       = cfg.get("sym_rise", "+")          # 涨符号（用于涨跌值/涨跌幅/盈亏/委比）
        self.sym_fall       = cfg.get("sym_fall", "-")          # 跌符号（用于涨跌值/涨跌幅/盈亏/委比）

        # 持仓成本数据：{code: {"cost": float, "qty": int}}
        cost_cfg = cfg.get("cost_data", {}) or {}
        self.cost_data = {}
        if isinstance(cost_cfg, dict):
            for k, v in cost_cfg.items():
                try:
                    if not isinstance(v, dict):
                        continue
                    cost = float(v.get("cost", 0))
                    qty = int(v.get("qty", 0))
                    if cost > 0 and qty != 0:
                        self.cost_data[str(k).strip().lower()] = {"cost": cost, "qty": qty}
                except Exception:
                    pass

        # 封单预警阈值：{code: [int, ...]}（正=涨停封单手数，负=跌停封单手数）
        alert_cfg = cfg.get("alert_data", {}) or {}
        self.alert_data = {}
        self._alert_state = {}  # 运行时生效状态，与 thresholds 索引一一对应
        self._notify_alert = None  # 通知回调 fn(title, msg)
        self._pnl_callback = None  # 总盈亏更新回调 fn(total_pnl: float, has_pnl: bool)
        self._tooltip_callback = None  # 托盘 ToolTip 文本更新回调 fn(text: str)
        if isinstance(alert_cfg, dict):
            for k, v in alert_cfg.items():
                try:
                    if not isinstance(v, list):
                        continue
                    code_key = str(k).strip().lower()
                    ts = []
                    for t in v:
                        try:
                            n = int(t)
                            if n != 0 and n not in ts:
                                ts.append(n)
                        except Exception:
                            pass
                    if ts:
                        self.alert_data[code_key] = ts
                        self._alert_state[code_key] = [False] * len(ts)
                except Exception:
                    pass

        # 涨跌异动报警配置
        price_alert_cfg = cfg.get("price_alert", {}) or {}
        self.price_alert_enabled = bool(price_alert_cfg.get("enabled", False))  # 全局开关
        # 多规则列表：[{"period": int, "threshold": float, "cooldown": int}, ...]
        rules_cfg = price_alert_cfg.get("rules", None)
        if isinstance(rules_cfg, list) and rules_cfg:
            self.price_alert_rules = []
            for r in rules_cfg:
                try:
                    self.price_alert_rules.append({
                        "period": max(1, int(r.get("period", 60))),
                        "threshold": max(0.1, float(r.get("threshold", 2.0))),
                        "cooldown": max(1, int(r.get("cooldown", 120))),
                    })
                except Exception:
                    pass
        else:
            # 兼容旧单规则配置
            self.price_alert_rules = [{
                "period": max(1, int(price_alert_cfg.get("period", 60))),
                "threshold": max(0.1, float(price_alert_cfg.get("threshold", 2.0))),
                "cooldown": max(1, int(price_alert_cfg.get("cooldown", 120))),
            }]
        # 价格历史：{code: deque([(timestamp, price), ...])}
        self._price_history = {}
        # 冷却记录：{(code, rule_index): last_fire_timestamp}
        self._price_alert_cooldowns = {}

        # 新高新低报警配置
        nhl_cfg = cfg.get("new_high_low_alert", {}) or {}
        self.new_high_low_alert_enabled = bool(nhl_cfg.get("enabled", False))
        self.new_high_alert = bool(nhl_cfg.get("new_high", True))  # 新高报警开关
        self.new_low_alert = bool(nhl_cfg.get("new_low", True))   # 新低报警开关
        self.new_high_low_cooldown = max(1, int(nhl_cfg.get("cooldown", 60)))  # 冷却秒数
        # 状态追踪：{code: {"high": last_known_high, "low": last_known_low}}
        self._nhl_last_known = {}
        # 冷却记录：{(code, "high"/"low"): last_fire_timestamp}
        self._nhl_cooldowns = {}

        # 涨跌停通知配置
        limit_alert_cfg = cfg.get("limit_alert", {}) or {}
        self.limit_alert_enabled = bool(limit_alert_cfg.get("enabled", False))  # 全局开关
        self.limit_alert_reach_up = bool(limit_alert_cfg.get("reach_up", True))  # 到达涨停通知
        self.limit_alert_reach_down = bool(limit_alert_cfg.get("reach_down", True))  # 到达跌停通知
        self.limit_alert_leave_up = bool(limit_alert_cfg.get("leave_up", True))  # 离开涨停通知
        self.limit_alert_leave_down = bool(limit_alert_cfg.get("leave_down", True))  # 离开跌停通知
        self.limit_alert_cooldown = max(1, int(limit_alert_cfg.get("cooldown", 30)))  # 冷却秒数
        # 状态追踪：{code: {"is_limit_up": bool, "is_limit_down": bool}}
        self._limit_alert_state = {}
        # 冷却记录：{(code, "reach_up"/"reach_down"/"leave_up"/"leave_down"): last_fire_timestamp}
        self._limit_alert_cooldowns = {}

        # 设置初值
        self.codes = [str(c).strip() for c in codes_cfg if str(c).strip()]
        # 列标题列表（提前定义，供后续旧配置解析使用）
        self.ALL_HEADERS = ["代码", "名称", "现价", "涨跌值", "涨跌幅", "盈亏", "买一", "卖一", "委比", "成交量", "成交额", "均价", "日高", "日低", "K线"]

        # 列显示标志（独立属性）
        # 解析旧 flags 配置以做回退
        old_flags = {}
        if isinstance(flags_cfg, list):
            for i, h in enumerate(self.ALL_HEADERS):
                old_flags[h] = bool(flags_cfg[i]) if i < len(flags_cfg) else False
        elif isinstance(flags_cfg, dict):
            for h in self.ALL_HEADERS:
                old_flags[h] = bool(flags_cfg.get(h, False))

        # 新：为每一列创建独立的 bool 属性（优先读取新配置，否则回退到 old_flags）
        self.code_visible = bool(cfg.get("code_visible", old_flags.get("代码", False)))
        self.name_visible = bool(cfg.get("name_visible", old_flags.get("名称", False)))
        self.price_visible = bool(cfg.get("price_visible", old_flags.get("现价", False)))
        self.change_visible = bool(cfg.get("change_visible", old_flags.get("涨跌值", False)))
        self.change_pct_visible = bool(cfg.get("change_pct_visible", old_flags.get("涨跌幅", False)))
        # 买一/卖一 使用单一开关 b1s1_visible（用户要求不要拆分控制）
        self.b1s1_visible = bool(cfg.get("b1s1_visible", (old_flags.get("买一", False) or old_flags.get("卖一", False))))
        self.commi_visible = bool(cfg.get("commi_visible", old_flags.get("委比", False)))
        self.vol_visible = bool(cfg.get("vol_visible", old_flags.get("成交量", False)))
        self.amount_visible = bool(cfg.get("amount_visible", old_flags.get("成交额", False)))
        self.avg_visible = bool(cfg.get("avg_visible", old_flags.get("均价", False)))
        self.high_visible = bool(cfg.get("high_visible", old_flags.get("日高", False)))
        self.low_visible = bool(cfg.get("low_visible", old_flags.get("日低", False)))
        self.kline_visible = bool(cfg.get("kline_visible", old_flags.get("K线", False)))
        self.pnl_visible = bool(cfg.get("pnl_visible", False))

        # 简易模式列显示标志
        simple_cfg = cfg.get("simple_flags", {})
        self.simple_code_visible = bool(simple_cfg.get("代码", False))
        self.simple_name_visible = bool(simple_cfg.get("名称", True))
        self.simple_price_visible = bool(simple_cfg.get("现价", True))
        self.simple_change_visible = bool(simple_cfg.get("涨跌值", False))
        self.simple_change_pct_visible = bool(simple_cfg.get("涨跌幅", True))
        self.simple_b1s1_visible = bool(simple_cfg.get("买一", False))
        self.simple_commi_visible = bool(simple_cfg.get("委比", False))
        self.simple_vol_visible = bool(simple_cfg.get("成交量", False))
        self.simple_amount_visible = bool(simple_cfg.get("成交额", False))
        self.simple_avg_visible = bool(simple_cfg.get("均价", False))
        self.simple_high_visible = bool(simple_cfg.get("日高", False))
        self.simple_low_visible = bool(simple_cfg.get("日低", False))
        self.simple_kline_visible = bool(simple_cfg.get("K线", False))
        self.simple_pnl_visible = bool(simple_cfg.get("盈亏", False))

        # 设置自选显示股票（新名 checked_codes）
        self.codes = [str(c).strip() for c in codes_cfg if str(c).strip()]
        self.checked_codes = [str(c).strip() for c in checked_codes_cfg if (str(c).strip() and str(c).strip() in self.codes)]
        self.font = QFont(font_family, max(8, min(15, font_size)))
        self.bg = QColor(bg["r"],bg["g"],bg["b"],bg["a"])
        
        
        self.hotkey_triggered.connect(self.toggle_win)
        self._register_hotkey()

        # UI
        self.panel = QWidget(self)
        self.panel.setObjectName("panel")
        self.vbox = QVBoxLayout(self.panel)
        self.vbox.setContentsMargins(10,6,10,6)
        self.vbox.setSpacing(0)

        self.table = QTableView(self.panel)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setVisible(self.header_visible)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setFont(self.font)
        self.table.horizontalHeader().setFont(self.font)
        self.table.verticalHeader().setMinimumSectionSize(1)
        self.table.verticalHeader().setDefaultSectionSize(1)
        self.table.horizontalHeader().setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.table.setTextElideMode(Qt.ElideNone)
        self.error_label = QLabel("", self.panel)
        self.error_label.setStyleSheet("color: #ff6666; padding: 2px 4px;")
        self.error_label.setVisible(False)
        self.vbox.addWidget(self.error_label)

        self.model = SimpleTableModel(headers=self.ALL_HEADERS, align_right_cols=[1,2,3,4,5])
        self.model.set_color_scheme(self.fg, self.up_color, self.down_color)
        self.table.setModel(self.model)

        self.k_delegate = KLineDelegate(self.table, base_pt=12)
        self.k_delegate.update_scheme(self.fg, self.up_color, self.down_color)
        self.k_delegate.set_point_size(self.font.pointSize())
        self.k_column_visible_index = None

        self.vbox.addWidget(self.table)

        for w in (self.panel, self.table, self.table.viewport(), self.table.horizontalHeader(), self.table.verticalHeader()):
            w.installEventFilter(self)

        # 初始化期间禁用锚点重定位，避免在宽度尚未稳定时被错误修正位置
        self._anchor_active = False

        self.apply_style()
        self.set_window_opacity_percent(self.opacity_pct)
        self._fit_to_contents()

        scr = QApplication.primaryScreen().availableGeometry()
        pos = cfg.get("pos")
        # 待初始化结束、宽度稳定后再做屏幕钛制（避免 self.width() 不准导致 x 被错误拽回）
        self._pending_pos = None
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            x, y = int(pos["x"]), int(pos["y"])
            self.move(x, y)
            self._pending_pos = (x, y)
        else:
            self.move(scr.right()-self.width()-40, scr.bottom()-self.height()-80)

        self._drag_pos = None

        self.timer = QTimer(self)
        self.timer.setInterval(max(1, self.refresh_seconds)*1000)
        self.timer.timeout.connect(self._refresh_from_function)
        self.timer.start()
        self._refresh_from_function()
        self._defer_fit()

        # 初始化完成：启用锚点重定位（后续指标变化才会按锚点调整）
        self._anchor_active = True

        # 宽度稳定后才对加载的 pos 做屏幕钛制，确保窗口可见且不被错误拽回
        QTimer.singleShot(0, self._clamp_pending_pos)

        # 定时器周期性确保窗口置顶（跨平台，使用 Qt flags）
        self._keep_top_timer = QTimer(self)
        self._keep_top_timer.setInterval(1000)  # 每 1000ms 检查一次
        self._keep_top_timer.timeout.connect(self._ensure_on_top)
        self._keep_top_timer.start()

    def _screen_geometry_for(self, point: QPoint):
        """返回指定点所在屏幕的可用几何；若不在任何屏幕内，返回主屏可用几何。
        用于多显示器场景下正确保存/还原位置。"""
        try:
            s = QGuiApplication.screenAt(point)
            if s is not None:
                return s.availableGeometry()
        except Exception:
            pass
        return QApplication.primaryScreen().availableGeometry()

    def _clamp_pending_pos(self):
        """初始化完成后对加载的位置做屏幕钛制。此时 self.width()/height() 已稳定。"""
        pending = getattr(self, '_pending_pos', None)
        if not pending:
            return
        self._pending_pos = None
        x, y = pending
        try:
            scr = self._screen_geometry_for(QPoint(x, y))
            new_x = max(scr.left(), min(x, scr.right() - self.width()))
            new_y = max(scr.top(), min(y, scr.bottom() - self.height()))
            if (new_x, new_y) != (self.x(), self.y()):
                self.move(new_x, new_y)
        except Exception:
            pass

    # 与 App 连接
    def set_open_settings_callback(self, fn): 
        self._open_settings_cb = fn

    def set_on_change(self, fn): 
        self._on_change = fn or (lambda: None)

    def _notify_change(self):
        cb = getattr(self, "_on_change", None)
        if callable(cb): cb()

    def current_config(self):
        return {
            "codes": self.codes,
            "checked_codes": self.checked_codes,
            "code_visible": bool(getattr(self, 'code_visible', False)),
            "name_visible": bool(getattr(self, 'name_visible', False)),
            "price_visible": bool(getattr(self, 'price_visible', False)),
            "change_visible": bool(getattr(self, 'change_visible', False)),
            "change_pct_visible": bool(getattr(self, 'change_pct_visible', False)),
            "b1s1_visible": bool(getattr(self, 'b1s1_visible', False)),
            "commi_visible": bool(getattr(self, 'commi_visible', False)),
            "vol_visible": bool(getattr(self, 'vol_visible', False)),
            "amount_visible": bool(getattr(self, 'amount_visible', False)),
            "avg_visible": bool(getattr(self, 'avg_visible', False)),
            "high_visible": bool(getattr(self, 'high_visible', False)),
            "low_visible": bool(getattr(self, 'low_visible', False)),
            "kline_visible": bool(getattr(self, 'kline_visible', False)),
            "pnl_visible": bool(getattr(self, 'pnl_visible', False)),
            "cost_data": dict(getattr(self, 'cost_data', {}) or {}),
            "alert_data": dict(getattr(self, 'alert_data', {}) or {}),
            "short_code": self.short_code,
            "name_length": self.name_length,
            "b1s1_price": (getattr(self, 'b1s1_display', 'qty') == 'price'),
            "b1s1_display": getattr(self, 'b1s1_display', 'qty'),
            "header_visible": self.header_visible,
            "grid_visible": self.grid_visible,
            "refresh_seconds": self.refresh_seconds,
            "fg": self.fg.name(QColor.HexRgb),
            "bg": {"r": self.bg.red(), "g": self.bg.green(), "b": self.bg.blue(), "a": self.bg.alpha()},
            "opacity_pct": int(round(self.windowOpacity()*100)),
            "font_family": self.font.family(),
            "font_size": self.font.pointSize(),
            "line_extra_px": self.line_extra_px,
            "up_color": self.up_color.name(QColor.HexRgb),
            "down_color": self.down_color.name(QColor.HexRgb),
            "grid_alpha_pct": int(self.grid_alpha_pct),
            "header_alpha_pct": int(self.header_alpha_pct),
            "pos": {"x": self.x(), "y": self.y()},
            "hotkey": self.hotkey,
            "start_on_boot": bool(self.start_on_boot),
            "anchor": self.anchor,
            "sym_high": self.sym_high,
            "sym_low": self.sym_low,
            "sym_limit_up": self.sym_limit_up,
            "sym_limit_down": self.sym_limit_down,
            "sym_rise": self.sym_rise,
            "sym_fall": self.sym_fall,
            "dual_mode_enabled": bool(self.dual_mode_enabled),
            "leave_delay_ms": int(self.leave_delay_ms),
            "manual_mode": str(self.manual_mode),
            "simple_flags": {
                "代码": bool(self.simple_code_visible),
                "名称": bool(self.simple_name_visible),
                "现价": bool(self.simple_price_visible),
                "涨跌值": bool(self.simple_change_visible),
                "涨跌幅": bool(self.simple_change_pct_visible),
                "买一": bool(self.simple_b1s1_visible),
                "委比": bool(self.simple_commi_visible),
                "成交量": bool(self.simple_vol_visible),
                "成交额": bool(self.simple_amount_visible),
                "均价": bool(self.simple_avg_visible),
                "日高": bool(self.simple_high_visible),
                "日低": bool(self.simple_low_visible),
                "K线": bool(self.simple_kline_visible),
                "盈亏": bool(self.simple_pnl_visible),
            },
            "price_alert": {
                "enabled": bool(self.price_alert_enabled),
                "rules": list(self.price_alert_rules),
            },
            "new_high_low_alert": {
                "enabled": bool(self.new_high_low_alert_enabled),
                "new_high": bool(self.new_high_alert),
                "new_low": bool(self.new_low_alert),
                "cooldown": int(self.new_high_low_cooldown),
            },
            "limit_alert": {
                "enabled": bool(self.limit_alert_enabled),
                "reach_up": bool(self.limit_alert_reach_up),
                "reach_down": bool(self.limit_alert_reach_down),
                "leave_up": bool(self.limit_alert_leave_up),
                "leave_down": bool(self.limit_alert_leave_down),
                "cooldown": int(self.limit_alert_cooldown),
            },
        }

    def header_is_visible(self, header: str) -> bool:
        """返回指定列标题对应的独立可见属性值（替代旧的 flags 字典）。"""
        try:
            if header == "代码":
                return bool(getattr(self, 'code_visible', False))
            if header == "名称":
                return bool(getattr(self, 'name_visible', False))
            if header == "现价":
                return bool(getattr(self, 'price_visible', False))
            if header == "涨跌值":
                return bool(getattr(self, 'change_visible', False))
            if header == "涨跌幅":
                return bool(getattr(self, 'change_pct_visible', False))
            if header in ("买一", "卖一"):
                return bool(getattr(self, 'b1s1_visible', False))
            if header == "委比":
                return bool(getattr(self, 'commi_visible', False))
            if header == "成交量":
                return bool(getattr(self, 'vol_visible', False))
            if header == "成交额":
                return bool(getattr(self, 'amount_visible', False))
            if header == "均价":
                return bool(getattr(self, 'avg_visible', False))
            if header == "日高":
                return bool(getattr(self, 'high_visible', False))
            if header == "日低":
                return bool(getattr(self, 'low_visible', False))
            if header == "K线":
                return bool(getattr(self, 'kline_visible', False))
            if header == "盈亏":
                return bool(getattr(self, 'pnl_visible', False))
        except Exception:
            pass
        return False

    # ----- 双模式切换：活跃指标可见性 -----
    def _active_header_is_visible(self, header: str) -> bool:
        """根据当前双模式状态、鼠标悬浮状态及手动模式返回应当显示的列可见性。
        - dual_mode_enabled=True + 悬浮: 用正常模式
        - dual_mode_enabled=True + 未悬浮: 用简易模式
        - dual_mode_enabled=False: 由 manual_mode 决定（normal=正常模式, simple=简易模式）
        """
        if self.dual_mode_enabled:
            if self._is_hovered:
                return self.header_is_visible(header)
            # 自动模式下未悬浮 -> 简易模式
        else:
            # 手动模式
            if self.manual_mode != "simple":
                return self.header_is_visible(header)
        # 简易模式
        try:
            if header == "代码":
                return bool(self.simple_code_visible)
            if header == "名称":
                return bool(self.simple_name_visible)
            if header == "现价":
                return bool(self.simple_price_visible)
            if header == "涨跌值":
                return bool(self.simple_change_visible)
            if header == "涨跌幅":
                return bool(self.simple_change_pct_visible)
            if header in ("买一", "卖一"):
                return bool(self.simple_b1s1_visible)
            if header == "委比":
                return bool(self.simple_commi_visible)
            if header == "成交量":
                return bool(self.simple_vol_visible)
            if header == "成交额":
                return bool(self.simple_amount_visible)
            if header == "均价":
                return bool(self.simple_avg_visible)
            if header == "日高":
                return bool(self.simple_high_visible)
            if header == "日低":
                return bool(self.simple_low_visible)
            if header == "K线":
                return bool(self.simple_kline_visible)
            if header == "盈亏":
                return bool(self.simple_pnl_visible)
        except Exception:
            pass
        return False

    def enterEvent(self, event):
        """Mouse enters widget - switch to normal (full) mode if dual mode enabled."""
        super().enterEvent(event)
        if self.dual_mode_enabled:
            # 取消待执行的延迟切换
            if hasattr(self, '_leave_timer') and self._leave_timer.isActive():
                self._leave_timer.stop()
            if not self._is_hovered:
                self._is_hovered = True
                self._refresh_from_function()

    def leaveEvent(self, event):
        """Mouse leaves widget - delay 500ms before switching to simple mode."""
        super().leaveEvent(event)
        if self.dual_mode_enabled and self._is_hovered:
            if not hasattr(self, '_leave_timer'):
                self._leave_timer = QTimer(self)
                self._leave_timer.setSingleShot(True)
                self._leave_timer.timeout.connect(self._on_leave_timeout)
            self._leave_timer.start(max(0, self.leave_delay_ms))

    def _on_leave_timeout(self):
        """500ms后确认鼠标确实已离开，切换到简易模式。"""
        if self.dual_mode_enabled and self._is_hovered:
            self._is_hovered = False
            self._refresh_from_function()

    # ----- 外观/尺寸 -----
    def apply_style(self):
        r,g,b,a = self.bg.red(), self.bg.green(), self.bg.blue(), self.bg.alpha()
        fg_r, fg_g, fg_b = self.fg.red(), self.fg.green(), self.fg.blue()
        g_alpha = int(round(self.grid_alpha_pct * 2.55))
        h_alpha = int(round(self.header_alpha_pct * 2.55))
        line_col = f"rgba({fg_r},{fg_g},{fg_b},{g_alpha})"
        header_col = f"rgba({fg_r},{fg_g},{fg_b},{h_alpha})"
        self.panel.setStyleSheet(f"""
            QWidget#panel {{
                background: rgba({r},{g},{b},{a});
                border-radius: 5px;
            }}
            QTableView {{
                background: transparent;
                border: {f"1px solid {line_col}" if self.grid_visible else "none"};
                border-radius: 3px;
                outline: none;
            }}
            QTableView::item {{
                border-right: {f"1px solid {line_col}" if self.grid_visible else "none"};
                border-bottom: {f"1px solid {line_col}" if self.grid_visible else "none"};
            }}
            QHeaderView {{
                background-color: transparent;
            }}
            QHeaderView::section {{
                background: transparent;
                border: none;
                border-bottom: 1px solid {line_col};
                font-weight: 600;
                color: {header_col};
                padding: 0px 4px;
            }}
        """)
        self.table.setFont(self.font)
        self.table.horizontalHeader().setFont(self.font)
        self._defer_fit()

    def _apply_row_heights(self):
        fm = self.table.fontMetrics()
        h = fm.height() + max(0, self.line_extra_px)
        self.table.verticalHeader().setDefaultSectionSize(h)
        for r in range(self.model.rowCount()):
            self.table.setRowHeight(r, h)
        # 表头行高与数据行一致
        self.table.horizontalHeader().setFixedHeight(h)

    def _fit_to_contents(self):
        # 记录调整尺寸前的左右边界，用于按锚点重新定位
        old_left = self.x()
        old_right = self.x() + self.width()

        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.resizeColumnsToContents()
        self._apply_row_heights()

        cols = self.model.columnCount()
        rows = self.model.rowCount()
        total_w = self.table.verticalHeader().width() + 2*self.table.frameWidth()
        for c in range(cols): 
            total_w += self.table.columnWidth(c)
        hh = self.table.horizontalHeader().height() if self.table.horizontalHeader().isVisible() else 0
        total_h = hh + 2*self.table.frameWidth()
        for r in range(rows): 
            total_h += self.table.rowHeight(r)
        self.table.setFixedSize(max(1,total_w), max(1,total_h))
        self.panel.adjustSize()
        self.resize(self.panel.size())

        # 按锚点保持对齐：right 保持右边不变，left 保持左边不变（默认即不变）
        # 仅在初始化完成后生效，避免重启后位置还原被这里错误修正
        if not getattr(self, '_anchor_active', False):
            return
        anchor = getattr(self, 'anchor', 'left')
        if anchor == 'right':
            new_x = old_right - self.width()
            try:
                # 使用窗口当前所在屏幕的可用区域，避免多屏幕下被拽回主屏
                ref_point = QPoint(new_x + self.width() // 2, self.y() + self.height() // 2)
                scr = self._screen_geometry_for(ref_point)
                new_x = max(scr.left(), min(new_x, scr.right() - self.width()))
            except Exception:
                pass
            if new_x != self.x():
                self.move(new_x, self.y())

    def _defer_fit(self):
        QTimer.singleShot(0, self._fit_to_contents)

    # ----- 数据 & 投影 -----
    def _show_error(self, msg: str):
        try:
            if self.k_column_visible_index is not None:
                self.table.setItemDelegateForColumn(self.k_column_visible_index, QStyledItemDelegate(self.table))
                self.k_column_visible_index = None
        except Exception:
            pass
        try:
            text = str(msg) if msg is not None else ""
            # 若是 requests 抛出的网络错误，显示更友好的中文提示
            if isinstance(msg, Exception):
                import requests as _req
                if isinstance(msg, _req.exceptions.RequestException):
                    text = "无网络连接"
        except Exception:
            text = str(msg)

        if hasattr(self, 'error_label'):
            self.error_label.setText(text)
            self.error_label.setVisible(True)
        self._defer_fit()

    def _clear_error(self):
        # 清除顶部错误提示
        if hasattr(self, 'error_label'):
            try:
                self.error_label.setVisible(False)
                self.error_label.setText("")
            except Exception:
                pass

    # ----- 数据来源：新浪财经 -----
    def _get_price(self, codes:list):
        formatted_codes = []
        for c in codes:
            c_str = str(c).strip()
            if not c_str: 
                continue
            # 如果是期货，强制变成小写前缀 + 大写代码 (例如 nf_ + AU0)
            if c_str.lower().startswith(('nf_', 'hf_')):
                formatted_codes.append(c_str[:3].lower() + c_str[3:].upper())
            else:
                # 如果是A股，保持全小写
                formatted_codes.append(c_str.lower())
                
        label = ",".join(formatted_codes)
        # ==========================================

        if not label:
            raise Exception("暂无数据，请添加自选")

        price_data = []
        sign_data = []
        total_pnl = 0.0
        has_pnl = False
        url = 'https://hq.sinajs.cn/list=' + label
        headers = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=3)
        r.encoding = 'gbk'
        
        for line in r.text.split('\n'):
            if not line or '"' not in line:
                continue
            
            prefix_part = line.split('="')[0]
            parts = line.split('="')[1].split(',')
            
            # 判断是否为内盘期货 (nf_) 或 外盘期货 (hf_)
            is_nf_futures = "str_nf_" in prefix_part
            is_hf_futures = "str_hf_" in prefix_part
            # 【新增】：统一的一个期货标志位，方便后续使用
            is_any_futures = is_nf_futures or is_hf_futures
            
            if is_hf_futures:

                #print(f"👉 成功进入外盘期货(hf_)解析分支！")
                #print(f"👉 原始文本行: {line}")
                #print(f"👉 拆分后的数组 (长度 {len(parts)}): {parts}")
                #print("="*50 + "\n")

                if len(parts) < 14: 
                    continue
                code          = prefix_part.split('str_hf_')[-1]
                name          = parts[13]
                opening_price = float(parts[8] or 0)
                high_price    = float(parts[4] or 0)
                low_price     = float(parts[5] or 0)
                prev_close    = float(parts[7] or 0)
                current_price = float(parts[0] or 0)
                first_pur     = float(parts[2] or 0)
                first_sell    = float(parts[3] or 0)
                
                # 清洗最后一位的符号，防止转 float 报错
                vol_str       = parts[14].replace('"', '').replace(';', '')
                deals_vol     = float(vol_str or 0)
                
                deals_amt     = current_price * deals_vol 
                committee     = 0.0
                pur_vol       = int(parts[10] or 0) * 100 
                sel_vol       = int(parts[11] or 0) * 100
                purchaser     = [pur_vol] + [0]*9 
                pur_price     = [first_pur] + [0]*9
                seller        = [sel_vol] + [0]*9
                sel_price     = [first_sell] + [0]*9
                etf           = False

            elif is_nf_futures:

                if len(parts) < 14:
                    continue
                
                code          = prefix_part.split('str_nf_')[-1]
                name          = parts[0]
                opening_price = float(parts[2] or 0)
                high_price    = float(parts[3] or 0)
                low_price     = float(parts[4] or 0)
                
                # 【修复1】：昨收（昨结算）实际上在索引 10 的位置
                prev_close    = float(parts[10] or 0) 
                
                first_pur     = float(parts[6] or 0)
                first_sell    = float(parts[7] or 0)
                current_price = float(parts[8] or 0)
                deals_vol     = float(parts[14] or 0)
                
                # 【修复2】：为了让下面的通用代码能算出正确的均价(avg = amt/vol)，
                # 我们用 现价*成交量 倒推伪装一个“成交额”给它
                deals_amt = current_price * deals_vol 
                committee = 0.0
                
                # 期货本身就是手数，为了抵消下方 A 股的除以 100 逻辑，这里乘 100
                pur_vol = int(parts[11] or 0) * 100 
                sel_vol = int(parts[12] or 0) * 100
                purchaser = [pur_vol] + [0]*9 
                pur_price = [first_pur] + [0]*9
                seller    = [sel_vol] + [0]*9
                sel_price = [first_sell] + [0]*9
                etf = False

            else:
                if len(parts) < 30:
                    continue
                heads = prefix_part.split('_')
                code          = heads[2]
                name          = parts[0]
                opening_price = float(parts[1] or 0)   # 开盘
                prev_close    = float(parts[2] or 0)   # 昨收
                current_price = float(parts[3] or 0)   # 现价
                high_price    = float(parts[4] or 0)   # 当日最高
                low_price     = float(parts[5] or 0)   # 当日最低
                first_pur     = float(parts[6] or 0)   # 买一
                first_sell    = float(parts[7] or 0)   # 卖一
                deals_vol     = float(parts[8] or 0)   # 成交量
                deals_amt     = float(parts[9] or 0)   # 成交额
                purchaser     = [int(x or 0) for x in parts[10:19:2]]  
                pur_price     = [float(x or 0) for x in parts[11:20:2]]  
                seller        = [int(x or 0) for x in parts[20:29:2]]  
                sel_price     = [float(x or 0) for x in parts[21:30:2]]  
                etf = code[2] in ('1','5') if len(code)>2 else False

            # 构建买一/卖一数据及其颜色信息，并添加位置箭头
            b1_label = ""
            s1_label = ""
            b1_color_sign = 0  # 买一颜色：1红 0中性 -1绿
            s1_color_sign = 0  # 卖一颜色：1红 0中性 -1绿

            # 决定小数精度用于比较是否相等（避免浮点微小误差）
            dec = 3 if etf else 2
            def almost_eq(a, b):
                try:
                    return round(float(a), dec) == round(float(b), dec)
                except Exception:
                    return False

            # 标记：买一箭头位于右侧 '<'，卖一箭头位于左侧 '>'
            buy_marker = " "
            sell_marker = " "
            if first_pur > 0 and almost_eq(current_price, first_pur):
                buy_marker = "<"
            if first_sell > 0 and almost_eq(current_price, first_sell):
                sell_marker = ">"

            if first_pur == first_sell > 0:
                # 集合竞价：配对量 / 未配对量
                # 此处不显示成交方向箭头（竞价阶段无 <> 指示），且配对量和未配对量使用统一颜色规则
                current_price = first_sell  # 9:15 ~ 9:25; 14:57 ~ 15:00 竞价
                paired = seller[0]
                # unpaired_sign: >0 表示买方优势，<0 表示卖方优势
                unpaired_sign = -seller[1] if seller[1] > 0 else purchaser[1]
                # 显示数量（手）或价格或数量和价格（手数(价格)）
                paired_cnt = int(paired/100)
                unpaired_cnt = int(unpaired_sign/100)
                paired_fmt = self._fmt_lots(paired_cnt)
                unpaired_fmt = f"+{self._fmt_lots(unpaired_cnt)}" if unpaired_cnt >= 0 else f"-{self._fmt_lots(abs(unpaired_cnt))}"
                b_price = f"{first_pur:.3f}" if etf else f"{first_pur:.2f}"
                s_price = f"{first_sell:.3f}" if etf else f"{first_sell:.2f}"
                mode = getattr(self, 'b1s1_display', 'qty')
                if mode == 'price':
                    b1_label = f"{b_price}"
                    s1_label = f"{s_price}"
                elif mode == 'both':
                    b1_label = f"{paired_fmt}({b_price})"
                    s1_label = f"{unpaired_fmt}({s_price})"
                else:
                    b1_label = f"{paired_fmt}"
                    s1_label = f"{unpaired_fmt}"
                # 竞价颜色：根据未配对量的方向
                if unpaired_sign > 0:
                    b1_color_sign = 1
                    s1_color_sign = 1
                elif unpaired_sign < 0:
                    b1_color_sign = -1
                    s1_color_sign = -1
                else:
                    b1_color_sign = 0
                    s1_color_sign = 0
            else:
                # 连续竞价：买一数量/卖一数量
                if first_pur > 0:
                    cnt = self._fmt_lots(int(purchaser[0]/100))
                    b_price = f"{first_pur:.3f}" if etf else f"{first_pur:.2f}"
                    mode = getattr(self, 'b1s1_display', 'qty')
                    if mode == 'price':
                        b1_label = f"{b_price}{buy_marker}"
                    elif mode == 'both':
                        b1_label = f"{cnt}({b_price}){buy_marker}"
                    else:
                        b1_label = f"{cnt}{buy_marker}"
                else:
                    b1_label = f"-{buy_marker}"

                if first_sell > 0:
                    cnt = self._fmt_lots(int(seller[0]/100))
                    s_price = f"{first_sell:.3f}" if etf else f"{first_sell:.2f}"
                    mode = getattr(self, 'b1s1_display', 'qty')
                    if mode == 'price':
                        s1_label = f"{sell_marker}{s_price}"
                    elif mode == 'both':
                        s1_label = f"{sell_marker}{cnt}({s_price})"
                    else:
                        s1_label = f"{sell_marker}{cnt}"
                else:
                    s1_label = f"{sell_marker}-"

                # 连续竞价时：买一固定红色，卖一固定绿色
                b1_color_sign = 1
                s1_color_sign = -1
            
            if current_price == 0:
                current_price = prev_close # 9:00 ~ 9:15 无数据
            if opening_price == 0: 
                opening_price = current_price
                high_price = current_price
                low_price = current_price

            change = current_price - prev_close if prev_close else 0.0
            change_pct = (current_price / prev_close - 1) * 100 if prev_close else 0.0
            avg = (deals_amt / deals_vol) if deals_vol > 0 else prev_close # 均价
            p_sum, s_sum = sum(purchaser), sum(seller)
            committee = (100 * (p_sum - s_sum) / (p_sum + s_sum)) if (p_sum + s_sum) > 0 else 0.0 # 委比

            # 触及涨跌停或日高/低显示箭头（涨跌停优先）
            # 涨跌停价计算：创业板/科创板±20%，ST±5%，其余±10%
            limit_up = None
            limit_down = None
            if not etf and prev_close > 0:
                if "ST" in name or "st" in name:
                    limit_pct = 0.05
                elif code[2:5] in ('300','301','688'):
                    limit_pct = 0.20
                else:
                    limit_pct = 0.10
                limit_up = round(prev_close * (1 + limit_pct), dec)
                limit_down = round(prev_close * (1 - limit_pct), dec)

            arrow = " "
            if high_price > low_price:
                if limit_up is not None:
                    cur_rounded = round(current_price, dec)
                    if cur_rounded == limit_up:
                        arrow = self.sym_limit_up
                    elif cur_rounded == limit_down:
                        arrow = self.sym_limit_down
                    elif current_price == high_price:
                        arrow = self.sym_high
                    elif current_price == low_price:
                        arrow = self.sym_low
                else:
                    if current_price == high_price: arrow = self.sym_high
                    elif current_price == low_price: arrow = self.sym_low

            # 封单预警检测
            try:
                self._check_seal_alerts(code, name, current_price,
                                        first_pur, first_sell,
                                        purchaser[0], seller[0],
                                        limit_up, limit_down, dec)
            except Exception:
                pass

            # 涨跌异动报警检测
            try:
                self._check_price_alert(code, name, current_price, prev_close)
            except Exception:
                pass

            # 新高新低报警检测
            try:
                self._check_new_high_low_alert(code, name, current_price, high_price, low_price)
            except Exception:
                pass

            # 涨跌停通知检测
            try:
                self._check_limit_alert(code, name, current_price, limit_up, limit_down, dec)
            except Exception:
                pass

            k_payload = {"k": (opening_price, current_price, high_price, low_price, prev_close)}

            # 计算盈亏：(现价 - 成本) * 持仓数量
            cd = self.cost_data.get(code)
            if cd:
                pnl_val = (current_price - cd["cost"]) * cd["qty"]
                pnl_label = self._fmt_signed(pnl_val, 3 if etf else 2)
                pnl_sign = (pnl_val > 0) - (pnl_val < 0)
                total_pnl += pnl_val
                has_pnl = True
            else:
                pnl_label = ""
                pnl_sign = 0

            # 委比格式化
            commi_label = self._fmt_signed(committee, 2) + "%"
            display_code = code[2:] if not is_any_futures and self.short_code else code

            # "代码", "名称", "现价", "涨跌值", "涨跌幅", "盈亏", "买一", "卖一", "委比", "成交量", "成交额", "均价", "日高", "日低", "K线"
            if code[2] not in ('1','5'):
                chg_fmt = self._fmt_signed(change, 2)
                pct_fmt = self._fmt_signed(change_pct, 2) + "%"
                price_data.append([
                    code[2:] if self.short_code else code,
                    name if self.name_length == 0 else name[:self.name_length],
                    f"{arrow}{current_price:.2f}",
                    chg_fmt,
                    pct_fmt,
                    pnl_label,
                    b1_label,
                    s1_label,
                    commi_label,
                    f"{deals_vol}" if deals_vol<1e4 else (f"{deals_vol/1e4:.2f}万" if deals_vol<1e8 else f"{deals_vol/1e8:.2f}亿"),
                    f"{deals_amt/1e4:.2f}万" if deals_amt<1e8 else (f"{deals_amt/1e8:.2f}亿" if deals_amt<1e12 else f"{deals_amt/1e12:.2f}万亿"),
                    f"{avg:.2f}",
                    f"{high_price:.2f}",
                    f"{low_price:.2f}",
                    k_payload
                ])
            else:
                chg_fmt = self._fmt_signed(change, 3)
                pct_fmt = self._fmt_signed(change_pct, 2) + "%"
                price_data.append([
                    code[2:] if self.short_code else code,
                    name if self.name_length == 0 else name[:self.name_length],
                    f"{current_price:.3f}{arrow}",
                    chg_fmt,
                    pct_fmt,
                    pnl_label,
                    b1_label,
                    s1_label,
                    commi_label,
                    f"{deals_vol}" if deals_vol<1e4 else (f"{deals_vol/1e4:.2f}万" if deals_vol<1e8 else f"{deals_vol/1e8:.2f}亿"),
                    f"{deals_amt/1e4:.2f}万" if deals_amt<1e8 else (f"{deals_amt/1e8:.2f}亿" if deals_amt<1e12 else f"{deals_amt/1e12:.2f}万亿"),
                    f"{avg:.3f}",
                    f"{high_price:.3f}",
                    f"{low_price:.3f}",
                    k_payload
                ])
            sign_data.append({
                "delta": (change > 0) - (change < 0), 
                "commi": (committee > 0) - (committee < 0),
                "avg": (avg > prev_close) - (avg < prev_close),
                "b1": b1_color_sign,
                "s1": s1_color_sign,
                "pnl": pnl_sign,
                "high": (high_price > prev_close) - (high_price < prev_close) if prev_close else 0,
                "low": (low_price > prev_close) - (low_price < prev_close) if prev_close else 0,
            })
        
        return price_data, sign_data, total_pnl, has_pnl

    def _project_columns(self, full_rows, sign_data):
        # 从 ALL_HEADERS 中按显示顺序筛选已启用的列（使用双模式感知的可见性）
        cols = [i for i, h in enumerate(self.ALL_HEADERS) if self._active_header_is_visible(h)]
        headers = [self.ALL_HEADERS[i] for i in cols]

        proj_rows, proj_meta = [], []
        for r, row in enumerate(full_rows):
            proj_rows.append([row[i] for i in cols])
            proj_meta.append(sign_data[r])

        # 右对齐：除了名称、K线、卖一外的所有列都右对齐
        right_cols = [i for i, h in enumerate(headers) if h not in ("名称", "K线", "卖一")]
        self.model.set_align_right_cols(right_cols)
        self.model.set_rows_headers(proj_rows, headers, meta=proj_meta)
        self.model.set_color_scheme(self.fg, self.up_color, self.down_color)

        if "K线" in headers:
            col = headers.index("K线")
            self.k_column_visible_index = col
            self.k_delegate.update_scheme(self.fg, self.up_color, self.down_color)
            self.k_delegate.set_point_size(self.font.pointSize())
            self.table.setItemDelegateForColumn(col, self.k_delegate)
        else:
            if self.k_column_visible_index is not None:
                self.table.setItemDelegateForColumn(self.k_column_visible_index, QStyledItemDelegate(self.table))
                self.k_column_visible_index = None

        self._fit_to_contents()

    def _refresh_from_function(self):
        try:
            full_rows, sign, total_pnl, has_pnl = self._get_price(self.checked_codes)
        except Exception as e:
            try:
                import requests as _req
                if isinstance(e, _req.exceptions.RequestException):
                    self._show_error(_req.exceptions.RequestException())
                else:
                    self._show_error(str(e))
            except Exception:
                self._show_error(str(e))
            return

        try:
            self._clear_error()
        except Exception:
            pass
        self._project_columns(full_rows, sign)
        # 通知外部更新总盈亏指示（用于托盘图标红绿灯泡）
        try:
            if callable(self._pnl_callback):
                self._pnl_callback(float(total_pnl), bool(has_pnl))
        except Exception:
            pass
        # 构建托盘 ToolTip 指标文本（使用制表符分隔）
        # 始终使用正常模式可见列，不受双模式/简易模式影响
        try:
            if callable(self._tooltip_callback):
                cols_idx = [i for i, h in enumerate(self.ALL_HEADERS)
                            if self.header_is_visible(h) and h != "K线"]
                if cols_idx and full_rows:
                    headers_text = [self.ALL_HEADERS[i] for i in cols_idx]
                    lines = ["\t".join(headers_text)]
                    for row in full_rows:
                        cells = []
                        for i in cols_idx:
                            v = row[i] if i < len(row) else ""
                            cells.append("" if isinstance(v, dict) else str(v))
                        lines.append("\t".join(cells))
                    self._tooltip_callback("\n".join(lines))
                else:
                    self._tooltip_callback("")
        except Exception:
            pass

    # ----- 应用设置 -----
    def set_codes(self, codes_list):
        seen = set()
        new = []
        for c in codes_list:
            s = str(c).strip().lower()
            if s and s not in seen:
                seen.add(s)
                new.append(s)
        if not new: 
            new = ["sh000001"]
        self.codes = new
        # 清理已删除股票的成本数据
        if self.cost_data:
            keep = set(new)
            self.cost_data = {k: v for k, v in self.cost_data.items() if k in keep}
        # 清理已删除股票的封单预警数据
        if self.alert_data:
            keep = set(new)
            self.alert_data = {k: v for k, v in self.alert_data.items() if k in keep}
            self._alert_state = {k: v for k, v in self._alert_state.items() if k in keep}
        self._notify_change()
        self._refresh_from_function()

    def set_checked_codes(self, codes_list):
        seen = set()
        new = []
        for c in codes_list:
            s = str(c).strip().lower()
            if s and s not in seen:
                seen.add(s)
                new.append(s)
        if not new: 
            new = ["sh000001"]
        self.checked_codes = new
        self._notify_change()
        self._refresh_from_function()

    def set_flag(self, idx, checked: bool):
        """设置指标显示标志。idx 可以是整数索引（向后兼容）或列标题字符串"""
        # 兼容老版本：若传整数索引，转为列标题
        if isinstance(idx, int):
            if 0 <= idx < len(self.ALL_HEADERS):
                header = self.ALL_HEADERS[idx]
            else:
                return
        else:
            header = str(idx)
            if header not in self.ALL_HEADERS:
                return
        
        checked = bool(checked)
        prev = None
        try:
            if header == "代码":
                prev = bool(getattr(self, 'code_visible', False)); self.code_visible = checked
            elif header == "名称":
                prev = bool(getattr(self, 'name_visible', False)); self.name_visible = checked
            elif header == "现价":
                prev = bool(getattr(self, 'price_visible', False)); self.price_visible = checked
            elif header == "涨跌值":
                prev = bool(getattr(self, 'change_visible', False)); self.change_visible = checked
            elif header == "涨跌幅":
                prev = bool(getattr(self, 'change_pct_visible', False)); self.change_pct_visible = checked
            elif header in ("买一", "卖一"):
                prev = bool(getattr(self, 'b1s1_visible', False)); self.b1s1_visible = checked
            elif header == "委比":
                prev = bool(getattr(self, 'commi_visible', False)); self.commi_visible = checked
            elif header == "成交量":
                prev = bool(getattr(self, 'vol_visible', False)); self.vol_visible = checked
            elif header == "成交额":
                prev = bool(getattr(self, 'amount_visible', False)); self.amount_visible = checked
            elif header == "均价":
                prev = bool(getattr(self, 'avg_visible', False)); self.avg_visible = checked
            elif header == "日高":
                prev = bool(getattr(self, 'high_visible', False)); self.high_visible = checked
            elif header == "日低":
                prev = bool(getattr(self, 'low_visible', False)); self.low_visible = checked
            elif header == "K线":
                prev = bool(getattr(self, 'kline_visible', False)); self.kline_visible = checked
            elif header == "盈亏":
                prev = bool(getattr(self, 'pnl_visible', False)); self.pnl_visible = checked
        except Exception:
            prev = None

        if prev is None or prev == checked:
            # 如果状态没有变化仍然返回（避免额外刷新）
            if prev == checked:
                return
        self._notify_change()
        self._refresh_from_function()

    def set_code_type(self, pure_num: bool):
        self.short_code = bool(pure_num)
        self._notify_change()
        self._refresh_from_function()

    def set_name_length(self, name_len: int):
        if name_len >=0:
            self.name_length = name_len
            self._notify_change()
            self._refresh_from_function()

    def set_b1s1_display(self, mode: str):
        """mode: 'qty' | 'price' | 'both'"""
        if mode not in ("qty", "price", "both"):
            return
        self.b1s1_display = mode
        self._notify_change()
        self._refresh_from_function()

    def set_header_visible(self, vis: bool):
        self.header_visible = bool(vis)
        self.table.horizontalHeader().setVisible(self.header_visible)
        self._notify_change()
        self._defer_fit()

    def set_symbols(self, sym_high: str, sym_low: str, sym_limit_up: str, sym_limit_down: str,
                    sym_rise: str = None, sym_fall: str = None):
        """设置日高/日低/涨停/跌停/涨/跌符号"""
        self.sym_high = sym_high or "↑"
        self.sym_low = sym_low or "↓"
        self.sym_limit_up = sym_limit_up or "⇧"
        self.sym_limit_down = sym_limit_down or "⇩"
        if sym_rise is not None:
            self.sym_rise = sym_rise
        if sym_fall is not None:
            self.sym_fall = sym_fall
        self._notify_change()
        self._refresh_from_function()

    def _fmt_signed(self, value: float, decimals: int) -> str:
        """使用涨/跌符号格式化带符号数值。
        正值前缀 sym_rise，负值前缀 sym_fall，零值显示 sym_rise+0。"""
        if value > 0:
            return f"{self.sym_rise}{value:.{decimals}f}"
        elif value < 0:
            return f"{self.sym_fall}{abs(value):.{decimals}f}"
        else:
            return f"{self.sym_rise}{0:.{decimals}f}"

    @staticmethod
    def _fmt_lots(lots: int) -> str:
        """格式化手数：>=1亿显示X.X亿，>=1万显示X.X万，否则原数字。"""
        abs_lots = abs(lots)
        if abs_lots >= 100000000:
            return f"{lots/1e8:.1f}亿"
        elif abs_lots >= 10000:
            return f"{lots/1e4:.1f}万"
        else:
            return f"{lots}"

    def set_cost(self, code: str, cost: float, qty: int):
        """设置指定股票的持仓成本与数量。cost<=0 或 qty==0 时清除。"""
        try:
            key = str(code).strip().lower()
            if not key:
                return
            try:
                cost_f = float(cost)
            except Exception:
                cost_f = 0.0
            try:
                qty_i = int(qty)
            except Exception:
                qty_i = 0
            if cost_f > 0 and qty_i != 0:
                self.cost_data[key] = {"cost": cost_f, "qty": qty_i}
                # 首次设置成本时自动启用盈亏列显示
                if not getattr(self, 'pnl_visible', False):
                    self.pnl_visible = True
            else:
                self.cost_data.pop(key, None)
            self._notify_change()
            self._refresh_from_function()
        except Exception:
            pass

    def get_cost(self, code: str):
        """返回指定股票的成本数据 dict 或 None。"""
        try:
            return self.cost_data.get(str(code).strip().lower())
        except Exception:
            return None

    def set_notifier_callback(self, fn):
        """设置预警通知回调 fn(title, msg)。"""
        self._notify_alert = fn

    def set_pnl_callback(self, fn):
        """设置总盈亏更新回调 fn(total_pnl: float, has_pnl: bool)。"""
        self._pnl_callback = fn

    def set_tooltip_callback(self, fn):
        """设置托盘 ToolTip 指标文本更新回调 fn(text: str)。"""
        self._tooltip_callback = fn

    def set_alert(self, code: str, thresholds: list):
        """设置指定股票的封单预警阈值列表（手数，正=涨停，负=跌停）。"""
        try:
            key = str(code).strip().lower()
            if not key:
                return
            cleaned = []
            for t in thresholds or []:
                try:
                    n = int(t)
                    if n != 0 and n not in cleaned:
                        cleaned.append(n)
                except Exception:
                    pass
            if cleaned:
                self.alert_data[key] = cleaned
                self._alert_state[key] = [False] * len(cleaned)
            else:
                self.alert_data.pop(key, None)
                self._alert_state.pop(key, None)
            self._notify_change()
        except Exception:
            pass

    def get_alert(self, code: str):
        """返回指定股票的预警阈值列表。"""
        try:
            return list(self.alert_data.get(str(code).strip().lower(), []))
        except Exception:
            return []

    def _fire_alert(self, title: str, msg: str):
        cb = getattr(self, '_notify_alert', None)
        if callable(cb):
            try:
                cb(title, msg)
            except Exception:
                pass

    def _check_seal_alerts(self, code, name, current_price, b1_price, s1_price,
                           b1_qty, s1_qty, limit_up, limit_down, dec):
        """封单预警状态机检测。进入涨/跌停且封单达阈值进入生效状态；
        封单跌破阈值或打开涨/跌停时触发通知并进入失效状态。"""
        key = (code or "").strip().lower()
        thresholds = self.alert_data.get(key)
        if not thresholds:
            return
        state = self._alert_state.get(key)
        if not state or len(state) != len(thresholds):
            state = [False] * len(thresholds)
            self._alert_state[key] = state

        is_limit_up = (limit_up is not None and
                       round(current_price, dec) == limit_up and
                       b1_price > 0 and round(b1_price, dec) == limit_up)
        is_limit_down = (limit_down is not None and
                         round(current_price, dec) == limit_down and
                         s1_price > 0 and round(s1_price, dec) == limit_down)

        seal_up_lots = int(b1_qty / 100) if is_limit_up else 0
        seal_down_lots = int(s1_qty / 100) if is_limit_down else 0

        for i, t in enumerate(thresholds):
            if t > 0:
                # 涨停预警
                if not state[i]:
                    if is_limit_up and seal_up_lots >= t:
                        state[i] = True
                else:
                    if not is_limit_up or seal_up_lots < t:
                        state[i] = False
                        if not is_limit_up:
                            title = f"{name} 打开涨停"
                            msg = f"{code} 预警阈值 {t}手：已脱离涨停"
                        else:
                            title = f"{name} 涨停封单跌破 {t}手"
                            msg = f"{code} 当前封单 {seal_up_lots}手 < {t}手"
                        self._fire_alert(title, msg)
            elif t < 0:
                # 跌停预警：阈值以绝对值比较
                req = -t
                if not state[i]:
                    if is_limit_down and seal_down_lots >= req:
                        state[i] = True
                else:
                    if not is_limit_down or seal_down_lots < req:
                        state[i] = False
                        if not is_limit_down:
                            title = f"{name} 打开跌停"
                            msg = f"{code} 预警阈值 {t}手：已脱离跌停"
                        else:
                            title = f"{name} 跌停封单跌破 {req}手"
                            msg = f"{code} 当前封单 {seal_down_lots}手 < {req}手"
                        self._fire_alert(title, msg)

    def _check_price_alert(self, code, name, current_price, prev_close):
        """涨跌异动报警：对每条规则独立检测，在配置的周期内若价格波动超过阈值则发出通知。"""
        if not self.price_alert_enabled:
            return
        if current_price <= 0 or prev_close <= 0:
            return
        if not self.price_alert_rules:
            return

        key = (code or "").strip().lower()
        now = time.time()

        # 记录价格历史（统一维护，保留最大周期所需数据）
        if key not in self._price_history:
            self._price_history[key] = deque()

        history = self._price_history[key]
        history.append((now, current_price))

        # 清除超出所有规则最大周期的老数据
        max_period = max(r["period"] for r in self.price_alert_rules)
        cutoff = now - max_period
        while history and history[0][0] < cutoff:
            history.popleft()

        # 对每条规则独立检测
        for rule_idx, rule in enumerate(self.price_alert_rules):
            period = rule["period"]
            threshold = rule["threshold"]
            cooldown = rule["cooldown"]

            # 找到该规则周期内最早的价格
            rule_cutoff = now - period
            base_price = None
            for ts, price in history:
                if ts >= rule_cutoff:
                    base_price = price
                    break

            if base_price is None or base_price <= 0:
                continue

            # 需要至少有两个数据点
            if base_price == current_price:
                continue

            # 计算周期内涨跌幅
            change_pct = abs((current_price - base_price) / base_price) * 100

            if change_pct >= threshold:
                # 检查冷却
                cd_key = (key, rule_idx)
                last_fired = self._price_alert_cooldowns.get(cd_key, 0)
                if now - last_fired < cooldown:
                    continue

                # 触发报警
                self._price_alert_cooldowns[cd_key] = now
                direction = "涨" if current_price > base_price else "跌"
                actual_pct = (current_price - base_price) / base_price * 100
                title = f"{name} 涨跌异动"
                msg = (f"{code} {period}秒内"
                       f"{direction}{abs(actual_pct):.2f}%"
                       f"（{base_price:.2f}→{current_price:.2f}）")
                self._fire_alert(title, msg)

    def _check_new_high_low_alert(self, code, name, current_price, high_price, low_price):
        """新高新低报警：当日最高价创新高或最低价创新低时发出通知。"""
        if not self.new_high_low_alert_enabled:
            return
        if current_price <= 0 or high_price <= 0 or low_price <= 0:
            return
        if high_price <= low_price:
            return  # 无效数据（还未交易）

        key = (code or "").strip().lower()
        now = time.time()

        prev = self._nhl_last_known.get(key)
        if prev is None:
            # 首次记录，不触发报警
            self._nhl_last_known[key] = {"high": high_price, "low": low_price}
            return

        prev_high = prev["high"]
        prev_low = prev["low"]

        # 检测新高
        if self.new_high_alert and high_price > prev_high:
            cd_key = (key, "high")
            last_fired = self._nhl_cooldowns.get(cd_key, 0)
            if now - last_fired >= self.new_high_low_cooldown:
                self._nhl_cooldowns[cd_key] = now
                title = f"{name} 创新高"
                msg = f"{code} 当日新高 {high_price:.2f}（前高 {prev_high:.2f}）"
                self._fire_alert(title, msg)

        # 检测新低
        if self.new_low_alert and low_price < prev_low:
            cd_key = (key, "low")
            last_fired = self._nhl_cooldowns.get(cd_key, 0)
            if now - last_fired >= self.new_high_low_cooldown:
                self._nhl_cooldowns[cd_key] = now
                title = f"{name} 创新低"
                msg = f"{code} 当日新低 {low_price:.2f}（前低 {prev_low:.2f}）"
                self._fire_alert(title, msg)

        # 更新记录
        self._nhl_last_known[key] = {"high": high_price, "low": low_price}

    def _check_limit_alert(self, code, name, current_price, limit_up, limit_down, dec):
        """涨跌停通知：到达涨跌停或离开涨跌停时发出通知。"""
        if not self.limit_alert_enabled:
            return
        if current_price <= 0:
            return
        if limit_up is None and limit_down is None:
            return

        key = (code or "").strip().lower()
        now = time.time()
        cur_rounded = round(current_price, dec)

        # 当前涨跌停状态
        is_limit_up = (limit_up is not None and cur_rounded == limit_up)
        is_limit_down = (limit_down is not None and cur_rounded == limit_down)

        prev = self._limit_alert_state.get(key)
        if prev is None:
            # 首次记录，不触发报警
            self._limit_alert_state[key] = {"is_limit_up": is_limit_up, "is_limit_down": is_limit_down}
            return

        prev_up = prev["is_limit_up"]
        prev_down = prev["is_limit_down"]

        # 检测到达涨停
        if self.limit_alert_reach_up and is_limit_up and not prev_up:
            cd_key = (key, "reach_up")
            last_fired = self._limit_alert_cooldowns.get(cd_key, 0)
            if now - last_fired >= self.limit_alert_cooldown:
                self._limit_alert_cooldowns[cd_key] = now
                title = f"{name} 到达涨停"
                msg = f"{code} 当前价 {current_price:.{dec}f} 触及涨停价 {limit_up:.{dec}f}"
                self._fire_alert(title, msg)

        # 检测到达跌停
        if self.limit_alert_reach_down and is_limit_down and not prev_down:
            cd_key = (key, "reach_down")
            last_fired = self._limit_alert_cooldowns.get(cd_key, 0)
            if now - last_fired >= self.limit_alert_cooldown:
                self._limit_alert_cooldowns[cd_key] = now
                title = f"{name} 到达跌停"
                msg = f"{code} 当前价 {current_price:.{dec}f} 触及跌停价 {limit_down:.{dec}f}"
                self._fire_alert(title, msg)

        # 检测离开涨停
        if self.limit_alert_leave_up and not is_limit_up and prev_up:
            cd_key = (key, "leave_up")
            last_fired = self._limit_alert_cooldowns.get(cd_key, 0)
            if now - last_fired >= self.limit_alert_cooldown:
                self._limit_alert_cooldowns[cd_key] = now
                title = f"{name} 离开涨停"
                msg = f"{code} 当前价 {current_price:.{dec}f} 已离开涨停价 {limit_up:.{dec}f}"
                self._fire_alert(title, msg)

        # 检测离开跌停
        if self.limit_alert_leave_down and not is_limit_down and prev_down:
            cd_key = (key, "leave_down")
            last_fired = self._limit_alert_cooldowns.get(cd_key, 0)
            if now - last_fired >= self.limit_alert_cooldown:
                self._limit_alert_cooldowns[cd_key] = now
                title = f"{name} 离开跌停"
                msg = f"{code} 当前价 {current_price:.{dec}f} 已离开跌停价 {limit_down:.{dec}f}"
                self._fire_alert(title, msg)

        # 更新状态
        self._limit_alert_state[key] = {"is_limit_up": is_limit_up, "is_limit_down": is_limit_down}

    def set_grid_visible(self, vis: bool):
        self.grid_visible = bool(vis)
        self.apply_style()
        self._notify_change()

    def set_refresh_interval(self, seconds: int):
        if seconds in {1,2,3,5,10,15,30,60}:
            self.refresh_seconds = seconds
            self.timer.setInterval(seconds*1000)
            self._notify_change()

    def set_fg_color(self, c: QColor):
        if isinstance(c, QColor) and c.isValid():
            self.fg = QColor(c)
            self.model.set_color_scheme(self.fg, self.up_color, self.down_color)
            self.k_delegate.update_scheme(self.fg, self.up_color, self.down_color)
            self.apply_style()
            self._notify_change()
            self._defer_fit()

    def set_up_color(self, c: QColor):
        if isinstance(c, QColor) and c.isValid():
            self.up_color = QColor(c)
            self.model.set_color_scheme(self.fg, self.up_color, self.down_color)
            self.k_delegate.update_scheme(self.fg, self.up_color, self.down_color)
            self.apply_style()
            self._notify_change()
            self._defer_fit()

    def set_down_color(self, c: QColor):
        if isinstance(c, QColor) and c.isValid():
            self.down_color = QColor(c)
            self.model.set_color_scheme(self.fg, self.up_color, self.down_color)
            self.k_delegate.update_scheme(self.fg, self.up_color, self.down_color)
            self.apply_style()
            self._notify_change()
            self._defer_fit()

    def reset_default_colors(self):
        """恢复涨/跌/表格颜色为默认值。"""
        self.up_color = QColor(DEFAULT_UP_COLOR)
        self.down_color = QColor(DEFAULT_DOWN_COLOR)
        self.fg = QColor(DEFAULT_TABLE_COLOR)
        self.model.set_color_scheme(self.fg, self.up_color, self.down_color)
        self.k_delegate.update_scheme(self.fg, self.up_color, self.down_color)
        self.apply_style()
        self._notify_change()
        self._defer_fit()

    def set_bg_rgb_keep_alpha(self, c: QColor):
        if isinstance(c, QColor) and c.isValid():
            c2 = QColor(c)
            c2.setAlpha(self.bg.alpha())
            self.bg = c2
            self.apply_style()
            self._notify_change()

    def set_bg_alpha_percent(self, percent_0_100: int):
        p = max(0, min(100, int(percent_0_100)))
        self.bg.setAlpha(int(round(p*2.55)))
        self.apply_style()
        self._notify_change()

    def set_window_opacity_percent(self, percent_20_100: int):
        p = max(20, min(100, int(percent_20_100)))
        self.setWindowOpacity(p/100.0)
        self._defer_fit()
        self._notify_change()

    def set_grid_alpha_percent(self, percent_0_100: int):
        """表格线/表头底边线的不透明度（0-100%）。"""
        self.grid_alpha_pct = max(0, min(100, int(percent_0_100)))
        self.apply_style()
        self._notify_change()

    def set_header_alpha_percent(self, percent_0_100: int):
        """表头文字的不透明度（0-100%）。"""
        self.header_alpha_pct = max(0, min(100, int(percent_0_100)))
        self.apply_style()
        self._notify_change()

    def set_font_size(self, pt: int):
        pt = max(MIN_FONT_SIZE, min(15, int(pt)))
        self.font.setPointSize(pt)
        self.k_delegate.set_point_size(pt)
        self.apply_style()
        self._notify_change()
        self.table.viewport().update()
        self._defer_fit()

    def set_font_family(self, family: str):
        if family and family != self.font.family():
            self.font.setFamily(family)
            self.apply_style()
            self._notify_change()

    def set_line_extra(self, px: int):
        self.line_extra_px = max(0, int(px))
        self.apply_style()
        self._defer_fit()
        self._notify_change()

    def set_start_on_boot(self, enabled: bool):
        self.start_on_boot = bool(enabled)
        self._notify_change()

    def set_anchor(self, anchor: str):
        """设置窗口锚点：'left' 保持左边对齐，'right' 保持右边对齐。
        切换时以当前窗口位置作为新锚点的基准，不立即移动窗口。"""
        if anchor not in ("left", "right"):
            return
        if anchor == self.anchor:
            return
        self.anchor = anchor
        self._notify_change()

    def set_dual_mode_enabled(self, enabled: bool):
        """启用或禁用双模式切换。"""
        self.dual_mode_enabled = bool(enabled)
        self._notify_change()
        self._refresh_from_function()

    def set_manual_mode(self, mode: str):
        """设置手动显示模式（仅当双模式自动切换关闭时生效）。
        mode: "normal" 或 "simple"。
        """
        mode = str(mode).lower()
        if mode not in ("normal", "simple"):
            return
        if mode == self.manual_mode:
            return
        self.manual_mode = mode
        self._notify_change()
        # 仅在自动切换关闭时立即刷新视图
        if not self.dual_mode_enabled:
            self._refresh_from_function()

    def set_leave_delay_ms(self, ms: int):
        """设置鼠标离开后切换简易模式的延迟时间(ms)。"""
        self.leave_delay_ms = max(0, int(ms))
        self._notify_change()

    def set_simple_flag(self, header: str, checked: bool):
        """设置简易模式下指定列的可见性。"""
        checked = bool(checked)
        if header == "代码":
            self.simple_code_visible = checked
        elif header == "名称":
            self.simple_name_visible = checked
        elif header == "现价":
            self.simple_price_visible = checked
        elif header == "涨跌值":
            self.simple_change_visible = checked
        elif header == "涨跌幅":
            self.simple_change_pct_visible = checked
        elif header in ("买一", "卖一"):
            self.simple_b1s1_visible = checked
        elif header == "委比":
            self.simple_commi_visible = checked
        elif header == "成交量":
            self.simple_vol_visible = checked
        elif header == "成交额":
            self.simple_amount_visible = checked
        elif header == "均价":
            self.simple_avg_visible = checked
        elif header == "日高":
            self.simple_high_visible = checked
        elif header == "日低":
            self.simple_low_visible = checked
        elif header == "K线":
            self.simple_kline_visible = checked
        elif header == "盈亏":
            self.simple_pnl_visible = checked
        else:
            return
        self._notify_change()
        self._refresh_from_function()

    def simple_header_is_visible(self, header: str) -> bool:
        """返回简易模式下指定列的可见性。"""
        try:
            if header == "代码":
                return bool(self.simple_code_visible)
            if header == "名称":
                return bool(self.simple_name_visible)
            if header == "现价":
                return bool(self.simple_price_visible)
            if header == "涨跌值":
                return bool(self.simple_change_visible)
            if header == "涨跌幅":
                return bool(self.simple_change_pct_visible)
            if header in ("买一", "卖一"):
                return bool(self.simple_b1s1_visible)
            if header == "委比":
                return bool(self.simple_commi_visible)
            if header == "成交量":
                return bool(self.simple_vol_visible)
            if header == "成交额":
                return bool(self.simple_amount_visible)
            if header == "均价":
                return bool(self.simple_avg_visible)
            if header == "日高":
                return bool(self.simple_high_visible)
            if header == "日低":
                return bool(self.simple_low_visible)
            if header == "K线":
                return bool(self.simple_kline_visible)
            if header == "盈亏":
                return bool(self.simple_pnl_visible)
        except Exception:
            pass
        return False

    # ----- 涨跌异动报警设置 -----
    def set_price_alert_enabled(self, enabled: bool):
        """启用/禁用涨跌异动报警。"""
        self.price_alert_enabled = bool(enabled)
        if not enabled:
            # 禁用时清空历史数据
            self._price_history.clear()
            self._price_alert_cooldowns.clear()
        self._notify_change()

    def set_price_alert_rules(self, rules: list):
        """设置涨跌异动报警规则列表。"""
        self.price_alert_rules = []
        for r in (rules or []):
            try:
                self.price_alert_rules.append({
                    "period": max(1, int(r.get("period", 60))),
                    "threshold": max(0.1, float(r.get("threshold", 2.0))),
                    "cooldown": max(1, int(r.get("cooldown", 120))),
                })
            except Exception:
                pass
        # 规则变化时清空历史和冷却状态
        self._price_history.clear()
        self._price_alert_cooldowns.clear()
        self._notify_change()

    def add_price_alert_rule(self, period: int, threshold: float, cooldown: int):
        """添加一条涨跌异动报警规则。"""
        self.price_alert_rules.append({
            "period": max(1, int(period)),
            "threshold": max(0.1, float(threshold)),
            "cooldown": max(1, int(cooldown)),
        })
        self._price_history.clear()
        self._price_alert_cooldowns.clear()
        self._notify_change()

    def remove_price_alert_rule(self, index: int):
        """删除指定索引的报警规则。"""
        if 0 <= index < len(self.price_alert_rules):
            self.price_alert_rules.pop(index)
            self._price_history.clear()
            self._price_alert_cooldowns.clear()
            self._notify_change()

    # ----- 新高新低报警设置 -----
    def set_new_high_low_alert_enabled(self, enabled: bool):
        """启用/禁用新高新低报警。"""
        self.new_high_low_alert_enabled = bool(enabled)
        if not enabled:
            self._nhl_last_known.clear()
            self._nhl_cooldowns.clear()
        self._notify_change()

    def set_new_high_alert(self, enabled: bool):
        """启用/禁用新高报警。"""
        self.new_high_alert = bool(enabled)
        self._notify_change()

    def set_new_low_alert(self, enabled: bool):
        """启用/禁用新低报警。"""
        self.new_low_alert = bool(enabled)
        self._notify_change()

    def set_new_high_low_cooldown(self, seconds: int):
        """设置新高新低报警冷却时间（秒）。"""
        self.new_high_low_cooldown = max(1, int(seconds))
        self._nhl_cooldowns.clear()
        self._notify_change()

    # ----- 涨跌停通知设置 -----
    def set_limit_alert_enabled(self, enabled: bool):
        """启用/禁用涨跌停通知。"""
        self.limit_alert_enabled = bool(enabled)
        if not enabled:
            self._limit_alert_state.clear()
            self._limit_alert_cooldowns.clear()
        self._notify_change()

    def set_limit_alert_reach_up(self, enabled: bool):
        """启用/禁用到达涨停通知。"""
        self.limit_alert_reach_up = bool(enabled)
        self._notify_change()

    def set_limit_alert_reach_down(self, enabled: bool):
        """启用/禁用到达跌停通知。"""
        self.limit_alert_reach_down = bool(enabled)
        self._notify_change()

    def set_limit_alert_leave_up(self, enabled: bool):
        """启用/禁用离开涨停通知。"""
        self.limit_alert_leave_up = bool(enabled)
        self._notify_change()

    def set_limit_alert_leave_down(self, enabled: bool):
        """启用/禁用离开跌停通知。"""
        self.limit_alert_leave_down = bool(enabled)
        self._notify_change()

    def set_limit_alert_cooldown(self, seconds: int):
        """设置涨跌停通知冷却时间（秒）。"""
        self.limit_alert_cooldown = max(1, int(seconds))
        self._limit_alert_cooldowns.clear()
        self._notify_change()

    # ----- 交互 -----
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        sub_cols = QMenu("显示指标", menu)
        for name in self.ALL_HEADERS:
            if name == "卖一":
                continue
            if name == "买一":
                act = QAction("买一/卖一", sub_cols, checkable=True)
                act.setChecked(self.header_is_visible("买一"))
                act.toggled.connect(partial(self.set_flag, "买一"))
                sub_cols.addAction(act)
                continue
            act = QAction(name, sub_cols, checkable=True)
            act.setChecked(self.header_is_visible(name))
            act.toggled.connect(partial(self.set_flag, name))
            sub_cols.addAction(act)
        menu.addMenu(sub_cols)

        act_header = QAction("显示表头", menu, checkable=True)
        act_header.setChecked(self.header_visible)
        act_header.toggled.connect(self.set_header_visible)
        menu.addAction(act_header)

        act_grid = QAction("显示网格",menu, checkable=True)
        act_grid.setChecked(self.grid_visible)
        act_grid.toggled.connect(self.set_grid_visible)
        menu.addAction(act_grid)

        act_dual = QAction("双模式切换", menu, checkable=True)
        act_dual.setChecked(self.dual_mode_enabled)
        act_dual.toggled.connect(self.set_dual_mode_enabled)
        menu.addAction(act_dual)

        # 手动模式选择：仅当双模式自动切换关闭时可用
        sub_mode = QMenu("当前显示模式", menu)
        sub_mode.setEnabled(not self.dual_mode_enabled)
        act_mode_normal = QAction("正常模式", sub_mode, checkable=True)
        act_mode_normal.setChecked(self.manual_mode == "normal")
        act_mode_normal.triggered.connect(lambda: self.set_manual_mode("normal"))
        sub_mode.addAction(act_mode_normal)
        act_mode_simple = QAction("简易模式", sub_mode, checkable=True)
        act_mode_simple.setChecked(self.manual_mode == "simple")
        act_mode_simple.triggered.connect(lambda: self.set_manual_mode("simple"))
        sub_mode.addAction(act_mode_simple)
        menu.addMenu(sub_mode)

        menu.addSeparator()
        act_open_settings = QAction("设置…", menu)
        act_open_settings.triggered.connect(self._open_settings_cb)
        menu.addAction(act_open_settings)

        menu.addSeparator()
        menu.addAction(QAction("隐藏浮窗", menu, triggered=self.hide))
        menu.exec(event.globalPos())

    def _pause_refresh(self):
        """拖动开始时暂停数据刷新，避免网络请求+重绘导致卡顿"""
        if self.timer and self.timer.isActive():
            self.timer.stop()

    def _resume_refresh(self):
        """拖动结束后恢复数据刷新"""
        if self.timer and not self.timer.isActive():
            self.timer.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._pause_refresh()
            self.setFocus(Qt.MouseFocusReason)

    def mouseMoveEvent(self, e):
        if getattr(self, "_drag_pos", None) and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = None
            self._resume_refresh()
            self._notify_change()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = None
            self.hide()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonDblClick and hasattr(ev, "button") and ev.button() == Qt.LeftButton:
            self._drag_pos = None
            self.hide()
            return True
        if ev.type() == QEvent.MouseButtonPress and hasattr(ev, "button") and ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._pause_refresh()
            self.setFocus(Qt.MouseFocusReason)
            return True
        if ev.type() == QEvent.MouseMove and hasattr(ev, "buttons") and (ev.buttons() & Qt.LeftButton) and getattr(self, "_drag_pos", None):
            self.move(ev.globalPosition().toPoint() - self._drag_pos)
            return True
        if ev.type() == QEvent.MouseButtonRelease and hasattr(ev, "button") and ev.button() == Qt.LeftButton:
            self._drag_pos = None
            self._resume_refresh()
            self._notify_change()
            return True
        return QWidget.eventFilter(self, obj, ev)

    def closeEvent(self, event): 
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        if self.timer and not self.timer.isActive(): 
            self.timer.start()
        if self._keep_top_timer and not self._keep_top_timer.isActive():
            self._keep_top_timer.start()
        self._defer_fit()

    def hideEvent(self, event):
        super().hideEvent(event)
        # 隐藏后仍需继续刷新以保证托盘 ToolTip / 总盈亏灯泡及时更新，不停数据刷新定时器
        if self._keep_top_timer and self._keep_top_timer.isActive():
            self._keep_top_timer.stop()

    def _ensure_on_top(self):
        """跨平台置顶：利用 Qt.WindowStaysOnTopHint 保持窗口始终在最前。"""
        if not self.isVisible():
            return
        try:
            popup = QApplication.activePopupWidget()
            if popup is not None and popup is not self and not self.isAncestorOf(popup):
                return
        except Exception:
            pass
        # 通过 raise_() 确保置顶；flags 中已包含 WindowStaysOnTopHint
        self.raise_()

    def _register_hotkey(self):
        try:
            keyboard.remove_all_hotkeys()
        except Exception:
            pass
        keyboard.add_hotkey(self.hotkey.lower(), lambda: self.hotkey_triggered.emit())

    def update_hotkey(self, new_hotkey: str):
        self.hotkey = new_hotkey.strip()
        self._register_hotkey()

    def toggle_win(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()