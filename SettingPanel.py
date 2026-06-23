import os, re
from functools import partial

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFontDatabase, QKeySequence, QDoubleValidator, QIntValidator, QAction
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QTabWidget, QPushButton, QSlider,
    QGroupBox, QLabel, QColorDialog, QComboBox, QAbstractItemView,
    QCheckBox, QListWidget, QListWidgetItem, QKeySequenceEdit, QFileDialog, QLineEdit, QMenu
)
from WidgetPanel import FloatLabel
from PySide6.QtWidgets import QSizePolicy


class CostDialog(QDialog):
    """设置持仓成本与数量的对话框。"""
    def __init__(self, parent: QWidget, code: str, cost: float = 0.0, qty: int = 0):
        super().__init__(parent)
        self.setWindowTitle(f"设置成本 - {code}")
        self.setModal(True)
        self.setFixedWidth(260)

        layout = QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        layout.addWidget(QLabel("成本价："), 0, 0)
        self.edit_cost = QLineEdit(f"{cost:g}" if cost and cost > 0 else "")
        self.edit_cost.setPlaceholderText("例如 12.345")
        cost_v = QDoubleValidator(0.0, 1e9, 4, self)
        cost_v.setNotation(QDoubleValidator.StandardNotation)
        self.edit_cost.setValidator(cost_v)
        layout.addWidget(self.edit_cost, 0, 1)

        layout.addWidget(QLabel("持仓数量："), 1, 0)
        self.edit_qty = QLineEdit(str(qty) if qty else "")
        self.edit_qty.setPlaceholderText("股数，可为负")
        self.edit_qty.setValidator(QIntValidator(-10**9, 10**9, self))
        layout.addWidget(self.edit_qty, 1, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_clear = QPushButton("清除")
        self.btn_ok = QPushButton("确定")
        self.btn_cancel = QPushButton("取消")
        for b in (self.btn_clear, self.btn_ok, self.btn_cancel):
            b.setFixedWidth(60)
            btn_row.addWidget(b)
        layout.addLayout(btn_row, 2, 0, 1, 2)

        self._cleared = False
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_clear.clicked.connect(self._on_clear)

    def _on_clear(self):
        self._cleared = True
        self.accept()

    def get_values(self):
        """返回 (cost, qty)。清除时返回 (0.0, 0)。"""
        if self._cleared:
            return 0.0, 0
        try:
            cost = float(self.edit_cost.text().strip() or 0)
        except Exception:
            cost = 0.0
        try:
            qty = int(self.edit_qty.text().strip() or 0)
        except Exception:
            qty = 0
        return cost, qty


class AlertDialog(QDialog):
    """设置封单预警阈值的对话框。可添加多个阈值：正=涨停封单手数，负=跌停封单手数。"""
    def __init__(self, parent: QWidget, code: str, thresholds: list = None):
        super().__init__(parent)
        self.setWindowTitle(f"封单预警 - {code}")
        self.setModal(True)
        self.setFixedWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        tip = QLabel("正值=涨停封单（手），负值=跌停封单（手）。\n"
                     "进入涨/跌停且封单达阈值时生效；\n"
                     "封单跌破阈值或打开涨/跌停时通知并失效。")
        tip.setWordWrap(True)
        tip.setStyleSheet("color: #888;")
        layout.addWidget(tip)

        self.list_thresholds = QListWidget()
        self.list_thresholds.setFixedHeight(120)
        for t in (thresholds or []):
            try:
                self._add_item(int(t))
            except Exception:
                pass
        layout.addWidget(self.list_thresholds)

        add_row = QHBoxLayout()
        self.edit_value = QLineEdit()
        self.edit_value.setPlaceholderText("手数：正=涨停，负=跌停")
        self.edit_value.setValidator(QIntValidator(-10**8, 10**8, self))
        self.btn_add_alert = QPushButton("添加")
        self.btn_add_alert.setFixedWidth(60)
        self.btn_remove_alert = QPushButton("删除")
        self.btn_remove_alert.setFixedWidth(60)
        add_row.addWidget(self.edit_value, 1)
        add_row.addWidget(self.btn_add_alert)
        add_row.addWidget(self.btn_remove_alert)
        layout.addLayout(add_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.btn_clear_all = QPushButton("清除全部")
        self.btn_ok = QPushButton("确定")
        self.btn_cancel = QPushButton("取消")
        for b in (self.btn_clear_all, self.btn_ok, self.btn_cancel):
            b.setFixedWidth(70)
            btn_row.addWidget(b)
        layout.addLayout(btn_row)

        self.btn_add_alert.clicked.connect(self._on_add)
        self.edit_value.returnPressed.connect(self._on_add)
        self.btn_remove_alert.clicked.connect(self._on_remove)
        self.btn_clear_all.clicked.connect(self.list_thresholds.clear)
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

    def _add_item(self, n: int):
        if n == 0:
            return
        for i in range(self.list_thresholds.count()):
            try:
                if int(self.list_thresholds.item(i).data(Qt.UserRole)) == n:
                    return
            except Exception:
                pass
        label = f"{n:+d} 手 ({'涨停' if n > 0 else '跌停'})"
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, n)
        self.list_thresholds.addItem(item)

    def _on_add(self):
        try:
            txt = self.edit_value.text().strip()
            if not txt:
                return
            n = int(txt)
            self._add_item(n)
            self.edit_value.clear()
        except Exception:
            pass

    def _on_remove(self):
        row = self.list_thresholds.currentRow()
        if row >= 0:
            self.list_thresholds.takeItem(row)

    def get_thresholds(self):
        result = []
        for i in range(self.list_thresholds.count()):
            try:
                n = int(self.list_thresholds.item(i).data(Qt.UserRole))
                if n != 0:
                    result.append(n)
            except Exception:
                pass
        return result


MIN_FONT_SIZE = 6
class SettingsDialog(QDialog):
    def __init__(self, win: FloatLabel, parent: QWidget, app=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.win = win
        self.app = app
        self.setModal(False)

        main = QHBoxLayout(self)
        main.setContentsMargins(8, 8, 8, 8)
        main.setSpacing(8)
        self.tabs = QTabWidget()
        main.addWidget(self.tabs)

        self.tab_sizes = {
            0: QSize(480, 300),
            1: QSize(480, 750),
            2: QSize(480, 460),
            3: QSize(480, 280),
            4: QSize(480, 720),
        }
        self._apply_tab_size(0)

        # ---- 第一页 ----
        tab_0 = QWidget()
        code_settings = QVBoxLayout(tab_0)

        # 1.自选列表
        g_codes = QGroupBox("自选列表")
        # 【修改点1】：确保外层布局允许控件填充
        g_codes.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        g_codes.setContentsMargins(3,25,3,6)
        lay_codes = QHBoxLayout(g_codes)
        lay_codes.setSpacing(6)
        # 1.1 代码列表
        self.list_codes = QListWidget()
        self.list_codes.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.SelectedClicked | QAbstractItemView.EditKeyPressed)
        # self.list_codes.setFixedWidth(150)
        self.list_codes.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        for c in self.win.codes:
            it = QListWidgetItem(c)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setCheckState(Qt.Checked if c in getattr(self.win, 'checked_codes', []) else Qt.Unchecked)
            it.setData(Qt.UserRole, c)  # 记住上次有效值
            self.list_codes.addItem(it)
        # 1.2 操作按钮
        btn_col = QVBoxLayout()
        btn_col.setSpacing(4)
        self.btn_add = QPushButton("添加")
        self.btn_add.setFixedWidth(60)
        self.btn_del = QPushButton("删除")
        self.btn_del.setFixedWidth(60)
        self.btn_up  = QPushButton("上移")
        self.btn_up.setFixedWidth(60)
        self.btn_dn  = QPushButton("下移")
        self.btn_dn.setFixedWidth(60)
        self.btn_cost = QPushButton("设置成本")
        self.btn_cost.setFixedWidth(60)
        self.btn_cost.setEnabled(False)
        self.btn_alert = QPushButton("封单预警")
        self.btn_alert.setFixedWidth(60)
        self.btn_alert.setEnabled(False)
        for b in (self.btn_add, self.btn_del, self.btn_up, self.btn_dn, self.btn_cost, self.btn_alert):
            btn_col.addWidget(b)
        btn_col.addStretch(1)

        lay_codes.addWidget(self.list_codes)
        lay_codes.addLayout(btn_col)
        code_settings.addWidget(g_codes, 1)

        self.tabs.addTab(tab_0, "自选列表")

        # ---- 第二页 ----
        tab_1 = QWidget()
        data_settings = QVBoxLayout(tab_1)

        # 2.刷新间隔
        g_interval = QGroupBox("刷新间隔")
        g_interval.setContentsMargins(3,12,3,6)
        self.cmb_interval = QComboBox()
        self.cmb_interval.setFixedWidth(136)
        for s in [1,2,3,5,10,15,30,60]:
            self.cmb_interval.addItem(f"{s} 秒", userData=s)
        idx = self.cmb_interval.findData(self.win.refresh_seconds)
        self.cmb_interval.setCurrentIndex(idx if idx >= 0 else 1)
        v = QVBoxLayout(g_interval)
        v.setContentsMargins(6,6,6,6)
        v.addWidget(self.cmb_interval)
        data_settings.addWidget(g_interval)

        # 3.显示选项
        # 3.0 双模式切换开关
        g_dual_mode = QGroupBox("双模式切换")
        g_dual_mode.setContentsMargins(3,12,3,6)
        gl_dual_mode = QGridLayout(g_dual_mode)
        gl_dual_mode.setHorizontalSpacing(6)
        gl_dual_mode.setVerticalSpacing(6)
        self.chk_dual_mode = QCheckBox("启用模式切换（悬浮显示正常模式，离开显示简易模式）")
        self.chk_dual_mode.setChecked(bool(self.win.dual_mode_enabled))
        gl_dual_mode.addWidget(self.chk_dual_mode, 0, 0, 1, 3)
        # 延迟设置
        gl_dual_mode.addWidget(QLabel("切换延迟："), 1, 0)
        self.cmb_leave_delay = QComboBox()
        self.cmb_leave_delay.setFixedWidth(100)
        for ms, label in [(0, "无延迟"), (200, "0.2 秒"), (500, "0.5 秒"), (1000, "1 秒"), (2000, "2 秒"), (3000, "3 秒")]:
            self.cmb_leave_delay.addItem(label, userData=ms)
        idx_delay = self.cmb_leave_delay.findData(self.win.leave_delay_ms)
        if idx_delay < 0:
            idx_delay = self.cmb_leave_delay.findData(500)
        self.cmb_leave_delay.setCurrentIndex(idx_delay if idx_delay >= 0 else 2)
        self.cmb_leave_delay.setEnabled(bool(self.win.dual_mode_enabled))
        gl_dual_mode.addWidget(self.cmb_leave_delay, 1, 1)
        data_settings.addWidget(g_dual_mode)

        # 3.1复选框组 - 正常模式
        g_flags = QGroupBox("正常模式指标")
        g_flags.setContentsMargins(3,12,3,6)
        gl_flags = QGridLayout(g_flags)
        gl_flags.setHorizontalSpacing(8)
        gl_flags.setVerticalSpacing(6)
        self.cbs: list[QCheckBox] = []
        cb_texts = self.win.ALL_HEADERS

        g_flag_name = QGroupBox("名称")
        gl_flag_name = QGridLayout(g_flag_name)
        gl_flag_name.setHorizontalSpacing(6)
        gl_flag_name.setVerticalSpacing(6)
        # 代码、名称
        for i, h in enumerate(cb_texts[0:2]):
            cb = QCheckBox(h)
            cb.setChecked(self.win.header_is_visible(h))
            cb.stateChanged.connect(partial(self._on_cb_changed, h))
            self.cbs.append(cb)
            gl_flag_name.addWidget(cb, i, 0)
        self.cb_short_code = QCheckBox("仅显示数字")
        self.cb_short_code.setChecked(bool(self.win.short_code))
        self.cb_short_code.setEnabled(self.win.header_is_visible("代码"))
        gl_flag_name.addWidget(self.cb_short_code, 0, 1)
        self.cmb_namelength = QComboBox()
        self.cmb_namelength.setFixedWidth(80)
        for l in [0, 1, 2, 3, 4]:
            self.cmb_namelength.addItem(f"{l}个字" if l>0 else "完整", userData=l)
        idx_name = self.cmb_namelength.findData(self.win.name_length)
        self.cmb_namelength.setCurrentIndex(idx_name if idx_name>=0 else 1)
        self.cmb_namelength.setEnabled(self.win.header_is_visible("名称"))
        gl_flag_name.addWidget(self.cmb_namelength, 1, 1)
        gl_flags.addWidget(g_flag_name, 0, 0)

        g_flag_price = QGroupBox("价格")
        gl_flag_price = QGridLayout(g_flag_price)
        gl_flag_price.setHorizontalSpacing(6)
        gl_flag_price.setVerticalSpacing(6)
        # 现价、涨跌值、涨跌幅、盈亏 — 2×2 网格布局
        for i, h in enumerate(cb_texts[2:6]):
            cb = QCheckBox(h)
            cb.setChecked(self.win.header_is_visible(h))
            cb.stateChanged.connect(partial(self._on_cb_changed, h))
            self.cbs.append(cb)
            gl_flag_price.addWidget(cb, i // 2, i % 2)
        gl_flags.addWidget(g_flag_price, 1, 0)

        g_flag_order = QGroupBox("盘口")
        gl_flag_order = QGridLayout(g_flag_order)
        gl_flag_order.setHorizontalSpacing(6)
        gl_flag_order.setVerticalSpacing(6)
        # 买一/卖一
        self.cb_b1s1 = QCheckBox("买一/卖一")
        self.cb_b1s1.setChecked(self.win.b1s1_visible)
        self.cb_b1s1.stateChanged.connect(self._on_b1s1_toggled)
        self.cbs.append(self.cb_b1s1)
        gl_flag_order.addWidget(self.cb_b1s1, 0, 0)
        
        # 委比
        cb_commi = QCheckBox("委比")
        cb_commi.setChecked(self.win.header_is_visible("委比"))
        cb_commi.stateChanged.connect(partial(self._on_cb_changed, "委比"))
        self.cbs.append(cb_commi)
        gl_flag_order.addWidget(cb_commi, 1, 0)
        
        # 买一/卖一显示模式：数量 / 价格 / 数量和价格
        self.cmb_b1s1_display = QComboBox()
        self.cmb_b1s1_display.setFixedWidth(150)
        self.cmb_b1s1_display.addItem("数量", userData="qty")
        self.cmb_b1s1_display.addItem("价格", userData="price")
        self.cmb_b1s1_display.addItem("数量和价格", userData="both")
        cur_mode = getattr(self.win, 'b1s1_display', 'qty')
        idx_mode = self.cmb_b1s1_display.findData(cur_mode)
        self.cmb_b1s1_display.setCurrentIndex(idx_mode if idx_mode>=0 else 0)
        self.cmb_b1s1_display.setEnabled(self.win.b1s1_visible)
        gl_flag_order.addWidget(self.cmb_b1s1_display, 0, 1)
        gl_flags.addWidget(g_flag_order, 0, 1)

        g_flag_deal = QGroupBox("成交")
        gl_flag_deal = QGridLayout(g_flag_deal)
        gl_flag_deal.setHorizontalSpacing(6)
        gl_flag_deal.setVerticalSpacing(6)
        for i, idx in enumerate(range(9,14)):
            cb = QCheckBox(cb_texts[idx])
            cb.setChecked(self.win.header_is_visible(cb_texts[idx]))
            cb.stateChanged.connect(partial(self._on_cb_changed, cb_texts[idx]))
            self.cbs.append(cb)
            gl_flag_deal.addWidget(cb, i // 2, i % 2)
        gl_flags.addWidget(g_flag_deal, 1, 1)

        g_flag_other = QGroupBox("其他")
        gl_flag_other = QGridLayout(g_flag_other)
        gl_flag_other.setHorizontalSpacing(6)
        gl_flag_other.setVerticalSpacing(6)
        for i in range(14,15):
            cb = QCheckBox(cb_texts[i])
            cb.setChecked(self.win.header_is_visible(cb_texts[i]))
            cb.stateChanged.connect(partial(self._on_cb_changed, cb_texts[i]))
            self.cbs.append(cb)
            gl_flag_other.addWidget(cb, i-14, 0)
        gl_flags.addWidget(g_flag_other, 2, 0)

        data_settings.addWidget(g_flags)

        # 3.2 简易模式指标复选框组
        g_simple_flags = QGroupBox("简易模式指标")
        g_simple_flags.setContentsMargins(3,12,3,6)
        gl_simple = QGridLayout(g_simple_flags)
        gl_simple.setHorizontalSpacing(6)
        gl_simple.setVerticalSpacing(6)
        self.simple_cbs: list[QCheckBox] = []
        simple_headers = ["代码", "名称", "现价", "涨跌值", "涨跌幅", "盈亏", "买一/卖一", "委比", "成交量", "成交额", "均价", "日高", "日低", "K线"]
        simple_header_keys = ["代码", "名称", "现价", "涨跌值", "涨跌幅", "盈亏", "买一", "委比", "成交量", "成交额", "均价", "日高", "日低", "K线"]
        for i, (label, key) in enumerate(zip(simple_headers, simple_header_keys)):
            cb = QCheckBox(label)
            cb.setChecked(self.win.simple_header_is_visible(key))
            cb.stateChanged.connect(partial(self._on_simple_cb_changed, key))
            self.simple_cbs.append(cb)
            gl_simple.addWidget(cb, i // 4, i % 4)
        # 简易模式指标组仅在双模式启用时可编辑
        g_simple_flags.setEnabled(bool(self.win.dual_mode_enabled))
        self._g_simple_flags = g_simple_flags
        data_settings.addWidget(g_simple_flags)

        # 符号设置
        g_symbols = QGroupBox("标记符号")
        g_symbols.setContentsMargins(3,12,3,6)
        gl_sym = QGridLayout(g_symbols)
        gl_sym.setHorizontalSpacing(6)
        gl_sym.setVerticalSpacing(6)
        gl_sym.addWidget(QLabel("日高:"), 0, 0)
        self.edit_sym_high = QLineEdit(self.win.sym_high)
        self.edit_sym_high.setFixedWidth(40)
        self.edit_sym_high.setMaxLength(2)
        gl_sym.addWidget(self.edit_sym_high, 0, 1)
        gl_sym.addWidget(QLabel("日低:"), 0, 2)
        self.edit_sym_low = QLineEdit(self.win.sym_low)
        self.edit_sym_low.setFixedWidth(40)
        self.edit_sym_low.setMaxLength(2)
        gl_sym.addWidget(self.edit_sym_low, 0, 3)
        gl_sym.addWidget(QLabel("涨停:"), 1, 0)
        self.edit_sym_limit_up = QLineEdit(self.win.sym_limit_up)
        self.edit_sym_limit_up.setFixedWidth(40)
        self.edit_sym_limit_up.setMaxLength(2)
        gl_sym.addWidget(self.edit_sym_limit_up, 1, 1)
        gl_sym.addWidget(QLabel("跌停:"), 1, 2)
        self.edit_sym_limit_down = QLineEdit(self.win.sym_limit_down)
        self.edit_sym_limit_down.setFixedWidth(40)
        self.edit_sym_limit_down.setMaxLength(2)
        gl_sym.addWidget(self.edit_sym_limit_down, 1, 3)
        gl_sym.addWidget(QLabel("涨:"), 2, 0)
        self.edit_sym_rise = QLineEdit(self.win.sym_rise)
        self.edit_sym_rise.setFixedWidth(40)
        self.edit_sym_rise.setMaxLength(2)
        gl_sym.addWidget(self.edit_sym_rise, 2, 1)
        gl_sym.addWidget(QLabel("跌:"), 2, 2)
        self.edit_sym_fall = QLineEdit(self.win.sym_fall)
        self.edit_sym_fall.setFixedWidth(40)
        self.edit_sym_fall.setMaxLength(2)
        gl_sym.addWidget(self.edit_sym_fall, 2, 3)
        data_settings.addWidget(g_symbols)
        data_settings.addStretch(1)

        self.tabs.addTab(tab_1, "显示数据")

        # ---- 第三页 ----
        tab_2 = QWidget()
        appearance_settings = QVBoxLayout(tab_2)

        # 表格外观
        g_table = QGroupBox("表格外观")
        g_table.setContentsMargins(3,12,3,6)
        gl_table = QGridLayout(g_table)
        gl_table.setHorizontalSpacing(6)
        gl_table.setVerticalSpacing(6)
        # 复选框
        self.chk_table_header = QCheckBox("显示表头")
        self.chk_table_header.setChecked(self.win.header_visible)
        self.chk_table_grid = QCheckBox("显示网格")
        self.chk_table_grid.setChecked(self.win.grid_visible)

        gl_table.addWidget(self.chk_table_header,0,0)
        gl_table.addWidget(self.chk_table_grid,0,1)
        appearance_settings.addWidget(g_table)

        # 3.颜色/透明度
        g_color = QGroupBox("颜色与透明度")
        g_color.setContentsMargins(3,12,3,6)
        gl_color = QGridLayout(g_color)
        gl_color.setHorizontalSpacing(6)
        gl_color.setVerticalSpacing(6)
        # 3.1 颜色按钮：涨/跌/表格/背景
        self.btn_up_color = QPushButton("涨颜色…")
        self.btn_up_color.setFixedWidth(90)
        self.btn_down_color = QPushButton("跌颜色…")
        self.btn_down_color.setFixedWidth(90)
        self.btn_fg = QPushButton("表格颜色…")
        self.btn_fg.setFixedWidth(90)
        self.btn_bg = QPushButton("背景颜色…")
        self.btn_bg.setFixedWidth(90)
        # 3.2 恢复默认按钮
        self.btn_reset_colors = QPushButton("恢复默认")
        self.btn_reset_colors.setFixedWidth(90)
        # 3.3 滑块：表格不透明度（表格线/表头底边线）
        self.slider_grid_alpha = QSlider(Qt.Horizontal)
        self.slider_grid_alpha.setRange(0, 100)
        self.slider_grid_alpha.setMinimumWidth(150)
        self.slider_grid_alpha.setValue(int(getattr(self.win, 'grid_alpha_pct', 31)))
        self.lbl_grid_alpha = QLabel(f"{self.slider_grid_alpha.value()}%")
        # 3.4 滑块：表头不透明度（表头文字）
        self.slider_header_alpha = QSlider(Qt.Horizontal)
        self.slider_header_alpha.setRange(0, 100)
        self.slider_header_alpha.setMinimumWidth(150)
        self.slider_header_alpha.setValue(int(getattr(self.win, 'header_alpha_pct', 100)))
        self.lbl_header_alpha = QLabel(f"{self.slider_header_alpha.value()}%")
        # 3.5 滑块：背景不透明度
        self.slider_bg_alpha = QSlider(Qt.Horizontal)
        self.slider_bg_alpha.setRange(1, 100)
        self.slider_bg_alpha.setMinimumWidth(150)
        self.slider_bg_alpha.setValue(int(round(self.win.bg.alpha()/2.55)))
        self.lbl_bg_alpha = QLabel(f"{self.slider_bg_alpha.value()}%")
        # 3.6 滑块：整体不透明度
        self.slider_win_opacity = QSlider(Qt.Horizontal)
        self.slider_win_opacity.setRange(20, 100)
        self.slider_win_opacity.setMinimumWidth(150)
        self.slider_win_opacity.setValue(int(round(self.win.windowOpacity()*100)))
        self.lbl_win_opacity = QLabel(f"{self.slider_win_opacity.value()}%")

        gl_color.addWidget(self.btn_up_color,0,0,1,2)
        gl_color.addWidget(self.btn_down_color,0,2,1,2)
        gl_color.addWidget(self.btn_fg,0,4,1,2)
        gl_color.addWidget(self.btn_bg,1,0,1,2)
        gl_color.addWidget(self.btn_reset_colors,1,4,1,2)
        gl_color.addWidget(QLabel("表格不透明度："),2,0,1,2)
        gl_color.addWidget(self.slider_grid_alpha,2,2,1,3)
        gl_color.addWidget(self.lbl_grid_alpha,2,5,1,1)
        gl_color.addWidget(QLabel("表头不透明度："),3,0,1,2)
        gl_color.addWidget(self.slider_header_alpha,3,2,1,3)
        gl_color.addWidget(self.lbl_header_alpha,3,5,1,1)
        gl_color.addWidget(QLabel("背景不透明度："),4,0,1,2)
        gl_color.addWidget(self.slider_bg_alpha,4,2,1,3)
        gl_color.addWidget(self.lbl_bg_alpha,4,5,1,1)
        gl_color.addWidget(QLabel("整体不透明度："),5,0,1,2)
        gl_color.addWidget(self.slider_win_opacity,5,2,1,3)
        gl_color.addWidget(self.lbl_win_opacity,5,5,1,1)
        appearance_settings.addWidget(g_color)

        # 4.字体/行距
        g_font = QGroupBox("字体与行距")
        g_font.setContentsMargins(3,12,3,6)
        gl_font = QGridLayout(g_font)
        gl_font.setHorizontalSpacing(6)
        gl_font.setVerticalSpacing(6)
        # 4.1 选项：字体
        self.cmb_family = QComboBox()
        self.cmb_family.setFixedWidth(200)
        for fam in sorted(QFontDatabase.families()):
            self.cmb_family.addItem(fam)
        fi = self.cmb_family.findText(self.win.font.family())
        self.cmb_family.setCurrentIndex(fi if fi >= 0 else 0)
        # 4.2 滑块：字号
        self.slider_font = QSlider(Qt.Horizontal)
        self.slider_font.setRange(MIN_FONT_SIZE, 15)
        self.slider_font.setMinimumWidth(150)
        self.slider_font.setValue(self.win.font.pointSize())
        self.lbl_font = QLabel(f"{self.slider_font.value()} pt")
        # 4.3 滑块：行间距
        self.slider_line = QSlider(Qt.Horizontal)
        self.slider_line.setRange(0, 20)
        self.slider_line.setMinimumWidth(150)
        self.slider_line.setValue(getattr(self.win,"line_extra_px",4))
        self.lbl_line = QLabel(f"+{self.slider_line.value()} px")

        gl_font.addWidget(QLabel("字体："),0,0,1,2)
        gl_font.addWidget(self.cmb_family,0,2,1,4)
        gl_font.addWidget(QLabel("字号："),1,0,1,2)
        gl_font.addWidget(self.slider_font,1,2,1,3)
        gl_font.addWidget(self.lbl_font,1,5,1,1)
        gl_font.addWidget(QLabel("行距："),2,0,1,2)
        gl_font.addWidget(self.slider_line,2,2,1,3)
        gl_font.addWidget(self.lbl_line,2,5,1,1)
        appearance_settings.addWidget(g_font)

        self.tabs.addTab(tab_2, "外观")

        # ---- 第四页 ----
        tab_3 = QWidget()
        other_settings = QVBoxLayout(tab_3)

        # 4.热键
        g_hotkey = QGroupBox("快捷键")
        g_hotkey.setContentsMargins(3,12,3,6)
        gl_hotkey = QGridLayout(g_hotkey)
        gl_hotkey.setHorizontalSpacing(6)
        gl_hotkey.setVerticalSpacing(6)
        gl_hotkey.addWidget(QLabel("隐藏/显示浮窗："),0,0,1,1)
        self.edit_hotkey = QKeySequenceEdit()
        self.edit_hotkey.setKeySequence(QKeySequence(self.win.hotkey))
        gl_hotkey.addWidget(self.edit_hotkey,0,1)
        # 开机启动复选框
        self.chk_start_on_boot = QCheckBox("开机启动")
        self.chk_start_on_boot.setChecked(bool(self.win.start_on_boot))
        other_settings.addWidget(self.chk_start_on_boot)
        other_settings.addWidget(g_hotkey)

        # 窗口锚点
        from PySide6.QtWidgets import QRadioButton, QButtonGroup
        g_anchor = QGroupBox("窗口锚点")
        g_anchor.setContentsMargins(3,12,3,6)
        gl_anchor = QHBoxLayout(g_anchor)
        self.rb_anchor_left = QRadioButton("左对齐")
        self.rb_anchor_right = QRadioButton("右对齐")
        cur_anchor = getattr(self.win, 'anchor', 'left')
        if cur_anchor == 'right':
            self.rb_anchor_right.setChecked(True)
        else:
            self.rb_anchor_left.setChecked(True)
        self._anchor_group = QButtonGroup(self)
        self._anchor_group.addButton(self.rb_anchor_left)
        self._anchor_group.addButton(self.rb_anchor_right)
        gl_anchor.addWidget(QLabel("指标变化时保持："))
        gl_anchor.addWidget(self.rb_anchor_left)
        gl_anchor.addWidget(self.rb_anchor_right)
        gl_anchor.addStretch(1)
        other_settings.addWidget(g_anchor)

        # 程序图标选择
        g_icon = QGroupBox("程序图标")
        g_icon.setContentsMargins(3,12,3,6)
        gl_icon = QHBoxLayout(g_icon)
        self.cmb_icon = QComboBox()
        icon_items = [
            ("默认", 'default'),
            ("系统：计算机", 'std:computer'),
            ("系统：网络", 'std:network'),
            ("系统：文件夹", 'std:folder'),
            ("系统：文件", 'std:file'),
            ("系统：回收站", 'std:trash'),
        ]
        for label, val in icon_items:
            self.cmb_icon.addItem(label, userData=val)
        self.btn_pick_icon = QPushButton("自定义图标…")
        self.btn_pick_icon.setFixedWidth(120)
        gl_icon.addWidget(self.cmb_icon)
        gl_icon.addWidget(self.btn_pick_icon)
        other_settings.addWidget(g_icon)
        other_settings.addStretch(1)

        self.tabs.addTab(tab_3, "常规")

        # ---- 第五页：报警 ----
        tab_4 = QWidget()
        alert_settings = QVBoxLayout(tab_4)

        # 涨跌异动报警
        g_price_alert = QGroupBox("涨跌异动报警")
        g_price_alert.setContentsMargins(3, 12, 3, 6)
        gl_pa = QVBoxLayout(g_price_alert)
        gl_pa.setSpacing(8)

        # 启用开关
        self.chk_price_alert = QCheckBox("启用涨跌异动报警")
        self.chk_price_alert.setChecked(bool(self.win.price_alert_enabled))
        gl_pa.addWidget(self.chk_price_alert)

        # 规则列表
        self.list_pa_rules = QListWidget()
        self.list_pa_rules.setFixedHeight(100)
        for rule in self.win.price_alert_rules:
            self._add_pa_rule_item(rule)
        gl_pa.addWidget(self.list_pa_rules)

        # 添加规则区域
        add_row = QGridLayout()
        add_row.setHorizontalSpacing(6)
        add_row.setVerticalSpacing(4)
        add_row.addWidget(QLabel("周期:"), 0, 0)
        self.cmb_pa_period = QComboBox()
        self.cmb_pa_period.setFixedWidth(90)
        for sec in [1, 3, 5, 10, 20, 30, 60, 120, 180, 300, 600]:
            if sec < 60:
                self.cmb_pa_period.addItem(f"{sec}秒", userData=sec)
            else:
                self.cmb_pa_period.addItem(f"{sec//60}分钟", userData=sec)
        self.cmb_pa_period.setCurrentIndex(5)  # 默认30秒
        add_row.addWidget(self.cmb_pa_period, 0, 1)

        add_row.addWidget(QLabel("阈值:"), 0, 2)
        self.edit_pa_threshold = QLineEdit("2.0")
        self.edit_pa_threshold.setFixedWidth(60)
        self.edit_pa_threshold.setPlaceholderText("%")
        th_validator = QDoubleValidator(0.1, 50.0, 2, self)
        th_validator.setNotation(QDoubleValidator.StandardNotation)
        self.edit_pa_threshold.setValidator(th_validator)
        add_row.addWidget(self.edit_pa_threshold, 0, 3)
        add_row.addWidget(QLabel("%"), 0, 4)

        add_row.addWidget(QLabel("冷却:"), 1, 0)
        self.cmb_pa_cooldown = QComboBox()
        self.cmb_pa_cooldown.setFixedWidth(90)
        for sec in [1, 3, 5, 10, 15, 30, 60, 120, 180, 300, 600]:
            if sec < 60:
                self.cmb_pa_cooldown.addItem(f"{sec}秒", userData=sec)
            else:
                self.cmb_pa_cooldown.addItem(f"{sec//60}分钟", userData=sec)
        self.cmb_pa_cooldown.setCurrentIndex(5)  # 默认30秒
        add_row.addWidget(self.cmb_pa_cooldown, 1, 1)

        self.btn_pa_add = QPushButton("添加规则")
        self.btn_pa_add.setFixedWidth(70)
        add_row.addWidget(self.btn_pa_add, 1, 2, 1, 2)
        self.btn_pa_del = QPushButton("删除")
        self.btn_pa_del.setFixedWidth(50)
        add_row.addWidget(self.btn_pa_del, 1, 4)
        gl_pa.addLayout(add_row)

        # 说明
        tip_pa = QLabel("在监测周期内，若股票价格波动超过阈值，\n"
                        "将发出系统通知。冷却时间内同一股票不重复报警。")
        tip_pa.setWordWrap(True)
        tip_pa.setStyleSheet("color: #888;")
        gl_pa.addWidget(tip_pa)

        alert_settings.addWidget(g_price_alert)

        # 新高新低报警
        g_nhl_alert = QGroupBox("新高新低报警")
        g_nhl_alert.setContentsMargins(3, 12, 3, 6)
        gl_nhl = QVBoxLayout(g_nhl_alert)
        gl_nhl.setSpacing(8)

        # 启用开关
        self.chk_nhl_alert = QCheckBox("启用新高新低报警")
        self.chk_nhl_alert.setChecked(bool(self.win.new_high_low_alert_enabled))
        gl_nhl.addWidget(self.chk_nhl_alert)

        # 新高/新低分别开关
        nhl_chk_row = QHBoxLayout()
        self.chk_new_high = QCheckBox("新高报警")
        self.chk_new_high.setChecked(bool(self.win.new_high_alert))
        nhl_chk_row.addWidget(self.chk_new_high)
        self.chk_new_low = QCheckBox("新低报警")
        self.chk_new_low.setChecked(bool(self.win.new_low_alert))
        nhl_chk_row.addWidget(self.chk_new_low)
        nhl_chk_row.addStretch(1)
        gl_nhl.addLayout(nhl_chk_row)

        # 冷却时间
        nhl_cd_row = QHBoxLayout()
        nhl_cd_row.addWidget(QLabel("冷却时间:"))
        self.cmb_nhl_cooldown = QComboBox()
        self.cmb_nhl_cooldown.setFixedWidth(90)
        nhl_cd_options = [5, 10, 15, 30, 60, 120, 180, 300, 600]
        for sec in nhl_cd_options:
            if sec < 60:
                self.cmb_nhl_cooldown.addItem(f"{sec}秒", userData=sec)
            else:
                self.cmb_nhl_cooldown.addItem(f"{sec//60}分钟", userData=sec)
        # 设置当前值
        cur_cd = self.win.new_high_low_cooldown
        for i in range(self.cmb_nhl_cooldown.count()):
            if self.cmb_nhl_cooldown.itemData(i) == cur_cd:
                self.cmb_nhl_cooldown.setCurrentIndex(i)
                break
        nhl_cd_row.addWidget(self.cmb_nhl_cooldown)
        nhl_cd_row.addStretch(1)
        gl_nhl.addLayout(nhl_cd_row)

        # 说明
        tip_nhl = QLabel("当股票价格创当日新高或新低时发出系统通知。\n"
                         "冷却时间内同一股票不重复报警。")
        tip_nhl.setWordWrap(True)
        tip_nhl.setStyleSheet("color: #888;")
        gl_nhl.addWidget(tip_nhl)

        alert_settings.addWidget(g_nhl_alert)

        # 涨跌停通知
        g_limit_alert = QGroupBox("涨跌停通知")
        g_limit_alert.setContentsMargins(3, 12, 3, 6)
        gl_la = QVBoxLayout(g_limit_alert)
        gl_la.setSpacing(8)

        # 启用开关
        self.chk_limit_alert = QCheckBox("启用涨跌停通知")
        self.chk_limit_alert.setChecked(bool(self.win.limit_alert_enabled))
        gl_la.addWidget(self.chk_limit_alert)

        # 到达/离开分别开关
        la_chk_row1 = QHBoxLayout()
        self.chk_reach_limit_up = QCheckBox("到达涨停")
        self.chk_reach_limit_up.setChecked(bool(self.win.limit_alert_reach_up))
        la_chk_row1.addWidget(self.chk_reach_limit_up)
        self.chk_reach_limit_down = QCheckBox("到达跌停")
        self.chk_reach_limit_down.setChecked(bool(self.win.limit_alert_reach_down))
        la_chk_row1.addWidget(self.chk_reach_limit_down)
        la_chk_row1.addStretch(1)
        gl_la.addLayout(la_chk_row1)

        la_chk_row2 = QHBoxLayout()
        self.chk_leave_limit_up = QCheckBox("离开涨停")
        self.chk_leave_limit_up.setChecked(bool(self.win.limit_alert_leave_up))
        la_chk_row2.addWidget(self.chk_leave_limit_up)
        self.chk_leave_limit_down = QCheckBox("离开跌停")
        self.chk_leave_limit_down.setChecked(bool(self.win.limit_alert_leave_down))
        la_chk_row2.addWidget(self.chk_leave_limit_down)
        la_chk_row2.addStretch(1)
        gl_la.addLayout(la_chk_row2)

        # 冷却时间
        la_cd_row = QHBoxLayout()
        la_cd_row.addWidget(QLabel("冷却时间:"))
        self.cmb_limit_alert_cooldown = QComboBox()
        self.cmb_limit_alert_cooldown.setFixedWidth(90)
        la_cd_options = [5, 10, 15, 30, 60, 120, 180, 300, 600]
        for sec in la_cd_options:
            if sec < 60:
                self.cmb_limit_alert_cooldown.addItem(f"{sec}秒", userData=sec)
            else:
                self.cmb_limit_alert_cooldown.addItem(f"{sec//60}分钟", userData=sec)
        # 设置当前值
        cur_la_cd = self.win.limit_alert_cooldown
        for i in range(self.cmb_limit_alert_cooldown.count()):
            if self.cmb_limit_alert_cooldown.itemData(i) == cur_la_cd:
                self.cmb_limit_alert_cooldown.setCurrentIndex(i)
                break
        la_cd_row.addWidget(self.cmb_limit_alert_cooldown)
        la_cd_row.addStretch(1)
        gl_la.addLayout(la_cd_row)

        # 说明
        tip_la = QLabel("当股票价格到达涨跌停或离开涨跌停时发出系统通知。\n"
                        "冷却时间内同一股票不重复报警。")
        tip_la.setWordWrap(True)
        tip_la.setStyleSheet("color: #888;")
        gl_la.addWidget(tip_la)

        alert_settings.addWidget(g_limit_alert)
        alert_settings.addStretch(1)

        self.tabs.addTab(tab_4, "报警")

        # ---- 连接 ----
        # 连接：代码列表
        self.list_codes.itemChanged.connect(self._on_codes_changed)
        self.btn_add.clicked.connect(self._add_code)
        self.btn_del.clicked.connect(self._del_code)
        self.btn_up.clicked.connect(self._move_up)
        self.btn_dn.clicked.connect(self._move_down)
        self.btn_cost.clicked.connect(self._open_cost_dialog_for_current)
        self.btn_alert.clicked.connect(self._open_alert_dialog_for_current)
        self.list_codes.itemSelectionChanged.connect(self._on_list_selection_changed)
        self.list_codes.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_codes.customContextMenuRequested.connect(self._on_list_context_menu)
        # 连接：其它设置
        self.cmb_interval.currentIndexChanged.connect(self._on_interval_changed)
        self.cmb_namelength.currentIndexChanged.connect(self._on_name_length_changed)
        self.btn_up_color.clicked.connect(self.pick_up_color)
        self.btn_down_color.clicked.connect(self.pick_down_color)
        self.btn_fg.clicked.connect(self.pick_fg)
        self.btn_bg.clicked.connect(self.pick_bg)
        self.btn_reset_colors.clicked.connect(self._on_reset_colors)
        self.slider_bg_alpha.valueChanged.connect(self.apply_bg_alpha)
        self.slider_win_opacity.valueChanged.connect(self.apply_win_opacity)
        self.slider_grid_alpha.valueChanged.connect(self.apply_grid_alpha)
        self.slider_header_alpha.valueChanged.connect(self.apply_header_alpha)
        self.cmb_family.currentTextChanged.connect(self._on_family_changed)
        self.slider_font.valueChanged.connect(self.apply_font_size)
        self.slider_line.valueChanged.connect(self._on_line_changed)
        self.edit_hotkey.editingFinished.connect(self._on_hotkey_changed)
        self.chk_start_on_boot.toggled.connect(self._on_start_on_boot_toggled)
        self.chk_table_header.toggled.connect(self._on_header_toggled)
        self.chk_table_grid.toggled.connect(self._on_grid_toggled)
        # icon controls
        try:
            # set current index based on app config if available
            cur_choice = None
            if hasattr(self, 'app') and self.app is not None:
                cur_choice = getattr(self.app, '_app_icon_choice', None)
            if cur_choice is None:
                cur_choice = 'default'
            # find index
            idx = self.cmb_icon.findData(cur_choice)
            if idx < 0:
                if isinstance(cur_choice, str) and os.path.exists(cur_choice):
                    self.cmb_icon.addItem('自定义', userData=cur_choice)
                    idx = self.cmb_icon.count()-1
            self.cmb_icon.setCurrentIndex(idx if idx >= 0 else 0)
        except Exception:
            pass
        self.cmb_icon.currentIndexChanged.connect(self._on_icon_changed)
        self.btn_pick_icon.clicked.connect(self._pick_custom_icon)
        self.tabs.currentChanged.connect(self._apply_tab_size)
        self.cmb_b1s1_display.currentIndexChanged.connect(self._on_b1s1_display_changed)
        self.cb_short_code.stateChanged.connect(self._on_short_code_toggled)
        # 符号设置连接
        self.edit_sym_high.textChanged.connect(self._on_symbols_changed)
        self.edit_sym_low.textChanged.connect(self._on_symbols_changed)
        self.edit_sym_limit_up.textChanged.connect(self._on_symbols_changed)
        self.edit_sym_limit_down.textChanged.connect(self._on_symbols_changed)
        self.edit_sym_rise.textChanged.connect(self._on_symbols_changed)
        self.edit_sym_fall.textChanged.connect(self._on_symbols_changed)
        # 双模式切换连接
        self.chk_dual_mode.toggled.connect(self._on_dual_mode_toggled)
        self.cmb_leave_delay.currentIndexChanged.connect(self._on_leave_delay_changed)
        # 锚点连接
        self.rb_anchor_left.toggled.connect(self._on_anchor_changed)
        self.rb_anchor_right.toggled.connect(self._on_anchor_changed)
        # 涨跌异动报警连接
        self.chk_price_alert.toggled.connect(self._on_price_alert_toggled)
        self.btn_pa_add.clicked.connect(self._on_pa_add_rule)
        self.btn_pa_del.clicked.connect(self._on_pa_del_rule)
        # 新高新低报警连接
        self.chk_nhl_alert.toggled.connect(self._on_nhl_alert_toggled)
        self.chk_new_high.toggled.connect(self._on_new_high_toggled)
        self.chk_new_low.toggled.connect(self._on_new_low_toggled)
        self.cmb_nhl_cooldown.currentIndexChanged.connect(self._on_nhl_cooldown_changed)
        # 涨跌停通知连接
        self.chk_limit_alert.toggled.connect(self._on_limit_alert_toggled)
        self.chk_reach_limit_up.toggled.connect(self._on_reach_limit_up_toggled)
        self.chk_reach_limit_down.toggled.connect(self._on_reach_limit_down_toggled)
        self.chk_leave_limit_up.toggled.connect(self._on_leave_limit_up_toggled)
        self.chk_leave_limit_down.toggled.connect(self._on_leave_limit_down_toggled)
        self.cmb_limit_alert_cooldown.currentIndexChanged.connect(self._on_limit_alert_cooldown_changed)

    def _on_start_on_boot_toggled(self, checked: bool):
        try:
            self.win.set_start_on_boot(bool(checked))
            if hasattr(self, 'app') and self.app is not None:
                try:
                    self.app.set_start_on_boot(bool(checked))
                except Exception:
                    pass
        except Exception:
            pass

    # —— 代码规格化 —— #
    _re_full = re.compile(r'^(sh|sz|bj)\d+$')
    _re_6 = re.compile(r'^\d{6}$')
    # 【新增】：匹配期货代码的正则 (nf_ 或 hf_ 开头，后面跟字母和数字)
    _re_futures = re.compile(r'^(nf|hf)_[a-zA-Z0-9]+$', re.IGNORECASE)

    def _normalize_code_or_none(self, s: str):
        original_s = (s or "").strip()
        if not original_s: 
            return None
            
        # ==========================================
        # 第一步：【智能免敲前缀 & 别名纠错】
        # ==========================================
        test_s = original_s.upper()
        
        # 1. 常见外盘现货/期货
        if test_s in ["XAU", "XAG", "OIL", "CL", "GC", "SI"]:
            original_s = f"hf_{test_s}"
            
        # 2. 常见全球指数 
        elif test_s in ["NKY", "N225", "N255", "DJI", "IXIC", "SPX", "HSI"]:
            if test_s in ["N225", "N255"]: 
                test_s = "NKY" 
            original_s = f"b_{test_s}"
            
        # 3. 国内期货智能识别 (1~3个字母 + 1~4个数字)
        elif re.match(r'^[A-Z]{1,3}\d{1,4}$', test_s) and not test_s.startswith(('SH', 'SZ', 'BJ')):
            original_s = f"nf_{original_s}"
            
        # 4. 【新增】：常见外汇对 (自动转为 fx_s_ + 小写)
        elif test_s in ["USDJPY", "EURUSD", "GBPUSD", "USDCNY", "USDCNH", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"]:
            original_s = f"fx_s{test_s.lower()}"  # 变成 fx_susdjpy
            
        # 5. 纯字母默认美股 (例如 AAPL -> gb_aapl)
        elif test_s.isalpha() and not original_s.lower().startswith(('b_', 'hf_', 'nf_', 'gb_', 'fx_')):
            original_s = f"gb_{original_s}"

        # ==========================================
        # 第二步：【绿色通道！拦截并规范化特殊接口】
        # ==========================================
        lower_s = original_s.lower()
        if lower_s.startswith(('nf_', 'hf_', 'b_', 'gb_', 'fx_')):
            
            # 【新增】：外汇 (fx_ 开头) 新浪要求全部小写即可
            if lower_s.startswith('fx_'):
                return lower_s
                
            parts = original_s.split('_', 1)
            if len(parts) == 2:
                prefix = parts[0].lower()
                code = parts[1]
                
                if prefix in ['nf', 'hf', 'b']:
                    return f"{prefix}_{code.upper()}"
                elif prefix == 'gb':
                    return f"{prefix}_{code.lower()}"
                    
            return original_s
        # ==========================================
        
        # ==========================================
        # 第三步：【原作者的 A 股处理逻辑兜底】
        # ==========================================
        s = lower_s
        s = re.sub(r'[^a-z0-9]', '', s)  
        if not s: return None
        if getattr(self, '_re_full', None) and self._re_full.match(s): return s
        if getattr(self, '_re_6', None) and self._re_6.match(s):
            if s[0] == '6' or s[0:2] == '90' or s[0] == '5':
                return 'sh' + s
            elif s[0] == '0' or s[0] == '3' or s[0] == '2' or s[0] == '1':
                return 'sz' + s
            elif s[0] == '8' or s[0] == '4' or s[0:2] == '92':
                return 'bj' + s
                
        return None

    def _collect_codes_from_list(self):
        codes = []
        seen = set()
        for i in range(self.list_codes.count()):
            txt = self.list_codes.item(i).text()
            norm = self._normalize_code_or_none(txt)
            if norm:
                if norm not in seen:
                    seen.add(norm)
                    codes.append(norm)
                # 写回规范化文本
                it = self.list_codes.item(i)
                if it.text() != norm:
                    self.list_codes.blockSignals(True)
                    it.setText(norm)
                    it.setData(Qt.UserRole, norm)
                    self.list_codes.blockSignals(False)
            else:
                # 回退到上次有效值
                it = self.list_codes.item(i)
                prev = it.data(Qt.UserRole)
                if prev:
                    self.list_codes.blockSignals(True)
                    it.setText(prev)
                    self.list_codes.blockSignals(False)
                else:
                    # 没有上次有效值则删除
                    self.list_codes.takeItem(i)
                    return self._collect_codes_from_list()
        return codes

    def _on_codes_changed(self, _item):
        codes = self._collect_codes_from_list()
        self.win.set_codes(codes)
        checked_codes = [
            self.list_codes.item(i).text().split()[0]
            for i in range(self.list_codes.count())
            if self.list_codes.item(i).checkState() == Qt.Checked
        ]
        self.win.set_checked_codes(checked_codes)

    def _add_code(self):
        it = QListWidgetItem("sh000001")
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        it.setCheckState(Qt.Unchecked)
        it.setData(Qt.UserRole, "sh000001")
        self.list_codes.addItem(it)
        self.list_codes.setCurrentItem(it)
        self.list_codes.editItem(it)
        self._on_codes_changed(it)

    def _del_code(self):
        row = self.list_codes.currentRow()
        if row >= 0:
            self.list_codes.takeItem(row)
            self._on_codes_changed(None)

    def _move_up(self):
        row = self.list_codes.currentRow()
        if row > 0:
            it = self.list_codes.takeItem(row)
            self.list_codes.insertItem(row-1, it)
            self.list_codes.setCurrentRow(row-1)
            self._on_codes_changed(None)

    def _move_down(self):
        row = self.list_codes.currentRow()
        if 0 <= row < self.list_codes.count()-1:
            it = self.list_codes.takeItem(row)
            self.list_codes.insertItem(row+1, it)
            self.list_codes.setCurrentRow(row+1)
            self._on_codes_changed(None)

    # —— 设置成本 —— #
    def _on_list_selection_changed(self):
        has = self.list_codes.currentItem() is not None
        self.btn_cost.setEnabled(has)
        self.btn_alert.setEnabled(has)

    def _on_list_context_menu(self, pos):
        item = self.list_codes.itemAt(pos)
        if item is None:
            return
        self.list_codes.setCurrentItem(item)
        menu = QMenu(self.list_codes)
        act = QAction("设置成本…", menu)
        act.triggered.connect(lambda: self._open_cost_dialog_for_item(item))
        menu.addAction(act)
        act_alert = QAction("封单预警…", menu)
        act_alert.triggered.connect(lambda: self._open_alert_dialog_for_item(item))
        menu.addAction(act_alert)
        menu.exec(self.list_codes.viewport().mapToGlobal(pos))

    def _open_cost_dialog_for_current(self):
        item = self.list_codes.currentItem()
        if item is not None:
            self._open_cost_dialog_for_item(item)

    def _open_cost_dialog_for_item(self, item: QListWidgetItem):
        raw = item.text().strip()
        code = self._normalize_code_or_none(raw) or raw.lower()
        if not code:
            return
        existing = {}
        try:
            existing = self.win.get_cost(code) or {}
        except Exception:
            existing = {}
        dlg = CostDialog(self, code,
                         float(existing.get("cost", 0.0) or 0.0),
                         int(existing.get("qty", 0) or 0))
        if dlg.exec() == QDialog.Accepted:
            cost, qty = dlg.get_values()
            try:
                self.win.set_cost(code, cost, qty)
            except Exception:
                pass

    def _open_alert_dialog_for_current(self):
        item = self.list_codes.currentItem()
        if item is not None:
            self._open_alert_dialog_for_item(item)

    def _open_alert_dialog_for_item(self, item: QListWidgetItem):
        raw = item.text().strip()
        code = self._normalize_code_or_none(raw) or raw.lower()
        if not code:
            return
        existing = []
        try:
            existing = self.win.get_alert(code) or []
        except Exception:
            existing = []
        dlg = AlertDialog(self, code, existing)
        if dlg.exec() == QDialog.Accepted:
            try:
                self.win.set_alert(code, dlg.get_thresholds())
            except Exception:
                pass

    # —— 其它槽 —— #
    def _on_interval_changed(self, idx):
        seconds = self.cmb_interval.currentData()
        if isinstance(seconds,int): 
            self.win.set_refresh_interval(seconds)

    def _on_reset_colors(self):
        try:
            self.win.reset_default_colors()
        except Exception:
            pass

    def _on_grid_toggled(self, checked: bool):
        self.win.set_grid_visible(bool(checked))

    def _on_header_toggled(self, checked: bool):
        self.win.set_header_visible(bool(checked))

    def _on_cb_changed(self, header: str, state: bool):
        self.win.set_flag(header, state)
        if header == "代码":
            self.cb_short_code.setEnabled(state)
        elif header == "名称":
            self.cmb_namelength.setEnabled(state)
    
    def _on_short_code_toggled(self, checked: bool):
        self.win.set_code_type(checked)

    def _on_name_length_changed(self, length: int):
        self.win.set_name_length(length)

    def _on_b1s1_display_changed(self, idx: int):
        try:
            val = self.cmb_b1s1_display.itemData(idx)
            if not val:
                return
            self.win.set_b1s1_display(val)
        except Exception:
            pass

    def _on_b1s1_toggled(self, state: bool):
        self.win.set_flag("买一", state)
        self.cmb_b1s1_display.setEnabled(state)

    def _on_symbols_changed(self):
        self.win.set_symbols(
            self.edit_sym_high.text(),
            self.edit_sym_low.text(),
            self.edit_sym_limit_up.text(),
            self.edit_sym_limit_down.text(),
            sym_rise=self.edit_sym_rise.text(),
            sym_fall=self.edit_sym_fall.text(),
        )

    def _on_dual_mode_toggled(self, checked: bool):
        self.win.set_dual_mode_enabled(bool(checked))
        self._g_simple_flags.setEnabled(bool(checked))
        self.cmb_leave_delay.setEnabled(bool(checked))

    def _on_leave_delay_changed(self, idx: int):
        ms = self.cmb_leave_delay.currentData()
        if isinstance(ms, int):
            self.win.set_leave_delay_ms(ms)

    def _on_anchor_changed(self, _checked: bool):
        try:
            anchor = 'right' if self.rb_anchor_right.isChecked() else 'left'
            self.win.set_anchor(anchor)
        except Exception:
            pass

    def _on_simple_cb_changed(self, header: str, state: bool):
        self.win.set_simple_flag(header, state)

    def _apply_tab_size(self, index: int):
        target_size = self.tab_sizes.get(index, QSize(480, 400))
        
        # 1. 临时解除主窗口所有的尺寸锁定，为变形做准备
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215) 

        # 2. 让后台页面“隐身”，彻底剥夺它们抢占空间的权利
        for i in range(self.tabs.count()):
            page = self.tabs.widget(i)
            if i == index:
                page.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            else:
                page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        
        # 3. 强制 QTabWidget 忘记刚才那个巨大的高度，重新计算
        self.tabs.updateGeometry()

        # 4. 强制一锤定音！直接锁死成你字典里写好的目标尺寸
        self.setFixedSize(target_size)
        
        # 【重要提示】：千万不要再加 self.adjustSize() 了，到这里完美收工！

    def pick_fg(self):
        c = QColorDialog.getColor(self.win.fg, self, "选择表格颜色")
        if c.isValid(): self.win.set_fg_color(c)
    def pick_up_color(self):
        c = QColorDialog.getColor(self.win.up_color, self, "选择涨颜色")
        if c.isValid(): self.win.set_up_color(c)
    def pick_down_color(self):
        c = QColorDialog.getColor(self.win.down_color, self, "选择跌颜色")
        if c.isValid(): self.win.set_down_color(c)
    def pick_bg(self):
        base = QColor(self.win.bg)
        base.setAlpha(255)
        c = QColorDialog.getColor(base, self, "选择背景颜色")
        if c.isValid(): self.win.set_bg_rgb_keep_alpha(c)
    def apply_bg_alpha(self, v): 
        self.lbl_bg_alpha.setText(f"{v}%")
        self.win.set_bg_alpha_percent(v)
    def apply_win_opacity(self, v): 
        self.lbl_win_opacity.setText(f"{v}%")
        self.win.set_window_opacity_percent(v)
    def apply_grid_alpha(self, v):
        self.lbl_grid_alpha.setText(f"{v}%")
        self.win.set_grid_alpha_percent(v)
    def apply_header_alpha(self, v):
        self.lbl_header_alpha.setText(f"{v}%")
        self.win.set_header_alpha_percent(v)
    def _on_family_changed(self, fam: str): 
        self.win.set_font_family(fam)
    def apply_font_size(self, v):
        self.lbl_font.setText(f"{v} pt")
        self.win.set_font_size(v)  # 同步 K 线缩放
    def _on_line_changed(self, v: int): 
        self.lbl_line.setText(f"+{v} px")
        self.win.set_line_extra(v)
    def _on_hotkey_changed(self):
        new_hotkey = self.edit_hotkey.keySequence().toString()
        try:
            self.win.update_hotkey(new_hotkey)
        except Exception:
            pass

    def _on_icon_changed(self, idx: int):
        try:
            val = self.cmb_icon.itemData(idx)
            if not val:
                return
            if hasattr(self, 'app') and self.app is not None:
                try:
                    self.app.set_app_icon(val)
                    # persist immediately
                    try:
                        self.app.save_now()
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    def _pick_custom_icon(self):
        try:
            path, _ = QFileDialog.getOpenFileName(self, "选择图标文件", os.path.expanduser('~'), "图标文件 (*.ico);;All Files (*)")
            if path:
                # append or find existing custom entry
                idx = self.cmb_icon.findData(path)
                if idx < 0:
                    self.cmb_icon.addItem('自定义', userData=path)
                    idx = self.cmb_icon.count()-1
                self.cmb_icon.setCurrentIndex(idx)
                # trigger change handler will call app.set_app_icon
        except Exception:
            pass

    # —— 涨跌异动报警槽 --
    def _on_price_alert_toggled(self, checked: bool):
        self.win.set_price_alert_enabled(bool(checked))

    def _add_pa_rule_item(self, rule: dict):
        """向规则列表添加一项。"""
        period = rule.get("period", 60)
        threshold = rule.get("threshold", 2.0)
        cooldown = rule.get("cooldown", 120)
        if period < 60:
            p_str = f"{period}秒"
        else:
            p_str = f"{period//60}分钟"
        if cooldown < 60:
            c_str = f"{cooldown}秒"
        else:
            c_str = f"{cooldown//60}分钟"
        label = f"周期 {p_str} | 阈值 {threshold:g}% | 冷却 {c_str}"
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, rule)
        self.list_pa_rules.addItem(item)

    def _on_pa_add_rule(self):
        """Read UI values and add a new rule."""
        try:
            period = self.cmb_pa_period.currentData()
            threshold_txt = self.edit_pa_threshold.text().strip()
            threshold = float(threshold_txt) if threshold_txt else 2.0
            cooldown = self.cmb_pa_cooldown.currentData()
            if not isinstance(period, int) or not isinstance(cooldown, int):
                return
            rule = {"period": period, "threshold": threshold, "cooldown": cooldown}
            self._add_pa_rule_item(rule)
            self.win.add_price_alert_rule(period, threshold, cooldown)
        except Exception:
            pass

    def _on_pa_del_rule(self):
        """Delete selected rule."""
        row = self.list_pa_rules.currentRow()
        if row >= 0:
            self.list_pa_rules.takeItem(row)
            self.win.remove_price_alert_rule(row)

    # —— 新高新低报警槽 --
    def _on_nhl_alert_toggled(self, checked: bool):
        self.win.set_new_high_low_alert_enabled(bool(checked))

    def _on_new_high_toggled(self, checked: bool):
        self.win.set_new_high_alert(bool(checked))

    def _on_new_low_toggled(self, checked: bool):
        self.win.set_new_low_alert(bool(checked))

    def _on_nhl_cooldown_changed(self, index: int):
        sec = self.cmb_nhl_cooldown.currentData()
        if isinstance(sec, int):
            self.win.set_new_high_low_cooldown(sec)

    # —— 涨跌停通知槽 --
    def _on_limit_alert_toggled(self, checked: bool):
        self.win.set_limit_alert_enabled(bool(checked))

    def _on_reach_limit_up_toggled(self, checked: bool):
        self.win.set_limit_alert_reach_up(bool(checked))

    def _on_reach_limit_down_toggled(self, checked: bool):
        self.win.set_limit_alert_reach_down(bool(checked))

    def _on_leave_limit_up_toggled(self, checked: bool):
        self.win.set_limit_alert_leave_up(bool(checked))

    def _on_leave_limit_down_toggled(self, checked: bool):
        self.win.set_limit_alert_leave_down(bool(checked))

    def _on_limit_alert_cooldown_changed(self, index: int):
        sec = self.cmb_limit_alert_cooldown.currentData()
        if isinstance(sec, int):
            self.win.set_limit_alert_cooldown(sec)
