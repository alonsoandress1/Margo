#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app_qt.py — Margo · Nelí · Sistema de Gestión de Restaurante
Framework: PyQt6 + QWebEngineView (Plotly embebido)
Ejecutar: python app_qt.py
Empaquetar: pyinstaller app_qt.spec
"""

import os, sys, json, tempfile, html as _html_mod, re as _re
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots as _msp


# ── PyQt6 ──────────────────────────────────────────────────────────────────────
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QTabWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QLabel, QSlider, QPushButton, QScrollArea, QFrame,
    QSizePolicy, QSplitter, QFileDialog, QMessageBox, QInputDialog,
    QDateEdit, QSpinBox, QDoubleSpinBox, QLineEdit,
    QComboBox, QListWidget, QListWidgetItem, QStackedWidget,
    QGroupBox, QCheckBox, QButtonGroup,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import (
    Qt, QDate, QUrl, QThread, pyqtSignal, QObject,
    QSize, QTimer, QRect,
)
from PyQt6.QtGui import (
    QFont, QIcon, QColor, QPalette, QPixmap, QAction,
    QFontDatabase,
)

# ── Business logic (sin Streamlit) ────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core

# ── Design System v3 — Nav Rail Architecture ──────────────────────────────────
QSS = """
/* ═══════════════════════════════════════════════════════════
   MARGO · NELÍ  —  Design System v3  —  2026
   Dark Warm Gourmet · Nav Rail · Agency-tier
   ═══════════════════════════════════════════════════════════ */

QMainWindow, QWidget {
    background-color: #09080C;
    color: #E8DDD0;
    font-family: "Segoe UI Variable", "Segoe UI", Calibri, sans-serif;
    font-size: 13px;
}

/* Nav Rail — color explícito en TODO (evita herencia rota por setStyleSheet locales) */
QWidget#navRail {
    background-color: #0E0C12;
    color: #E8DDD0;
}
QWidget#navRail QLabel {
    color: #C2B8AE;
    background: transparent;
}

/* ── Nav Rail items ────────────────────────────────────────── */
QPushButton#navItem {
    background: rgba(255,255,255,0.02);
    color: #A09A94;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 8px;
    padding: 10px 12px 10px 10px;
    text-align: left;
    font-size: 12.5px;
    font-weight: 400;
}
QPushButton#navItem:hover:!checked {
    background: rgba(201,169,122,0.08);
    color: #D4CBB8;
    border-left: 2px solid rgba(201,169,122,0.30);
}
QPushButton#navItem:checked {
    background: rgba(201,169,122,0.14);
    color: #C9A97A;
    font-weight: 600;
    border-left: 2px solid #C9A97A;
}
QPushButton#navItem:pressed {
    background: rgba(201,169,122,0.20);
}
QFrame#navDivider {
    background: rgba(255,255,255,0.07);
    border: none;
    max-height: 1px;
}
/* Especificidad 0,1,1 — pierde contra QWidget#navRail QLabel (0,1,2).
   Se necesita prefijo navRail para ganar: especificidad 0,2,2. */
QLabel#navSection,
QWidget#navRail QLabel#navSection {
    color: rgba(201,169,122,0.55);
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.20em;
    padding: 0px 2px 3px 2px;
}
QLabel#navMeta,
QWidget#navRail QLabel#navMeta {
    color: #8A847E;
    font-size: 11px;
}
QLabel#navMetaGold,
QWidget#navRail QLabel#navMetaGold {
    color: #B89860;
    font-size: 11px;
    font-weight: 600;
    font-family: Consolas, "Cascadia Code", "Courier New", monospace;
}
QPushButton#navSmallBtn {
    background: rgba(255,255,255,0.04);
    color: #8A847E;
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 11px;
}
QPushButton#navSmallBtn:hover {
    background: rgba(201,169,122,0.10);
    color: #C9A97A;
    border-color: rgba(201,169,122,0.22);
}
/* Widgets DENTRO del navRail heredan color explícito */
QWidget#navRail QSlider::groove:horizontal { height: 2px; background: rgba(255,255,255,0.10); border-radius:1px; }
QWidget#navRail QSlider::handle:horizontal { background:#C9A97A; width:14px; height:14px; margin:-6px 0; border-radius:7px; border:2px solid #0E0C12; }
QWidget#navRail QSlider::sub-page:horizontal { background: rgba(201,169,122,0.55); border-radius:1px; }
QWidget#navRail QDateEdit,
QWidget#navRail QSpinBox {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 6px;
    padding: 5px 8px;
    color: #C2B8AE;
}
QWidget#navRail QDateEdit:focus,
QWidget#navRail QSpinBox:focus {
    border-color: rgba(201,169,122,0.46);
}

/* ── Stacked / content area ───────────────────────────────── */
QStackedWidget { background: #09080C; border: none; }

/* ── Inner tabs (used only in TabProduccion Plan/Analisis) ── */
QTabWidget#innerTabs::pane { border: none; background: #09080C; }
QTabWidget#innerTabs > QTabBar {
    background: #0C0A07;
    border-bottom: 1px solid rgba(201,169,122,0.07);
}
QTabWidget#innerTabs > QTabBar::tab {
    background: transparent;
    color: rgba(240,232,220,0.35);
    padding: 10px 22px 9px;
    border: none;
    border-bottom: 2px solid transparent;
    font-size: 11px;
    letter-spacing: 0.04em;
    min-width: 70px;
}
QTabWidget#innerTabs > QTabBar::tab:selected {
    color: #E8D4B0;
    border-bottom: 2px solid rgba(201,169,122,0.68);
    background: rgba(201,169,122,0.05);
}
QTabWidget#innerTabs > QTabBar::tab:hover:!selected {
    color: rgba(240,232,220,0.60);
    background: rgba(240,232,220,0.016);
}
QTabWidget::pane { border: none; background: #09080C; }
QTabBar::tab {
    background: transparent; color: rgba(240,232,220,0.32);
    padding: 10px 20px; border: none;
    border-bottom: 2px solid transparent; font-size: 11px;
}
QTabBar::tab:selected {
    color: #C9A97A;
    border-bottom: 2px solid rgba(201,169,122,0.68);
    background: rgba(201,169,122,0.04);
}
QTabBar::tab:hover:!selected { color: rgba(240,232,220,0.56); }

/* ── Scrollbars ───────────────────────────────────────────── */
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical {
    background: transparent; width: 5px; border-radius: 3px; margin: 0;
}
QScrollBar::handle:vertical {
    background: rgba(201,169,122,0.20); border-radius: 3px; min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { height: 5px; background: transparent; }
QScrollBar::handle:horizontal {
    background: rgba(201,169,122,0.20); border-radius: 3px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ── Labels ───────────────────────────────────────────────── */
QLabel { color: #F0E8DC; background: transparent; }
QLabel#subtle {
    color: rgba(240,232,220,0.26); font-size: 9px;
    letter-spacing: 0.14em; font-weight: 600;
}
QLabel#muted  { color: rgba(240,232,220,0.48); }
QLabel#gold   { color: #C9A97A; font-weight: 600; }
QLabel#section {
    color: rgba(201,169,122,0.48);
    font-size: 8px; font-weight: 700;
    letter-spacing: 0.24em;
    padding: 12px 0 7px;
    border-bottom: 1px solid rgba(201,169,122,0.10);
}

/* ── Slider ───────────────────────────────────────────────── */
QSlider::groove:horizontal {
    height: 2px; background: rgba(240,228,200,0.09); border-radius: 1px;
}
QSlider::handle:horizontal {
    background: #C9A97A; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px; border: 2px solid #09080C;
}
QSlider::sub-page:horizontal {
    background: rgba(201,169,122,0.55); border-radius: 1px;
}

/* ── Buttons ──────────────────────────────────────────────── */
QPushButton {
    background: rgba(201,169,122,0.07);
    color: rgba(201,169,122,0.82);
    border: 1px solid rgba(201,169,122,0.18);
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 12px;
    letter-spacing: 0.02em;
}
QPushButton:hover {
    background: rgba(201,169,122,0.14);
    color: #C9A97A;
    border-color: rgba(201,169,122,0.36);
}
QPushButton:pressed { background: rgba(201,169,122,0.22); }
QPushButton#primary {
    background: rgba(201,169,122,0.16);
    color: #E8D4B0;
    border: 1px solid rgba(201,169,122,0.42);
    font-weight: 600; border-radius: 8px; padding: 9px 20px;
}
QPushButton#primary:hover { background: rgba(201,169,122,0.26); }
QPushButton#danger {
    background: rgba(200,80,70,0.09);
    color: rgba(220,110,100,0.80);
    border: 1px solid rgba(200,80,70,0.18);
    border-radius: 8px;
}
QPushButton#danger:hover {
    background: rgba(200,80,70,0.16); color: rgba(230,130,120,0.92);
}

/* ── Inputs ───────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit {
    background: rgba(240,228,200,0.04);
    border: 1px solid rgba(240,228,200,0.09);
    border-radius: 7px;
    padding: 6px 10px;
    color: #F0E8DC;
    selection-background-color: rgba(201,169,122,0.26);
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus {
    border: 1px solid rgba(201,169,122,0.46);
    background: rgba(201,169,122,0.04);
}
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { width: 8px; height: 8px; }
QComboBox QAbstractItemView {
    background: #1C1712;
    border: 1px solid rgba(201,169,122,0.16);
    border-radius: 7px;
    selection-background-color: rgba(201,169,122,0.13);
    color: #F0E8DC; outline: none;
}

/* ── Group boxes ──────────────────────────────────────────── */
QGroupBox {
    border: 1px solid rgba(240,228,200,0.07);
    border-radius: 10px;
    margin-top: 8px; padding-top: 8px;
    color: rgba(201,169,122,0.38);
    font-size: 8px; font-weight: 700; letter-spacing: 0.18em;
}
QGroupBox::title {
    subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 6px; left: 10px;
}

/* ── Dividers ─────────────────────────────────────────────── */
QFrame#divider {
    background: rgba(201,169,122,0.09);
    max-height: 1px; border: none;
}

/* ── List widget (Recetas) ────────────────────────────────── */
QListWidget {
    background: #09080C;
    border: 1px solid rgba(240,228,200,0.07);
    border-radius: 10px; outline: none;
}
QListWidget::item {
    padding: 9px 14px; color: rgba(240,232,220,0.56);
    font-size: 12px; border-radius: 5px;
}
QListWidget::item:selected {
    background: rgba(201,169,122,0.12); color: #C9A97A;
}
QListWidget::item:hover:!selected {
    background: rgba(240,228,200,0.028);
    color: rgba(240,232,220,0.84);
}

/* ── Checkbox ─────────────────────────────────────────────── */
QCheckBox { color: rgba(240,232,220,0.56); font-size: 11px; spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid rgba(240,228,200,0.18);
    border-radius: 3px; background: rgba(240,228,200,0.03);
}
QCheckBox::indicator:checked {
    background: rgba(201,169,122,0.30); border-color: rgba(201,169,122,0.52);
}
QCheckBox:hover { color: rgba(240,232,220,0.80); }

/* ── Recetas panel izquierdo ──────────────────────────────── */
/* ── Producción toolbar ───────────────────────────────────── */
QWidget#prodToolbar {
    background: #0A0906;
    border-bottom: 1px solid rgba(201,169,122,0.08);
}

/* ── Recetas panel izquierdo ──────────────────────────────── */
QWidget#recetasPanel {
    background: #0E0D12;
    border-right: 1px solid rgba(255,255,255,0.06);
    color: #E8DDD0;
}
QWidget#recetasPanel QLabel { color: #C2B8AE; background: transparent; }
QListWidget#recetasList {
    background: #09080C;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    color: #C2B8AE;
}
QListWidget#recetasList::item { padding: 7px 12px; font-size: 12px; border-radius: 5px; }
QListWidget#recetasList::item:selected { background: rgba(201,169,122,0.12); color: #C9A97A; }
QListWidget#recetasList::item:hover:!selected { background: rgba(255,255,255,0.028); color: #D8CFC4; }

/* ── Message box / Dialogs ────────────────────────────────── */
QMessageBox {
    background: #17130E;
    color: #F0E8DC;
}
QMessageBox QLabel {
    color: #F0E8DC;
    font-size: 13px;
    background: transparent;
}
QMessageBox QPushButton {
    min-width: 80px;
    padding: 7px 18px;
}

/* ── QSpinBox / QDoubleSpinBox sub-controls ─────────────────
   CRÍTICO: sin estos estilos Qt renderiza los botones ▲▼ como
   rectángulos blancos nativos sobre el fondo oscuro.
   ──────────────────────────────────────────────────────────── */
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    background: rgba(240,228,200,0.05);
    border-left: 1px solid rgba(240,228,200,0.08);
    border-bottom: 1px solid rgba(240,228,200,0.05);
    border-radius: 0 5px 0 0;
    width: 14px;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    background: rgba(240,228,200,0.05);
    border-left: 1px solid rgba(240,228,200,0.08);
    border-radius: 0 0 5px 0;
    width: 14px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background: rgba(201,169,122,0.12);
}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {
    background: rgba(201,169,122,0.22);
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    width: 5px; height: 4px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    width: 5px; height: 4px;
}

/* ── QDateEdit sub-controls ─────────────────────────────────
   Igual que QSpinBox: el botón del calendario aparece blanco
   si no se estiliza explícitamente.
   ──────────────────────────────────────────────────────────── */
QDateEdit::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    background: rgba(240,228,200,0.05);
    border: none;
    border-left: 1px solid rgba(240,228,200,0.08);
    border-radius: 0 5px 5px 0;
    width: 20px;
}
QDateEdit::drop-down:hover { background: rgba(201,169,122,0.12); }
QDateEdit::down-arrow {
    width: 7px; height: 5px;
}

"""

# ── HTML page template ─────────────────────────────────────────────────────────
# Cada tab renderiza su contenido como una página HTML completa.
# Los charts Plotly se embeben directamente.

# Plotly local — sin internet requerido
# Cuando corre como .exe: assets/ están en sys._MEIPASS (carpeta temporal de PyInstaller)
if getattr(sys, 'frozen', False):
    _ASSETS_DIR = os.path.join(sys._MEIPASS, "assets")
else:
    _ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

_PLOTLY_FILE  = "plotly-3.0.1.min.js"   # Plotly Python 6.x requiere JS 3.x
_PLOTLY_CDN   = "https://cdn.plot.ly/plotly-3.0.1.min.js"
_PLOTLY_LOCAL = os.path.join(_ASSETS_DIR, _PLOTLY_FILE)

# Base URL que apunta a assets/ para que el browser encuentre plotly.min.js
_BASE_URL = QUrl.fromLocalFile(_ASSETS_DIR + os.sep)

def _page(body: str, extra_css: str = "", include_plotly: bool = True) -> str:
    plotly_tag = f'<script src="{_PLOTLY_FILE}"></script>' if include_plotly else ''
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{plotly_tag}
<style>
/* ══════════════════════════════════════════════════════════════
   MARGÓ GOURMET — Design System v2.0
   Elevated Dark Gourmet · Agency-Tier · margo.cl brand identity
   ══════════════════════════════════════════════════════════════ */
:root {{
  /* Paleta cálida — interior de restaurante de lujo */
  --bg:    #090806;
  --s1:    #0F0C09;
  --s2:    #16120D;
  --s3:    #1E1912;
  --s4:    #272018;
  --s5:    #312820;

  /* Oro — acento de marca */
  --gold:       #C9A97A;
  --gold-hi:    #E8D4A8;
  --gold-dim:   #7A5E32;
  --gold-glow:  rgba(201,169,122,0.18);
  --g50: rgba(201,169,122,.50);
  --g25: rgba(201,169,122,.25);
  --g15: rgba(201,169,122,.15);
  --g08: rgba(201,169,122,.08);
  --g04: rgba(201,169,122,.04);

  /* Bordes cálidos */
  --b1: rgba(250,235,200,.052);
  --b2: rgba(250,235,200,.11);
  --b3: rgba(250,235,200,.20);

  /* Texto crema — no blanco frío */
  --t1: #F2EAE0;
  --t2: rgba(242,234,224,.64);
  --t3: rgba(242,234,224,.32);
  --t4: rgba(242,234,224,.14);

  /* Elevación — sistema de sombras */
  --shadow-xs: 0 2px 6px rgba(0,0,0,.32);
  --shadow-sm: 0 3px 16px rgba(0,0,0,.42), 0 1px 2px rgba(0,0,0,.45);
  --shadow-md: 0 6px 32px rgba(0,0,0,.52), 0 2px 4px rgba(0,0,0,.40);
  --shadow-lg: 0 12px 52px rgba(0,0,0,.62), 0 4px 8px rgba(0,0,0,.40);
  --inner-hi:  inset 0 1px 0 rgba(255,255,255,.072);
  --inner-gold: inset 0 1px 0 rgba(201,169,122,.15);
  --ring-gold:  0 0 0 1px rgba(201,169,122,.10);

  /* Acentos semánticos */
  --green: #6DCDA0;
  --red:   #E07870;
  --blue:  #7AACD8;
  --amber: #E8B96A;

  /* Tipografía — fuentes premium Windows (sin dependencia de red) */
  --serif: 'Palatino Linotype','Book Antiqua',Palatino,Cambria,Georgia,serif;
  --sans:  'Segoe UI','Segoe UI Light',Calibri,Corbel,system-ui,sans-serif;
  --mono:  Consolas,'Cascadia Code','Courier New',monospace;

  /* Radii */
  --r-xs:  6px;
  --r-sm:  10px;
  --r-md:  16px;
  --r-lg:  22px;

  /* Motion */
  --spring: cubic-bezier(0.32, 0.72, 0, 1);
  --snap:   cubic-bezier(0.16, 1, 0.3, 1);
}}

*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

/* Grain film texture — da tacto físico al diseño */
body::before {{
  content: '';
  position: fixed;
  inset: 0;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='4' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23g)'/%3E%3C/svg%3E");
  opacity: 0.028;
  pointer-events: none;
  z-index: 9997;
}}

body {{
  background:
    radial-gradient(ellipse 75% 55% at 5% 0%, rgba(201,169,122,0.065) 0%, transparent 60%),
    radial-gradient(ellipse 60% 50% at 95% 95%, rgba(140,100,50,0.042) 0%, transparent 55%),
    var(--bg);
  color: var(--t1);
  font-family: var(--sans);
  font-size: 13px;
  line-height: 1.58;
  padding: 32px 36px 48px;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
}}

/* ── Tipografía ─────────────────────────────────────────────── */
h1 {{
  font-family: var(--serif);
  font-weight: 300;
  font-size: 34px;
  letter-spacing: -0.015em;
  color: var(--t1);
  line-height: 1.08;
}}
h2 {{
  font-family: var(--serif);
  font-weight: 400;
  font-size: 26px;
  color: var(--t1);
  margin-bottom: 4px;
  line-height: 1.18;
  letter-spacing: -0.01em;
}}
h2 em {{
  font-style: italic;
  color: var(--gold);
}}
.page-sub {{
  font-size: 11px;
  color: var(--t3);
  letter-spacing: 0.07em;
  margin-bottom: 32px;
  display: flex;
  align-items: center;
  gap: 10px;
}}
.page-sub::before {{
  content: '';
  display: inline-block;
  width: 28px;
  height: 1px;
  background: linear-gradient(90deg, var(--gold-dim), transparent);
  flex-shrink: 0;
}}

/* ── Section labels ─────────────────────────────────────────── */
.section-label {{
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.26em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.50);
  margin: 34px 0 18px;
}}
.section-label::before {{
  content: '';
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--gold);
  opacity: 0.55;
  flex-shrink: 0;
  box-shadow: 0 0 8px rgba(201,169,122,0.55), 0 0 16px rgba(201,169,122,0.22);
}}
.section-label::after {{
  content: '';
  flex: 1; height: 1px;
  background: linear-gradient(90deg, rgba(201,169,122,0.18), transparent);
}}

/* ── KPI Cards ──────────────────────────────────────────────── */
.kpi-row {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
  gap: 16px;
  margin-bottom: 32px;
}}
.kpi {{
  background: linear-gradient(145deg, var(--s2) 0%, var(--s3) 60%, var(--s2) 100%);
  border: 1px solid var(--b1);
  border-radius: var(--r-md);
  padding: 22px 24px 20px;
  position: relative;
  overflow: hidden;
  box-shadow: var(--inner-hi), var(--shadow-sm);
  transition:
    transform 0.45s var(--spring),
    box-shadow 0.45s var(--spring);
}}
.kpi:hover {{
  transform: translateY(-3px);
  box-shadow: var(--inner-gold), var(--shadow-md), var(--ring-gold);
}}
.kpi::after {{
  content: '';
  position: absolute;
  top: 0; left: 18px; right: 18px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(201,169,122,0.30), transparent);
  opacity: 0.80;
}}
.kpi-label {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--t3);
  margin-bottom: 14px;
}}
.kpi-value {{
  font-family: var(--serif);
  font-size: 32px;
  font-weight: 400;
  line-height: 1;
  color: var(--gold);
  letter-spacing: -0.01em;
}}
.kpi-value.neutral  {{ color: var(--t1); }}
.kpi-value.positive {{ color: var(--green); }}
.kpi-value.negative {{ color: var(--red); }}
.kpi-sub {{
  font-size: 11px;
  color: var(--t3);
  margin-top: 12px;
  font-variant-numeric: tabular-nums;
  line-height: 1.45;
}}

/* ── Chart containers ───────────────────────────────────────── */
.chart-box {{
  background: linear-gradient(160deg, var(--s1) 0%, var(--s2) 100%);
  border: 1px solid var(--b1);
  border-radius: var(--r-md);
  margin-bottom: 20px;
  overflow: hidden;
  box-shadow: var(--inner-hi), var(--shadow-sm);
}}
.chart-title {{
  font-family: var(--serif);
  font-size: 16px;
  font-weight: 400;
  color: var(--t2);
  padding: 18px 22px 0;
  letter-spacing: 0.01em;
}}

/* ── Day cards — design v3 (sin arc SVG) ───────────────────── */
.cards-row {{
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 32px;
}}
.day-card {{
  background: linear-gradient(160deg, var(--s2) 0%, var(--s3) 100%);
  border: 1px solid var(--b1);
  border-radius: var(--r-lg);
  padding: 18px 20px 16px;
  min-width: 172px;
  flex: 1;
  max-width: 240px;
  position: relative;
  overflow: hidden;
  animation: card-in 0.55s var(--snap) both;
  box-shadow: var(--inner-hi), var(--shadow-sm);
  transition: transform 0.38s var(--spring), box-shadow 0.38s var(--spring);
}}
.day-card:hover {{
  transform: translateY(-3px);
  box-shadow: var(--inner-gold), var(--shadow-md), var(--ring-gold);
}}
.day-card::before {{
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--gold-dim), transparent);
  opacity: 0; transition: opacity 0.3s;
}}
.day-card.promo {{
  border-color: rgba(201,169,122,0.24);
  background: linear-gradient(160deg,
    rgba(201,169,122,0.10) 0%, rgba(201,169,122,0.04) 100%);
}}
.day-card.promo::before {{ opacity: 1; }}

/* head row */
.dc-head {{
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}}
.dc-dow {{
  font-size: 8.5px; font-weight: 700;
  letter-spacing: 0.20em; color: var(--t3);
  text-transform: uppercase; line-height: 1;
}}
.dc-date {{
  font-family: var(--serif);
  font-size: 22px; font-weight: 300;
  color: var(--t2); line-height: 1; text-align: right;
}}
.dc-date small {{
  font-size: 11px; color: var(--t3);
  display: block; font-weight: 400; margin-top: 2px;
}}

/* hero number */
.dc-hero-num {{
  font-family: var(--mono);
  font-size: 46px; font-weight: 500;
  line-height: 1; letter-spacing: -0.03em;
  text-align: center;
  padding: 4px 0 2px;
}}
.dc-hero-sub {{
  font-size: 8px; letter-spacing: 0.18em;
  color: var(--t3); text-transform: uppercase;
  text-align: center; margin-bottom: 14px;
}}

/* bottom divider + total */
.dc-sep {{
  height: 1px; background: var(--b1); margin-bottom: 11px;
}}
.dc-foot {{
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 5px;
}}
.dc-foot-num {{
  font-family: var(--mono);
  font-size: 18px; color: var(--t2);
  letter-spacing: -0.02em;
}}
.dc-foot-lbl {{
  font-size: 10px; color: var(--t3);
  letter-spacing: 0.08em;
}}
.dc-chips {{
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 10px;
}}
.promo-chip {{
  background: rgba(201,169,122,0.12);
  color: var(--gold);
  border: 1px solid rgba(201,169,122,0.25);
  font-size: 8.5px;
  font-weight: 600;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  border-radius: 20px;
}}
.dc-feriado-chip {{
  background: rgba(122,172,216,0.10);
  color: #7AACD8;
  border: 1px solid rgba(122,172,216,0.20);
  font-size: 8.5px;
  padding: 2px 8px;
  border-radius: 20px;
}}
.dc-warn-chip {{
  background: rgba(232,185,106,0.10);
  color: var(--amber);
  border: 1px solid rgba(232,185,106,0.20);
  font-size: 8.5px;
  padding: 2px 8px;
  border-radius: 20px;
}}

/* ── Production table ───────────────────────────────────────── */
.prod-wrap {{ overflow-x: auto; }}
.prod-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}}
.prod-table thead tr {{
  border-bottom: 1px solid var(--b2);
}}
.prod-table thead th {{
  padding: 12px 16px;
  text-align: left;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.20em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.42);
}}
.prod-table tbody tr {{
  transition: background 0.2s var(--snap);
}}
.prod-table tbody tr:hover {{
  background: rgba(201,169,122,0.038);
}}
.prod-table td {{
  padding: 8px 16px;
  border-bottom: 1px solid rgba(250,235,200,0.026);
}}
.td-name {{ color: var(--t1); }}
.td-name.r1 {{ color: var(--gold); font-weight: 500; }}
.td-name.r2 {{ color: rgba(201,169,122,.72); }}
.td-name.r3 {{ color: rgba(201,169,122,.50); }}
.td-name.dim {{ color: var(--t3); }}
.td-num {{
  text-align: right;
  font-family: var(--mono);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}}
.td-mu    {{ color: var(--t2); }}
.td-buf   {{ color: rgba(124,201,154,.75); }}
.td-total {{ font-weight: 500; }}
.td-bar   {{ width: 28%; padding: 7px 14px; }}
.bar-track {{
  height: 3px;
  background: rgba(240,220,180,0.07);
  border-radius: 2px;
  overflow: hidden;
}}
.bar-fill {{ height: 3px; border-radius: 2px; }}
.r {{ text-align: right; }}

/* ── Coverage table ─────────────────────────────────────────── */
.cov-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  transition: background 0.2s var(--snap);
}}
.cov-table th {{
  padding: 10px 14px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.42);
  border-bottom: 1px solid var(--b2);
}}
.cov-table td {{
  padding: 8px 14px;
  border-bottom: 1px solid rgba(250,235,200,0.026);
}}

/* ── Ventas tables ──────────────────────────────────────────── */
.ventas-tbl {{ width: 100%; border-collapse: collapse; }}
.ventas-tbl th {{
  padding: 10px 14px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.42);
  border-bottom: 1px solid var(--b2);
}}
.ventas-tbl td {{
  padding: 10px 14px;
  border-bottom: 1px solid rgba(250,235,200,0.026);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}}
.ventas-tbl tbody tr {{
  transition: background 0.2s var(--snap);
}}
.ventas-tbl tbody tr:hover {{
  background: rgba(201,169,122,0.035);
}}

/* ── Diagnóstico cards ──────────────────────────────────────── */
.diag-card {{
  border-left: 2px solid;
  padding: 13px 18px;
  margin-bottom: 12px;
  background: rgba(250,235,200,0.025);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
  box-shadow: var(--shadow-xs);
  transition: background 0.2s var(--snap);
}}
.diag-card:hover {{ background: rgba(250,235,200,0.038); }}
.diag-title {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.20em;
  text-transform: uppercase;
  color: var(--t3);
  margin-bottom: 5px;
}}
.diag-body {{
  font-size: 13px;
  color: var(--t1);
  line-height: 1.45;
}}

/* ── Compras ────────────────────────────────────────────────── */
.cat-group {{ margin-bottom: 22px; }}
.cat-header {{
  display: flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(90deg, var(--s3), var(--s2));
  padding: 11px 20px;
  border-radius: var(--r-sm) var(--r-sm) 0 0;
  font-size: 8.5px;
  font-weight: 700;
  letter-spacing: 0.20em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.58);
  border: 1px solid var(--b1);
  border-bottom: none;
}}
.ing-row {{
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 11px 20px;
  border: 1px solid var(--b1);
  border-top: none;
  background: var(--s2);
  transition: background 0.2s var(--snap);
}}
.ing-row:hover {{ background: var(--s3); }}
.ing-row:last-child {{ border-radius: 0 0 var(--r-sm) var(--r-sm); }}
.ing-name {{
  flex: 3;
  font-size: 13px;
  color: var(--t1);
}}
.ing-qty {{
  flex: 1;
  font-family: var(--mono);
  font-size: 13px;
  font-weight: 500;
  color: var(--gold);
  text-align: right;
  font-variant-numeric: tabular-nums;
}}
.ing-unit {{ flex: 1; font-size: 11px; color: var(--t3); }}
.ing-costo {{
  flex: 1.5;
  font-family: var(--mono);
  font-size: 12px;
  color: rgba(201,169,122,.55);
  text-align: right;
  font-variant-numeric: tabular-nums;
}}
.ing-urgency {{
  flex: 2;
  font-size: 11px;
  padding: 3px 10px;
  border-radius: 20px;
  text-align: center;
  font-weight: 500;
  letter-spacing: 0.02em;
}}

/* ── Historial ──────────────────────────────────────────────── */
.hist-table {{ width: 100%; border-collapse: collapse; font-size: 12.5px; }}
.hist-table th {{
  padding: 10px 16px;
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.42);
  border-bottom: 1px solid var(--b2);
}}
.hist-table td {{
  padding: 8px 16px;
  border-bottom: 1px solid rgba(250,235,200,0.026);
  font-variant-numeric: tabular-nums;
}}
.hist-table tbody tr {{
  transition: background 0.2s var(--snap);
}}
.hist-table tbody tr:hover {{ background: rgba(201,169,122,0.035); }}
.hist-cat {{
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(201,169,122,0.38);
  background: var(--s2);
  padding: 7px 16px;
}}

/* ── Utility ────────────────────────────────────────────────── */
.mono {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.gold {{ color: var(--gold); }}
.dim  {{ color: var(--t3); }}
.positive {{ color: var(--green); }}
.negative {{ color: var(--red); }}
.two-col   {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-bottom: 18px; }}
.three-col {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; margin-bottom: 18px; }}

/* ── Animations ─────────────────────────────────────────────── */
@keyframes card-in {{
  from {{ opacity: 0; transform: translateY(20px) scale(0.97); filter: blur(3px); }}
  to   {{ opacity: 1; transform: none; filter: blur(0); }}
}}
@keyframes fade-in {{
  from {{ opacity: 0; transform: translateY(14px); filter: blur(2px); }}
  to   {{ opacity: 1; transform: none; filter: blur(0); }}
}}

body > * {{ animation: fade-in 0.55s var(--snap) both; }}

.page-logo {{
  position: fixed;
  top: 20px;
  right: 28px;
  opacity: 0.55;
  pointer-events: none;
  z-index: 100;
  transition: opacity 0.3s;
}}
.page-logo:hover {{ opacity: 0.85; }}
.page-logo img {{
  height: 28px;
  width: auto;
  filter: brightness(1.15) contrast(0.9);
}}
{extra_css}
</style>
</head>
<body>
<div class="page-logo"><img src="margo_logo_web.png" alt="Margó"></div>
{body}
</body>
</html>"""

# ── Section-tabs helper ────────────────────────────────────────────────────────
# sections: list of (label, slug, content_html)  active: index of default tab

_STABS_CSS_JS = """<style>
.stabs{display:flex;gap:6px;margin:20px 0 0;
  border-bottom:1px solid rgba(255,255,255,.07);
  flex-wrap:nowrap;overflow-x:auto;overflow-y:hidden;
  scrollbar-width:none}
.stabs::-webkit-scrollbar{display:none}
.stab{background:transparent;border:1px solid rgba(255,255,255,.08);border-bottom:none;
  border-radius:6px 6px 0 0;color:rgba(255,255,255,.42);font-size:11px;font-weight:700;
  letter-spacing:.08em;padding:7px 16px;cursor:pointer;white-space:nowrap;flex-shrink:0;
  transition:background .15s,color .15s}
.stab:hover{background:rgba(255,255,255,.04);color:rgba(255,255,255,.7)}
.stab.son{background:rgba(255,255,255,.06);color:var(--stab-clr,#C9A97A);
  border-color:rgba(255,255,255,.13);border-bottom:2px solid var(--stab-clr,#C9A97A)}
.spanel{animation:spfade .18s ease}
@keyframes spfade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
</style>
<script>
function stab(slug,btn){
  document.querySelectorAll('.spanel').forEach(p=>p.style.display='none');
  document.querySelectorAll('.stab').forEach(b=>b.classList.remove('son'));
  document.getElementById('sp-'+slug).style.display='block';
  btn.classList.add('son');
}
</script>"""

_ACCENT_DEFAULT = '#C9A97A'

def _slug(text):
    import re as _re
    s = (text.lower()
         .replace(' ','_').replace('á','a').replace('é','e')
         .replace('í','i').replace('ó','o').replace('ú','u').replace('ñ','n')
         .replace('ü','u').replace('ç','c').replace('à','a').replace('è','e'))
    return _re.sub(r'[^a-z0-9_]', '_', s)

def _stabs(sections, active=0):
    # sections: list of (label, slug, content) or (label, slug, content, color)
    tabs = '<div class="stabs">'
    panels = ''
    for i, sec in enumerate(sections):
        label, slug, content = sec[0], sec[1], sec[2]
        color = sec[3] if len(sec) > 3 else _ACCENT_DEFAULT
        cls = ' son' if i == active else ''
        tabs += (f'<button class="stab{cls}" style="--stab-clr:{color}" '
                 f'onclick="stab(\'{slug}\',this)">{label}</button>')
        disp = 'block' if i == active else 'none'
        panels += f'<div id="sp-{slug}" class="spanel" style="display:{disp}">{content}</div>'
    tabs += '</div>'
    return _STABS_CSS_JS + tabs + panels


# ── Chart → HTML helper ────────────────────────────────────────────────────────

def _fig_html(fig, height: int = 400) -> str:
    fig.update_layout(height=height)
    return fig.to_html(full_html=False, include_plotlyjs=False,
                       config={'displayModeBar': False, 'responsive': True})

# ── AppState: parámetros globales compartidos entre tabs ───────────────────────

class AppState(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        cfg = core.load_config()
        self.folder       = core.get_folder()
        self.k_factor     = float(cfg.get("k_factor", core.K_SAFETY))
        self.horizon      = int(cfg.get("horizon", core.DEFAULT_HORIZON))
        _saved_date       = cfg.get("start_date")
        try:
            self.start_date = datetime.strptime(_saved_date, "%Y-%m-%d").date() if _saved_date else None
        except (ValueError, TypeError):
            self.start_date = None
        if not self.start_date or self.start_date < datetime.now().date():
            self.start_date = datetime.now().date() + timedelta(days=1)
        # Fechas excluidas del modelo (configurables por el usuario)
        self.excluded_extra: set = set()
        for s in cfg.get("excluded_extra", []):
            try:
                self.excluded_extra.add(datetime.strptime(s, "%Y-%m-%d"))
            except (ValueError, TypeError):
                pass
        # Locales configurados: {nombre: ruta_reportes}
        self.locales: dict = cfg.get("locales", {})
        self.history      : dict = {}
        self.model        : dict = {}
        self.df           = None
        self.name_to_sku  : dict = {}
        self.ventas_df    = None
        self._recetas_raw : dict = {}
        self.recetas      : dict = {}
        self.load_errors  : list = []

    def _save_prefs(self):
        cfg = core.load_config()
        cfg["reportes_folder"] = self.folder
        cfg["k_factor"]        = self.k_factor
        cfg["horizon"]         = self.horizon
        cfg["start_date"]      = self.start_date.strftime("%Y-%m-%d") if self.start_date else None
        cfg["excluded_extra"]  = sorted(d.strftime("%Y-%m-%d") for d in self.excluded_extra)
        cfg["locales"]         = self.locales
        core.save_config(cfg)

    def toggle_excluded(self, date: datetime):
        """Agrega o quita una fecha de la lista de excluidos del modelo."""
        if date in self.excluded_extra:
            self.excluded_extra.discard(date)
        else:
            self.excluded_extra.add(date)
        self._save_prefs()

    def reload(self):
        self.load_errors = []
        self.history     = core.load_history(self.folder, self.load_errors, self.excluded_extra)
        self.model       = core.build_model(self.history)
        self.df          = core.build_df(self.history)
        self.name_to_sku = core.build_name_to_sku(self.history)
        self.ventas_df   = core.load_ventas_df()
        self._recetas_raw, self.recetas = core.load_recetas()
        self.changed.emit()

# ── Web view base ──────────────────────────────────────────────────────────────

class WebTab(QWebEngineView):
    """QWebEngineView con método render(html) y soporte offline."""
    def __init__(self, parent=None):
        super().__init__(parent)
        s = self.settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        self.setZoomFactor(1.0)
        # Fondo oscuro antes de que cargue el HTML — evita el flash blanco al renderizar
        self.page().setBackgroundColor(QColor(9, 8, 12))

    def render(self, html: str):
        # Base URL apunta a assets/ → el browser resuelve plotly-2.26.0.min.js localmente
        self.setHtml(html, _BASE_URL)

# ── Reload worker (background thread) ─────────────────────────────────────────

class _ReloadWorker(QThread):
    """Ejecuta state.reload() en hilo secundario para no bloquear la UI."""
    finished = pyqtSignal()

    def __init__(self, folder: str, excluded_extra: set | None = None):
        super().__init__()
        self.folder          = folder
        self.excluded_extra  = excluded_extra or set()
        self.result: dict    = {}
        self.errors: list    = []

    def run(self):
        self.errors = []
        history      = core.load_history(self.folder, self.errors, self.excluded_extra)
        model        = core.build_model(history)
        df           = core.build_df(history)
        name_to_sku  = core.build_name_to_sku(history)
        ventas_df    = core.load_ventas_df()
        recetas_raw, recetas = core.load_recetas()
        self.result = {
            'history': history, 'model': model, 'df': df,
            'name_to_sku': name_to_sku, 'ventas_df': ventas_df,
            'recetas_raw': recetas_raw, 'recetas': recetas,
        }
        self.finished.emit()


# ── Sidebar ────────────────────────────────────────────────────────────────────

class NavRail(QWidget):
    """Nav Rail lateral — reemplaza Sidebar + QTabWidget anidados."""
    page_changed = pyqtSignal(int)

    _PAGES = [
        ("🍽", "Producción",  0),
        ("🛒", "Compras",     1),
        None,
        ("💰", "Ventas",      2),
        ("📈", "Tendencias",  3),
        ("⭐", "AMEX",        4),
        ("📋", "Historial",   5),
        ("💲", "Costos",      7),
        None,
        ("📖", "Recetas",     6),
    ]

    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setFixedWidth(208)
        self.setObjectName("navRail")
        self._btns: dict[int, QPushButton] = {}
        self._build()
        state.changed.connect(self._refresh_stats)

    # ── Build ──────────────────────────────────────────────────────────────
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 14)
        lay.setSpacing(1)

        # Logo
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "assets", "margo_logo_web.png")
        logo_lbl = QLabel()
        if os.path.exists(logo_path):
            pix = QPixmap(logo_path)
            pix = pix.scaledToWidth(116, Qt.TransformationMode.SmoothTransformation)
            logo_lbl.setPixmap(pix)
            logo_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            logo_lbl.setStyleSheet("padding:2px 4px 10px 4px;")
        else:
            logo_lbl.setText("Margo · Nelí")
            logo_lbl.setStyleSheet(
                "font-family:'Palatino Linotype',Georgia,serif;"
                "font-size:15px;font-style:italic;color:#C9A97A;padding:2px 4px 10px 4px;")
        lay.addWidget(logo_lbl)

        # ── Selector de local ──────────────────────────────────────────────────
        self._add_divider(lay)
        sec_loc = QLabel("LOCAL"); sec_loc.setObjectName("navSection")
        lay.addWidget(sec_loc)
        loc_row = QHBoxLayout(); loc_row.setSpacing(4)
        self._local_combo = QComboBox()
        self._local_combo.setFixedHeight(26)
        self._local_combo.currentIndexChanged.connect(self._on_local_change)
        loc_row.addWidget(self._local_combo, 1)
        btn_add_loc = QPushButton("＋"); btn_add_loc.setObjectName("navSmallBtn")
        btn_add_loc.setFixedSize(26, 26); btn_add_loc.setToolTip("Agregar local")
        btn_add_loc.clicked.connect(self._on_add_local)
        loc_row.addWidget(btn_add_loc)
        lay.addLayout(loc_row)
        self._rebuild_local_combo()
        self._add_divider(lay)

        # Nav items — el grupo debe vivir como atributo para no ser garbage-collected
        self._btn_grp = QButtonGroup(self)
        self._btn_grp.setExclusive(True)
        for item in self._PAGES:
            if item is None:
                lay.addSpacing(4)
                d = QFrame(); d.setObjectName("navDivider")
                d.setFrameShape(QFrame.Shape.HLine); d.setFixedHeight(1)
                lay.addWidget(d); lay.addSpacing(4)
            else:
                ico, lbl, idx = item
                btn = QPushButton(f"  {ico}  {lbl}")
                btn.setObjectName("navItem")
                btn.setCheckable(True)
                btn.setFixedHeight(38)
                btn.clicked.connect(lambda _=False, i=idx: self.page_changed.emit(i))
                self._btn_grp.addButton(btn, idx)
                self._btns[idx] = btn
                lay.addWidget(btn)

        if 0 in self._btns:
            self._btns[0].setChecked(True)

        lay.addSpacing(8)

        # Stats
        self._add_divider(lay)
        sec_m = QLabel("MODELO"); sec_m.setObjectName("navSection")
        lay.addWidget(sec_m)
        self.lbl_stats = QLabel("—")
        self.lbl_stats.setObjectName("navMeta")
        self.lbl_stats.setWordWrap(True)
        lay.addWidget(self.lbl_stats)

        self._add_divider(lay)

        # Parámetros
        sec_p = QLabel("PARÁMETROS"); sec_p.setObjectName("navSection")
        lay.addWidget(sec_p)

        # k_factor oculto por defecto — evita cambios accidentales por usuarios no técnicos
        self._avanz_btn = QPushButton("⚙ Avanzado")
        self._avanz_btn.setObjectName("navSmallBtn")
        self._avanz_btn.setFixedHeight(22)
        self._avanz_btn.setCheckable(True)
        self._avanz_btn.setChecked(False)
        lay.addWidget(self._avanz_btn)

        self._avanz_panel = QWidget()
        avanz_lay = QVBoxLayout(self._avanz_panel)
        avanz_lay.setContentsMargins(0, 4, 0, 0)
        avanz_lay.setSpacing(3)
        k_row = QHBoxLayout(); k_row.setSpacing(6)
        k_l = QLabel("Buffer k"); k_l.setObjectName("navMeta")
        k_row.addWidget(k_l); k_row.addStretch()
        self.k_val_lbl = QLabel(f"{self.state.k_factor:.1f}σ")
        self.k_val_lbl.setObjectName("navMetaGold")
        k_row.addWidget(self.k_val_lbl)
        avanz_lay.addLayout(k_row)
        self.k_slider = QSlider(Qt.Orientation.Horizontal)
        self.k_slider.setRange(5, 25)
        self.k_slider.setValue(int(self.state.k_factor * 10))
        self.k_slider.valueChanged.connect(self._on_k)
        avanz_lay.addWidget(self.k_slider)
        self._avanz_panel.setVisible(False)
        self._avanz_btn.toggled.connect(self._avanz_panel.setVisible)
        lay.addWidget(self._avanz_panel)
        lay.addSpacing(5)

        date_lbl = QLabel("Inicio pronóstico"); date_lbl.setObjectName("navMeta")
        lay.addWidget(date_lbl)
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setMinimumDate(QDate.currentDate())
        self.date_edit.setDate(QDate.fromString(
            self.state.start_date.strftime('%Y-%m-%d'), 'yyyy-MM-dd'))
        self.date_edit.dateChanged.connect(self._on_date)
        self.date_edit.setFixedHeight(28)
        lay.addWidget(self.date_edit)

        # Atajos de fecha — el uso más frecuente es hoy o mañana
        _date_row = QHBoxLayout(); _date_row.setSpacing(4)
        _btn_hoy = QPushButton("Hoy"); _btn_hoy.setObjectName("navSmallBtn"); _btn_hoy.setFixedHeight(22)
        _btn_man = QPushButton("Mañana"); _btn_man.setObjectName("navSmallBtn"); _btn_man.setFixedHeight(22)
        _btn_hoy.clicked.connect(lambda: self.date_edit.setDate(QDate.currentDate()))
        _btn_man.clicked.connect(lambda: self.date_edit.setDate(QDate.currentDate().addDays(1)))
        _date_row.addWidget(_btn_hoy); _date_row.addWidget(_btn_man); _date_row.addStretch()
        lay.addLayout(_date_row)
        lay.addSpacing(5)

        hor_row = QHBoxLayout(); hor_row.setSpacing(6)
        hor_l = QLabel("Días a producir"); hor_l.setObjectName("navMeta")
        hor_row.addWidget(hor_l); hor_row.addStretch()
        self.hor_spin = QSpinBox()
        self.hor_spin.setRange(1, 7)
        self.hor_spin.setValue(self.state.horizon)
        self.hor_spin.setFixedWidth(52); self.hor_spin.setFixedHeight(26)
        self.hor_spin.valueChanged.connect(self._on_horizon)
        hor_row.addWidget(self.hor_spin)
        lay.addLayout(hor_row)

        self._add_divider(lay)

        self.lbl_folder = QLabel(os.path.basename(self.state.folder) or self.state.folder)
        self.lbl_folder.setObjectName("navMeta"); self.lbl_folder.setWordWrap(True)
        self.lbl_folder.setFont(QFont("Consolas", 9))
        lay.addWidget(self.lbl_folder)
        btn_row = QHBoxLayout(); btn_row.setSpacing(5)
        btn_f = QPushButton("📁 Carpeta"); btn_f.setObjectName("navSmallBtn")
        btn_f.setFixedHeight(26); btn_f.clicked.connect(self._on_folder)
        self._btn_r = QPushButton("🔄 Recargar"); self._btn_r.setObjectName("navSmallBtn")
        self._btn_r.setFixedHeight(26); self._btn_r.clicked.connect(self._on_reload)
        btn_row.addWidget(btn_f); btn_row.addWidget(self._btn_r)
        lay.addLayout(btn_row)
        lay.addSpacing(8)

        self.semaforo = QLabel()
        self.semaforo.setWordWrap(True)
        self.semaforo.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.semaforo)
        lay.addStretch()

        self._refresh_stats()

    def _add_divider(self, lay):
        lay.addSpacing(7)
        d = QFrame(); d.setObjectName("navDivider")
        d.setFrameShape(QFrame.Shape.HLine); d.setFixedHeight(1)
        lay.addWidget(d); lay.addSpacing(7)

    # ── Slots ──────────────────────────────────────────────────────────────
    def _on_k(self, v):
        self.state.k_factor = v / 10
        self.k_val_lbl.setText(f"{self.state.k_factor:.1f}σ")
        self.state._save_prefs()
        self.state.changed.emit()

    def _on_date(self, qd):
        self.state.start_date = qd.toPyDate()
        self.state._save_prefs()
        self.state.changed.emit()

    def _on_horizon(self, v):
        self.state.horizon = v
        self.state._save_prefs()
        self.state.changed.emit()

    def _on_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Carpeta de reportes", self.state.folder)
        if folder:
            self.state.folder = folder
            self.state._save_prefs()
            self.lbl_folder.setText(os.path.basename(folder) or folder)
            self._on_reload()

    def _on_reload(self):
        if getattr(self, '_worker', None) and self._worker.isRunning():
            return  # evita race condition si ya hay un reload en curso
        self._btn_r.setEnabled(False)
        self._btn_r.setText("⏳ Cargando…")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._worker = _ReloadWorker(self.state.folder, self.state.excluded_extra)
        self._worker.finished.connect(self._on_reload_done)
        self._worker.start()

    def _on_reload_done(self):
        QApplication.restoreOverrideCursor()
        self._btn_r.setEnabled(True)
        self._btn_r.setText("🔄 Recargar")
        w = self._worker
        s = self.state
        s.load_errors  = w.errors
        s.history      = w.result['history']
        s.model        = w.result['model']
        s.df           = w.result['df']
        s.name_to_sku  = w.result['name_to_sku']
        s.ventas_df    = w.result['ventas_df']
        s._recetas_raw = w.result['recetas_raw']
        s.recetas      = w.result['recetas']
        s.changed.emit()
        self._refresh_stats()
        if not s.history:
            if w.errors:
                detail = "\n".join(f"  • {e}" for e in w.errors[:8])
                QMessageBox.warning(self, "Sin datos",
                    f"No se pudieron cargar archivos.\n\n{detail}\n\n"
                    "Selecciona la carpeta correcta en el panel lateral.")
            else:
                QMessageBox.warning(self, "Sin datos",
                    "No se encontraron archivos de informe.\n"
                    "Selecciona la carpeta correcta en el panel lateral.")

    # ── Locales ────────────────────────────────────────────────────────────────
    def _rebuild_local_combo(self):
        self._local_combo.blockSignals(True)
        self._local_combo.clear()
        locs = self.state.locales
        if not locs:
            # Si no hay locales configurados, mostrar la carpeta activa
            name = os.path.basename(self.state.folder) or self.state.folder
            self._local_combo.addItem(name, self.state.folder)
        else:
            for name, path in locs.items():
                self._local_combo.addItem(name, path)
            # Seleccionar el local cuya ruta coincide con la carpeta activa
            for i in range(self._local_combo.count()):
                if self._local_combo.itemData(i) == self.state.folder:
                    self._local_combo.setCurrentIndex(i)
                    break
        self._local_combo.blockSignals(False)

    def _on_local_change(self, idx: int):
        path = self._local_combo.itemData(idx)
        if path and path != self.state.folder:
            self.state.folder = path
            self.state._save_prefs()
            self._on_reload()

    def _on_add_local(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Carpeta de reportes del nuevo local", self.state.folder)
        if not folder:
            return
        name, ok = QInputDialog.getText(
            self, "Nombre del local",
            "Ingresa el nombre de este local\n(ej: Chicureo, La Dehesa):")
        if not ok or not name.strip():
            return
        name = name.strip()
        self.state.locales[name] = folder
        self.state.folder = folder
        self.state._save_prefs()
        self._rebuild_local_combo()
        self._on_reload()

    def set_active(self, idx: int):
        if idx in self._btns:
            self._btns[idx].setChecked(True)

    def _refresh_stats(self):
        h = self.state.history
        errs = self.state.load_errors
        if not h:
            self.lbl_stats.setText("Sin datos cargados")
        else:
            ds = sorted(h)
            n_p = sum(1 for d in h if core.day_type(d) == 'Dom-Promo')
            last = ds[-1]
            days_old = (datetime.now() - last).days
            txt = (f"{len(h)} días  ·  {n_p} promo\n"
                   f"{ds[0].strftime('%d/%m/%y')} - {last.strftime('%d/%m/%y')}")
            if days_old > 2:
                txt += f"\n⚠ Datos con {days_old}d de antigüedad"
            elif errs:
                txt += f"\n⚠ {len(errs)} archivo(s) con problemas"
            # Indicar cuántos días están excluidos manualmente
            n_excl = len(self.state.excluded_extra)
            if n_excl:
                txt += f"\n✕ {n_excl} día(s) excluido(s) del modelo"
            self.lbl_stats.setText(txt)

        vdf = self.state.ventas_df
        if vdf is not None and not vdf.empty:
            _anio_act = datetime.now().year
            _anio_ant = _anio_act - 1
            vm  = vdf.groupby(['año','mes'])['bruto'].sum().reset_index()
            v25 = vm[vm['año']==_anio_ant].set_index('mes')['bruto']
            v26 = vm[vm['año']==_anio_act].set_index('mes')['bruto']
            common = sorted(set(v25.index) & set(v26.index))
            if len(common) >= 3:
                ult3 = common[-3:]
                yoys = [(v26[m]-v25[m])/v25[m]*100 if v25[m] else 0 for m in ult3]
                tend = sum(yoys)/len(yoys)
                if tend >= 0:      clr, lbl = '#5CE8D4', 'Crecimiento'
                elif tend >= -5:   clr, lbl = '#F59E0B', 'Estable'
                elif tend >= -12:  clr, lbl = '#F7A8D0', 'En baja'
                else:              clr, lbl = '#EF4444', 'Alerta'
                MN = ['','Ene','Feb','Mar','Abr','May','Jun',
                      'Jul','Ago','Sep','Oct','Nov','Dic']
                det = '  '.join(
                    f"{MN[m]}: {'+' if yoys[i]>=0 else ''}{yoys[i]:.0f}%"
                    for i, m in enumerate(ult3))
                self.semaforo.setText(
                    f'<div style="background:rgba(201,169,122,0.05);'
                    f'border:1px solid rgba(201,169,122,0.12);border-radius:8px;'
                    f'padding:9px 11px;margin-top:2px">'
                    f'<div style="font-size:8px;letter-spacing:.14em;font-weight:700;'
                    f'color:rgba(201,169,122,.34)">VENTAS YoY</div>'
                    f'<div style="font-size:13px;color:{clr};font-weight:600;margin:3px 0 1px">'
                    f'● {lbl}  {"+" if tend>=0 else ""}{tend:.1f}%</div>'
                    f'<div style="font-size:10px;color:rgba(242,234,224,.26);'
                    f'letter-spacing:.01em">{det}</div></div>')
        else:
            self.semaforo.setText("")

# ── Tab: PRODUCCIÓN ────────────────────────────────────────────────────────────

class TabProduccion(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state        = state
        self._day_details : list = []
        self._totals      : dict = {}
        self._dish_stats  : dict = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Toolbar (solo visible en sub-tab Plan del día)
        self._toolbar = QWidget()
        self._toolbar.setObjectName("prodToolbar")
        tl = QHBoxLayout(self._toolbar)
        tl.setContentsMargins(14, 6, 14, 6)
        self._btn_export = QPushButton("⬇  Exportar Excel")
        self._btn_export.setFixedHeight(30)
        self._btn_export.setFixedWidth(165)
        self._btn_export.clicked.connect(self._export_excel)
        self._btn_pdf = QPushButton("🖨  Imprimir / PDF")
        self._btn_pdf.setFixedHeight(30)
        self._btn_pdf.setFixedWidth(155)
        self._btn_pdf.clicked.connect(self._export_pdf)

        # Selector de categoría — solo visible en sub-tab Análisis
        self._cat_combo = QComboBox()
        self._cat_combo.addItems(core.CAT_ORDER)
        self._cat_combo.setCurrentText('Fondo')
        self._cat_combo.setFixedHeight(30)
        self._cat_combo.setVisible(False)
        self._cat_combo.currentTextChanged.connect(self._on_analisis_cat)

        # Selector de categoría del Plan — persiste qué categoría ve el chef
        self._cat_combo_plan = QComboBox()
        self._cat_combo_plan.addItem("Todas las categorías", "")
        for _c in core.CAT_ORDER:
            self._cat_combo_plan.addItem(_c, _c)
        self._cat_combo_plan.setFixedHeight(30)
        self._cat_combo_plan.setVisible(True)
        self._cat_combo_plan.currentIndexChanged.connect(lambda _: self.refresh())

        tl.addStretch()
        tl.addWidget(self._cat_combo_plan)
        tl.addSpacing(8)
        tl.addWidget(self._cat_combo)
        tl.addSpacing(8)
        tl.addWidget(self._btn_pdf)
        tl.addWidget(self._btn_export)
        lay.addWidget(self._toolbar)

        # Sub-tabs: Plan del día | Análisis del modelo
        self.sub = QTabWidget()
        self.sub.setObjectName("innerTabs")
        self.sub.setTabPosition(QTabWidget.TabPosition.North)
        def _on_sub_change(i):
            self._btn_export.setVisible(i == 0)
            self._btn_pdf.setVisible(i == 0)
            self._cat_combo_plan.setVisible(i == 0)
            self._cat_combo.setVisible(i == 1)
        self.sub.currentChanged.connect(_on_sub_change)

        self.plan_view     = WebTab()
        self.analisis_view = WebTab()

        self.sub.addTab(self.plan_view,     "🍽  Plan del día")
        self.sub.addTab(self.analisis_view, "📊  Análisis del modelo")
        lay.addWidget(self.sub)

        state.changed.connect(self.refresh)
        self.refresh()

    def _on_analisis_cat(self, cat: str):
        if cat in core.CAT_ORDER:
            self.refresh()

    def _export_pdf(self):
        default = f"Plan_{self.state.start_date.strftime('%d-%m-%Y')}.pdf"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar PDF del plan", default, "PDF (*.pdf)")
        if not path:
            return
        def _on_pdf_done(ok):
            if ok:
                QMessageBox.information(self, "PDF guardado",
                    f"Archivo guardado correctamente:\n{path}")
            else:
                QMessageBox.warning(self, "Error al guardar PDF",
                    "No se pudo generar el PDF.")
        page = self.plan_view.page()
        try:
            page.pdfPrintingFinished.disconnect()
        except Exception:
            pass
        page.pdfPrintingFinished.connect(_on_pdf_done)
        page.printToPdf(path)

    def _export_excel(self):
        if not self._day_details:
            return
        data = core.make_excel_bytes(
            self._day_details, self._totals, self._dish_stats,
            len(self.state.history), self.state.k_factor)
        if not data:
            QMessageBox.warning(self, "Exportar", "openpyxl no está instalado.")
            return
        default = f"Produccion_{datetime.now().strftime('%d-%m-%Y')}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar pronóstico Excel", default, "Excel (*.xlsx)")
        if path:
            try:
                with open(path, 'wb') as f:
                    f.write(data)
                QMessageBox.information(self, "Exportado",
                    f"Archivo guardado correctamente:\n{path}")
            except PermissionError:
                QMessageBox.warning(self, "Error al exportar",
                    "No se pudo guardar el archivo.\n"
                    "Asegúrate de que no esté abierto en Excel.")
            except Exception as e:
                QMessageBox.warning(self, "Error al exportar", str(e))

    def refresh(self):
        s = self.state
        if not s.history:
            self.plan_view.render(_page("<h2>Sin datos</h2><p>Selecciona una carpeta de reportes.</p>"))
            return

        start = datetime.combine(s.start_date, datetime.min.time())
        day_details, totals, dish_stats = core.make_forecast(
            s.model, start, s.horizon, s.k_factor)
        self._day_details = day_details
        self._totals      = totals
        self._dish_stats  = dish_stats
        dish_coverage = core.compute_dish_coverage(
            s.history, day_details, s.model, s.k_factor)

        # Plan del día — day cards + tablas por categoría
        all_ff  = [sum(core.dish_fc(st, s.k_factor) for (_, c), st in dm.items() if c == 'Fondo')
                   for _, _, dm, _ in day_details]
        all_pf  = [sum(core.dish_fc(st, s.k_factor) for st in dm.values())
                   for _, _, dm, _ in day_details]
        max_ff  = max(all_ff) if all_ff else 1

        cards_html = '<div class="cards-row">'
        for idx, ((d, dt, dm, fb), ff, pf) in enumerate(zip(day_details, all_ff, all_pf)):
            cards_html += core.day_card_html(d, dt, ff, pf, max_ff, fb, idx)
        cards_html += '</div>'

        # Tabs por categoría — respeta el filtro del combo del toolbar
        sel_plan_cat = self._cat_combo_plan.currentData() or ""
        cat_sections = []
        for cat in core.CAT_ORDER:
            if sel_plan_cat and cat != sel_plan_cat:
                continue
            items = {k: v for k, v in totals.items() if k[1] == cat and v >= 1}
            if not items:
                continue
            color   = core.CAT_HEX.get(cat, core.GOLD)
            sl      = _slug(cat)
            content = (f'<div class="section-label" style="margin-top:12px">{cat.upper()}</div>'
                       f'<div class="chart-box">'
                       f'{core.prod_table_html(items, dish_stats, color, dish_coverage)}'
                       f'</div>')
            cat_sections.append((cat.upper(), sl, content, color))

        n_dias_lbl = f"{s.horizon} día" + ("s" if s.horizon > 1 else "")
        cat_lbl    = f" — {sel_plan_cat}" if sel_plan_cat else ""
        body = f"""
        <div style="display:flex;align-items:baseline;gap:16px;margin-bottom:4px">
          <h2 style="margin:0">Plan de Producción{cat_lbl}</h2>
          <span style="font-size:18px;color:#C9A97A;font-family:'Palatino Linotype',Georgia,serif">
            {core.fecha_es(start)}</span>
          <span style="font-size:12px;color:rgba(255,255,255,.3)">
            {n_dias_lbl} · {len(s.history)} días en modelo</span>
        </div>
        {cards_html}
        {_stabs(cat_sections)}
        """
        self.plan_view.render(_page(body))

        # Análisis del modelo — cobertura + variabilidad + barras forecast
        cov_data = core.compute_buffer_coverage(s.history, s.model)
        K_COLS   = [0.0, 0.5, 0.7, 1.0, 1.5, 2.0]

        # Tabla de cobertura
        cov_rows = ''
        for dt in sorted(cov_data):
            d = cov_data[dt]
            cov_rows += f'<tr><td style="color:rgba(255,255,255,.7);padding:7px 10px">{dt}</td>'
            cov_rows += f'<td style="padding:7px 10px;color:rgba(255,255,255,.4)">{d["n"]} días</td>'
            for k in K_COLS:
                pct = d['coverage'].get(k, 0)
                if pct >= 90:   c = 'rgba(100,230,170,.8)'
                elif pct >= 75: c = '#F59E0B'
                else:           c = 'rgba(215,75,65,.8)'
                bold = ' font-weight:600;' if abs(k - s.k_factor) < 0.05 else ''
                cov_rows += f'<td style="text-align:center;padding:7px 10px;color:{c};{bold}">{pct}%</td>'
            cov_rows += '</tr>'

        k_headers = ''.join(
            f'<th style="text-align:center;padding:6px 10px;font-size:10px;'
            f'letter-spacing:.06em;color:{"#C9A97A" if abs(k-s.k_factor)<.05 else "rgba(255,255,255,.32)"};">'
            f'k={k:.1f}</th>'
            for k in K_COLS)

        cov_table = f"""
        <div class="chart-box" style="padding:0">
          <table style="width:100%;border-collapse:collapse;font-size:12px">
            <thead><tr>
              <th style="text-align:left;padding:8px 10px;font-size:9px;
                letter-spacing:.1em;color:rgba(255,255,255,.32);
                border-bottom:1px solid rgba(255,255,255,.06)">TIPO DE DÍA</th>
              <th style="padding:8px 10px;font-size:9px;letter-spacing:.1em;
                color:rgba(255,255,255,.32);
                border-bottom:1px solid rgba(255,255,255,.06)">Muestras</th>
              {k_headers.replace('padding:6px','border-bottom:1px solid rgba(255,255,255,.06);padding:8px')}
            </tr></thead>
            <tbody>{cov_rows}</tbody>
          </table>
        </div>"""

        # Charts: variabilidad + forecast bars — categoría elegida en el combo Qt
        sel_cat  = self._cat_combo.currentText() or 'Fondo'
        fig_var  = core.chart_variability(s.model, sel_cat)
        fig_bars = core.chart_forecast_bars(totals, dish_stats, sel_cat, horizon=s.horizon)

        analisis_tabs = _stabs([
            ('COBERTURA',    'cob', cov_table),
            ('VARIABILIDAD', 'var', f'<div class="chart-box">{_fig_html(fig_var,  420)}</div>'),
            ('FORECAST',     'fc',  f'<div class="chart-box">{_fig_html(fig_bars, 420)}</div>'),
        ])
        analisis_body = f'<h2>Análisis del Modelo — {sel_cat}</h2>{analisis_tabs}'
        self.analisis_view.render(_page(analisis_body))


# ── Tab: COMPRAS ───────────────────────────────────────────────────────────────

class TabCompras(WebTab):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        state.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.state
        if not s.history or not s.recetas:
            self.render(_page(
                '<h2>Compras</h2>'
                '<p style="color:var(--t3)">Sin datos de historia o recetas configuradas.</p>'))
            return

        start = datetime.combine(s.start_date, datetime.min.time())
        _, totals, _ = core.make_forecast(s.model, start, s.horizon, s.k_factor)

        # Agregar ingredientes
        DAYS_ORDER = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado']
        _DNUM = {d: i for i, d in enumerate(DAYS_ORDER)}
        _NDIA = {v: k for k, v in _DNUM.items()}

        def _prox_despacho(dias):
            if not dias: return 99, '—'
            hoy_wd = datetime.now().weekday()
            wds = sorted(_DNUM[d] for d in dias if d in _DNUM)
            if not wds: return 99, '—'
            for wd in wds:
                if wd >= hoy_wd: return wd - hoy_wd, _NDIA[wd]
            return 7 - hoy_wd + wds[0], _NDIA[wds[0]]

        _ing: dict = {}
        for (dname, _), total_qty in totals.items():
            sku = s.name_to_sku.get(dname)
            if not sku or sku not in s.recetas: continue
            for ing in s.recetas[sku].get('ingredientes', []):
                _nombre = ing.get('nombre', '').strip()
                if not _nombre:
                    continue
                k_i = f"{_nombre}||{ing.get('unidad','g')}"
                pu  = float(ing.get('precio_unitario', 0) or 0)
                if k_i not in _ing:
                    _ing[k_i] = {**ing, 'nombre': _nombre, 'total': 0.0,
                                 'precio_unitario': pu,
                                 'dias_despacho': list(ing.get('dias_despacho', []))}
                _ing[k_i]['total'] += float(ing.get('cantidad', 0) or 0) * total_qty
                # Actualizar con cualquier precio no-cero encontrado
                if pu:
                    _ing[k_i]['precio_unitario'] = pu
                dd = ing.get('dias_despacho', [])
                _ing[k_i]['dias_despacho'] = sorted(
                    set(_ing[k_i]['dias_despacho']) | set(dd),
                    key=lambda x: _DNUM.get(x, 9))

        if not _ing:
            self.render(_page(
                '<h2>Compras</h2>'
                '<p style="color:var(--t3)">Sin recetas configuradas con ingredientes.</p>'))
            return

        # Totales globales
        total_costo = sum(
            d['total'] * d['precio_unitario']
            for d in _ing.values() if d.get('precio_unitario')
        )
        n_sin_precio = sum(1 for d in _ing.values() if not d.get('precio_unitario'))

        def _fmt_clp(v):
            return f"${v:,.0f}".replace(',', '.')

        # KPI strip superior
        costo_html = _fmt_clp(total_costo) if total_costo else '—'
        sin_p_html  = (f'<span style="color:#FBBF24"> · {n_sin_precio} sin precio</span>'
                       if n_sin_precio else '')
        kpi_strip = f"""
        <div style="display:flex;gap:14px;margin-bottom:20px">
          <div class="kpi" style="flex:2;padding:16px 20px">
            <div class="kpi-label">COSTO ESTIMADO DEL PEDIDO</div>
            <div class="kpi-value" style="font-size:32px;color:#C9A97A">{costo_html}</div>
            <div class="kpi-sub">{core.fecha_es(start)} · {s.horizon} día(s){sin_p_html}</div>
          </div>
          <div class="kpi" style="flex:1;padding:16px 20px">
            <div class="kpi-label">INSUMOS</div>
            <div class="kpi-value">{len(_ing)}</div>
          </div>
        </div>"""

        # Agrupar por categoría
        by_cat: dict = {}
        for ki, d in sorted(_ing.items(), key=lambda x: x[1].get('categoria','ZZ')):
            cat = d.get('categoria', 'Sin categoría')
            by_cat.setdefault(cat, []).append(d)

        CAT_ICONS = {
            'Proteínas del mar': '🐟', 'Mariscos': '🦐', 'Carnes': '🥩',
            'Aves': '🍗', 'Frutas': '🍋', 'Lácteos': '🥛', 'Huevos': '🥚',
            'Pasta y cereales': '🌾', 'Repostería': '🍰', 'Helados': '🍦',
            'Aceites y condimentos': '🫙',
        }

        compras_sections = []
        for cat, ings in sorted(by_cat.items()):
            icon = CAT_ICONS.get(cat, '📦')
            cat_costo = sum(d['total'] * d['precio_unitario']
                            for d in ings if d.get('precio_unitario'))
            cat_costo_html = (f'<span style="float:right;color:rgba(201,169,122,.6);'
                              f'font-size:12px">{_fmt_clp(cat_costo)}</span>'
                              if cat_costo else '')
            rows_html = ''
            for d in sorted(ings, key=lambda x: -x['total']):
                n_dias, nombre_dia = _prox_despacho(d.get('dias_despacho', []))
                if n_dias == 0:   urg_bg, urg_clr, urg_txt = '#A5D6A7', '#1B4332', f'⚡ HOY ({nombre_dia})'
                elif n_dias == 1: urg_bg, urg_clr, urg_txt = '#FBBF24', '#1C1305', f'📋 MAÑANA ({nombre_dia})'
                elif n_dias <= 3: urg_bg, urg_clr, urg_txt = '#7EB8F7', '#0C1A2E', f'📦 {n_dias}d ({nombre_dia})'
                elif n_dias < 99: urg_bg, urg_clr, urg_txt = 'rgba(255,255,255,.08)', 'rgba(255,255,255,.7)', f'🗓 {n_dias}d ({nombre_dia})'
                else:             urg_bg, urg_clr, urg_txt = 'rgba(255,255,255,.04)', 'rgba(255,255,255,.35)', '—'

                qty     = d['total']
                qty_txt = f"{qty:,.1f}" if qty < 1000 else f"{qty:,.0f}"
                pu      = d.get('precio_unitario', 0)
                costo_i = qty * pu if pu else None
                costo_i_html = (
                    f'<span class="ing-costo">{_fmt_clp(costo_i)}</span>'
                    if costo_i else
                    '<span class="ing-costo" style="color:rgba(255,255,255,.2)">—</span>')

                prov = d.get('proveedor', '')
                prov_html = (f'<span style="font-size:10px;color:rgba(255,255,255,.3);'
                             f'flex:1.5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
                             f'{prov}</span>' if prov else
                             '<span style="flex:1.5"></span>')
                rows_html += (
                    f'<div class="ing-row">'
                    f'<span class="ing-name">{_html_mod.escape(d["nombre"])}</span>'
                    f'<span class="ing-qty">{qty_txt}</span>'
                    f'<span class="ing-unit">{d.get("unidad","g")}</span>'
                    f'{prov_html}'
                    f'{costo_i_html}'
                    f'<span class="ing-urgency" style="background:{urg_bg};color:{urg_clr}">'
                    f'{urg_txt}</span></div>')
            slug = _slug(cat)
            panel_html = (f'<div class="cat-header" style="margin-top:4px">'
                          f'{icon} {cat}{cat_costo_html}</div>{rows_html}')
            compras_sections.append((f'{icon} {cat.upper()}', slug, panel_html))

        # Banner si hay platos del pronóstico sin receta configurada
        n_en_forecast   = sum(1 for (dname, _) in totals)
        n_sin_receta    = sum(1 for (dname, _) in totals
                              if not (s.name_to_sku.get(dname) and
                                      s.name_to_sku.get(dname) in s.recetas))
        banner = ''
        if n_sin_receta:
            banner = (f'<div style="background:rgba(251,191,36,.08);border:1px solid rgba(251,191,36,.25);'
                      f'border-radius:10px;padding:10px 16px;margin-bottom:16px;font-size:12px;'
                      f'color:rgba(251,191,36,.9)">'
                      f'⚠ <b>{n_sin_receta} de {n_en_forecast} platos</b> del pronóstico no tienen '
                      f'receta configurada y están excluidos de esta lista. '
                      f'El costo estimado es <b>parcial</b>.</div>')

        body = f'<h2>Lista de Compras</h2>{banner}{kpi_strip}{_stabs(compras_sections)}'
        self.render(_page(body))


# ── Tab: VENTAS ────────────────────────────────────────────────────────────────

class TabVentas(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        toolbar = QWidget(); toolbar.setObjectName("prodToolbar")
        tl = QHBoxLayout(toolbar); tl.setContentsMargins(14, 6, 14, 6)
        self._btn_exp_ventas = QPushButton("⬇  Exportar ventas Excel")
        self._btn_exp_ventas.setFixedHeight(30)
        self._btn_exp_ventas.clicked.connect(self._export_ventas)
        tl.addStretch(); tl.addWidget(self._btn_exp_ventas)
        lay.addWidget(toolbar)

        self._web = WebTab()
        lay.addWidget(self._web, 1)
        state.changed.connect(self.refresh)
        self.refresh()

    def render(self, html: str):
        self._web.render(html)

    def _export_ventas(self):
        vdf = self.state.ventas_df
        if vdf is None or vdf.empty:
            QMessageBox.warning(self, "Sin datos", "No hay datos de ventas cargados.")
            return
        try:
            import io, openpyxl
            buf = io.BytesIO()
            vdf.to_excel(buf, index=False, engine='openpyxl')
            default = f"Ventas_{datetime.now().strftime('%Y')}.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self, "Exportar ventas", default, "Excel (*.xlsx)")
            if path:
                with open(path, 'wb') as f:
                    f.write(buf.getvalue())
                QMessageBox.information(self, "Exportado",
                    f"Archivo guardado correctamente:\n{path}")
        except ImportError:
            QMessageBox.warning(self, "Exportar", "openpyxl no está instalado.")
        except Exception as e:
            QMessageBox.warning(self, "Error al exportar", str(e))

    def refresh(self):
        vdf = self.state.ventas_df
        if vdf is None or vdf.empty:
            self.render(_page('<h2>Ventas</h2><p style="color:var(--t3)">No se encontraron archivos en Ventas/</p>'))
            return

        vm  = vdf.groupby(['año','mes'])['bruto'].sum().reset_index().rename(columns={'bruto':'total'})
        vc  = vdf.groupby(['año','mes','categoria'])['bruto'].sum().reset_index()
        vq  = vdf.groupby(['año','mes','categoria'])['cantidad'].sum().reset_index()
        vd  = vdf.groupby(['año','mes'])['descuento'].sum().reset_index()

        v25 = vm[vm['año']==2025].set_index('mes')['total']
        v26 = vm[vm['año']==2026].set_index('mes')['total']
        common = sorted(set(v25.index) & set(v26.index))
        if not common:
            self.render(_page('<h2>Ventas</h2><p style="color:var(--t3)">No hay meses comparables.</p>'))
            return

        tot25 = v25[common].sum(); tot26 = v26[common].sum()
        delta = (tot26-tot25)/tot25*100 if tot25 else 0
        yoy   = {m: (v26[m]-v25[m])/v25[m]*100 if v25[m] else 0 for m in common}
        best_m  = max(yoy, key=yoy.get)
        worst_m = min(yoy, key=yoy.get)
        arr, acol = core._delta_arrow(delta)
        MN = core.MESES_NOM_V

        # KPIs — bento asimétrico
        n_pos = sum(1 for v in yoy.values() if v >= 0)
        ult3 = sorted(common)[-3:]
        tend3 = sum(yoy[m] for m in ult3) / max(1, len(ult3))
        tc = '#5CE8D4' if tend3 >= 0 else '#F7A8D0'
        tend_lbl = ('Crecimiento' if tend3 >= 0 else
                    'Estable' if tend3 >= -5 else
                    'En baja' if tend3 >= -12 else 'Alerta')

        kpis = f"""
<div style="display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:28px">
  <!-- KPI principal — ancho 2/3 -->
  <div class="kpi" style="display:flex;flex-direction:column;justify-content:space-between;padding:24px 28px">
    <div>
      <div class="kpi-label">INGRESOS 2026</div>
      <div class="kpi-value" style="color:#C9A97A;font-size:42px;margin:8px 0 4px">
        {core._fmt_clp(tot26)}</div>
      <div class="kpi-sub" style="font-size:12px">
        Ene–{MN[max(common)]} &nbsp;·&nbsp; {len(common)} meses comparados<br>
        2025: {core._fmt_clp(tot25)} &nbsp;
        <span style="color:{acol};font-weight:600">{arr} {abs(delta):.1f}%</span>
      </div>
    </div>
    <div style="display:flex;gap:20px;margin-top:18px;padding-top:14px;
                border-top:1px solid rgba(255,255,255,0.05)">
      <div>
        <div style="font-size:8px;letter-spacing:.16em;color:var(--t3);font-weight:700">
          MEJOR · {MN[best_m]}</div>
        <div style="font-size:16px;color:#5CE8D4;font-weight:600;margin-top:2px">
          +{yoy[best_m]:.1f}%</div>
      </div>
      <div>
        <div style="font-size:8px;letter-spacing:.16em;color:var(--t3);font-weight:700">
          PEOR · {MN[worst_m]}</div>
        <div style="font-size:16px;color:#F7A8D0;font-weight:600;margin-top:2px">
          {yoy[worst_m]:.1f}%</div>
      </div>
      <div>
        <div style="font-size:8px;letter-spacing:.16em;color:var(--t3);font-weight:700">
          EN VERDE</div>
        <div style="font-size:16px;color:var(--t2);font-weight:500;margin-top:2px">
          {n_pos}/{len(common)}</div>
      </div>
    </div>
  </div>
  <!-- Diagnóstico rápido — 1/3 -->
  <div class="kpi" style="padding:20px 20px;display:flex;flex-direction:column;gap:12px">
    <div style="font-size:8px;letter-spacing:.18em;font-weight:700;color:var(--t3)">
      DIAGNOSTICO</div>
    <div>
      <div style="font-size:11px;color:var(--t3);margin-bottom:3px">Tendencia 3 meses</div>
      <div style="font-size:22px;color:{tc};font-weight:700;line-height:1">
        {"+" if tend3>=0 else ""}{tend3:.1f}%</div>
      <div style="font-size:11px;color:{tc};opacity:.7">{tend_lbl}</div>
    </div>
    <div style="height:1px;background:rgba(255,255,255,0.05)"></div>
    <div>
      <div style="font-size:11px;color:var(--t3);margin-bottom:2px">
        {MN[best_m]} 26: {core._fmt_clp(v25[best_m])} → {core._fmt_clp(v26[best_m])}</div>
      <div style="font-size:11px;color:var(--t3)">
        {MN[worst_m]} 26: {core._fmt_clp(v25[worst_m])} → {core._fmt_clp(v26[worst_m])}</div>
    </div>
  </div>
</div>"""

        # Gráfico barras mensual
        fig_main = go.Figure()
        all25 = sorted(v25.index); all26 = sorted(v26.index)
        fig_main.add_trace(go.Bar(name='2025', x=[MN[m] for m in all25],
            y=[v25[m]/1e6 for m in all25], marker_color='rgba(201,169,122,0.30)'))
        fig_main.add_trace(go.Bar(name='2026', x=[MN[m] for m in all26],
            y=[v26[m]/1e6 for m in all26], marker_color='#C9A97A'))
        fig_main.add_trace(go.Scatter(name='YoY %', x=[MN[m] for m in common],
            y=[yoy[m] for m in common], yaxis='y2', mode='lines+markers+text',
            line=dict(color='rgba(255,255,255,.5)', width=1.5, dash='dot'),
            marker=dict(size=8, color=['#5CE8D4' if yoy[m]>=0 else '#F7A8D0' for m in common]),
            text=[f"{yoy[m]:+.0f}%" for m in common], textposition='top center',
            textfont=dict(size=10)))
        main_layout = {**core.PLOTLY_BASE}
        main_layout.update(barmode='group', bargap=0.25, height=380,
            title=dict(text='Ventas Mensuales — 2025 vs 2026', **core.PLOTLY_BASE['title']),
            yaxis=dict(**core.PLOTLY_BASE['yaxis'], ticksuffix='M', tickformat=',.0f'),
            yaxis2=dict(overlaying='y', side='right', tickformat='+.0f', ticksuffix='%',
                        showgrid=False, zeroline=True,
                        zerolinecolor='rgba(255,255,255,.08)',
                        tickfont=dict(size=10)),
            margin=dict(l=16, r=64, t=56, b=16),
            legend=dict(**core.PLOTLY_BASE['legend'], orientation='h', x=0, y=1.12))
        fig_main.update_layout(**main_layout)

        # Tabla mensual
        tbl_rows = ''
        for m in common:
            a25 = v25[m]; a26 = v26[m]
            pct = (a26-a25)/a25*100 if a25 else 0
            clr = '#5CE8D4' if pct >= 0 else '#F7A8D0'
            tbl_rows += (f'<tr><td style="padding:7px 10px;color:rgba(255,255,255,.65)">{MN[m]}</td>'
                         f'<td style="text-align:right;padding:7px 10px;color:rgba(255,255,255,.4)">{core._fmt_clp(a25)}</td>'
                         f'<td style="text-align:right;padding:7px 10px;color:#C9A97A">{core._fmt_clp(a26)}</td>'
                         f'<td style="text-align:center;padding:7px 10px;color:{clr};font-weight:600">{"+" if pct>=0 else ""}{pct:.1f}%</td></tr>')

        for m in sorted(set(v25.index)-set(common)):
            tbl_rows += (f'<tr><td style="padding:7px 10px;color:rgba(255,255,255,.4)">{MN[m]}</td>'
                         f'<td style="text-align:right;padding:7px 10px;color:rgba(255,255,255,.3)">{core._fmt_clp(v25[m])}</td>'
                         f'<td colspan="2" style="padding:7px 10px;color:rgba(255,255,255,.2)">sin dato 2026</td></tr>')

        tbl_html = (f'<table class="ventas-tbl"><thead><tr>'
                    f'<th style="text-align:left">MES</th><th>2025</th><th>2026</th><th>VAR.</th>'
                    f'</tr></thead><tbody>{tbl_rows}</tbody></table>')

        # Categorías mes a mes (2×2)
        CATS_ANA  = ['Alimentos', 'Bebidas S/Alcohol', 'Bebidas C/Alcohol', 'Vinos']
        CAT_CLRS  = ['#C9A97A', '#7EB8F7', '#5CE8D4', '#C4B5FD']
        fig_mm = _msp(rows=2, cols=2,
            subplot_titles=[f'<b>{c}</b>' for c in CATS_ANA],
            vertical_spacing=0.14, horizontal_spacing=0.08,
            specs=[[{'secondary_y':True},{'secondary_y':True}],
                   [{'secondary_y':True},{'secondary_y':True}]])
        todos25 = sorted(v25.index); todos26 = sorted(v26.index)
        for ci, (cat, clr) in enumerate(zip(CATS_ANA, CAT_CLRS)):
            row, col = ci//2+1, ci%2+1
            show_leg = (ci == 0)
            d25 = core._mv_cat(vc, 'bruto', cat, 2025, todos25)
            d26 = core._mv_cat(vc, 'bruto', cat, 2026, todos26)
            fig_mm.add_trace(go.Bar(name='2025', x=[MN[m] for m in todos25],
                y=[d25.get(m,0)/1e6 for m in todos25],
                marker_color='rgba(201,169,122,0.28)', showlegend=show_leg),
                row=row, col=col, secondary_y=False)
            fig_mm.add_trace(go.Bar(name='2026', x=[MN[m] for m in todos26],
                y=[d26.get(m,0)/1e6 for m in todos26],
                marker_color=clr, opacity=0.85, showlegend=show_leg),
                row=row, col=col, secondary_y=False)
            yoy_xs, yoy_ys, yoy_ms, yoy_txts = [], [], [], []
            for m in common:
                a25v = d25.get(m,0); a26v = d26.get(m,0)
                if a25v:
                    pv = (a26v-a25v)/a25v*100
                    yoy_xs.append(MN[m]); yoy_ys.append(pv)
                    yoy_ms.append('#5CE8D4' if pv>=0 else '#F7A8D0')
                    yoy_txts.append(f'{pv:+.0f}%')
            fig_mm.add_trace(go.Scatter(name='YoY%', x=yoy_xs, y=yoy_ys,
                mode='lines+markers+text',
                line=dict(color='rgba(255,255,255,.4)', width=1.2, dash='dot'),
                marker=dict(size=6, color=yoy_ms),
                text=yoy_txts, textposition='top center',
                textfont=dict(size=9), showlegend=show_leg),
                row=row, col=col, secondary_y=True)
        mm_layout = {k: v for k, v in core.PLOTLY_BASE.items()
                     if k not in ('xaxis','yaxis','title','margin','legend')}
        mm_layout.update(barmode='group', bargap=0.22, height=580,
            margin=dict(l=16, r=48, t=56, b=16),
            title=dict(text='Categorías mes a mes — 2025 vs 2026',
                **core.PLOTLY_BASE['title']),
            legend=dict(**core.PLOTLY_BASE['legend'], orientation='h', x=0, y=1.04))
        for ax in ['yaxis2','yaxis4','yaxis6','yaxis8']:
            mm_layout[ax] = dict(tickformat='+.0f', ticksuffix='%',
                tickfont=dict(size=9, color='rgba(255,255,255,.3)'),
                showgrid=False, zeroline=True,
                zerolinecolor='rgba(255,255,255,.07)')
        fig_mm.update_layout(**mm_layout)
        fig_mm.update_annotations(font=dict(
            family="'Palatino Linotype',Georgia,serif", size=12,
            color='rgba(255,255,255,.8)'))

        # Acumulado
        fig_acum = go.Figure()
        cx25, cy25, acc = [], [], 0
        for m in sorted(v25.index):
            acc += v25[m]; cx25.append(MN[m]); cy25.append(acc/1e6)
        cx26, cy26, acc = [], [], 0
        for m in sorted(v26.index):
            acc += v26[m]; cx26.append(MN[m]); cy26.append(acc/1e6)
        fig_acum.add_trace(go.Scatter(x=cx25, y=cy25, name='Acum. 2025',
            mode='lines+markers',
            line=dict(color='rgba(201,169,122,.4)', width=2, dash='dot'),
            marker=dict(size=6), fill='tozeroy', fillcolor='rgba(201,169,122,.04)'))
        fig_acum.add_trace(go.Scatter(x=cx26, y=cy26, name='Acum. 2026',
            mode='lines+markers', line=dict(color='#C9A97A', width=2.5),
            marker=dict(size=7, color='#C9A97A'),
            fill='tozeroy', fillcolor='rgba(201,169,122,.10)'))
        acum_layout = {**core.PLOTLY_BASE}
        acum_layout.update(height=300,
            title=dict(text='Ventas acumuladas en el año', **core.PLOTLY_BASE['title']),
            yaxis=dict(**core.PLOTLY_BASE['yaxis'], ticksuffix='M'),
            legend=dict(**core.PLOTLY_BASE['legend'], orientation='h', x=0, y=1.15))
        fig_acum.update_layout(**acum_layout)

        # ── Donut mix por categoría ────────────────────────────────────────────
        vals25 = core._cat_totals(vc, CATS_ANA, 2025, common)
        vals26 = core._cat_totals(vc, CATS_ANA, 2026, common)
        fig_mix = go.Figure()
        fig_mix.add_trace(go.Pie(
            labels=CATS_ANA, values=vals25, name='2025',
            domain=dict(x=[0, 0.46]), hole=0.55, marker_colors=CAT_CLRS,
            textinfo='none',
            hovertemplate='%{label}<br>2025: <b>%{value:,.0f}</b> (%{percent})<extra></extra>'))
        fig_mix.add_trace(go.Pie(
            labels=CATS_ANA, values=vals26, name='2026',
            domain=dict(x=[0.54, 1.0]), hole=0.55, marker_colors=CAT_CLRS,
            textinfo='none',
            hovertemplate='%{label}<br>2026: <b>%{value:,.0f}</b> (%{percent})<extra></extra>'))
        fig_mix.add_annotation(text='2025', x=0.23, y=0.5, showarrow=False,
            font=dict(size=13, color=core.MUTED))
        fig_mix.add_annotation(text='2026', x=0.77, y=0.5, showarrow=False,
            font=dict(size=13, color=core.GOLD))
        mix_layout = {**core.PLOTLY_BASE}
        mix_layout.update(title=dict(text='Mix por categoría', **core.PLOTLY_BASE['title']),
            height=300, showlegend=True,
            legend=dict(**core.PLOTLY_BASE['legend'], orientation='v',
                        x=1.0, y=0.5, xanchor='left', yanchor='middle'),
            margin=dict(l=0, r=120, t=48, b=0))
        fig_mix.update_layout(**mix_layout)

        # ── Variación por categoría ────────────────────────────────────────────
        cat_rows = []
        for cat, clr in zip(CATS_ANA, CAT_CLRS):
            r25 = core._csum(vc,  common, 2025, cat, 'bruto')
            r26 = core._csum(vc,  common, 2026, cat, 'bruto')
            q25 = core._csum(vq,  common, 2025, cat, 'cantidad')
            q26 = core._csum(vq,  common, 2026, cat, 'cantidad')
            rv  = (r26-r25)/r25*100 if r25 else 0
            qv  = (q26-q25)/q25*100 if q25 else 0
            a25 = r25/q25 if q25 else 0
            a26 = r26/q26 if q26 else 0
            av  = (a26-a25)/a25*100 if a25 else 0
            cat_rows.append({'cat':cat,'color':clr,'r25':r25,'r26':r26,'rv':rv,
                             'q25':q25,'q26':q26,'qv':qv,'a25':a25,'a26':a26,'av':av})

        fig_cat = go.Figure()
        fig_cat.add_trace(go.Bar(name='Ingresos YoY %', x=CATS_ANA,
            y=[d['rv'] for d in cat_rows],
            marker_color=[core.GOLD if d['rv'] >= 0 else '#F7A8D0' for d in cat_rows],
            opacity=0.9,
            text=[f"{d['rv']:+.1f}%" for d in cat_rows],
            textposition='outside', textfont=dict(size=11, color='rgba(255,255,255,0.8)'),
            hovertemplate='%{x}<br>Ingresos: <b>%{y:+.1f}%</b><extra></extra>'))
        fig_cat.add_trace(go.Bar(name='Unidades YoY %', x=CATS_ANA,
            y=[d['qv'] for d in cat_rows],
            marker_color=['#5CE8D4' if d['qv'] >= 0 else '#9F7AEA' for d in cat_rows],
            opacity=0.85,
            text=[f"{d['qv']:+.1f}%" for d in cat_rows],
            textposition='outside', textfont=dict(size=11, color='rgba(255,255,255,0.7)'),
            hovertemplate='%{x}<br>Unidades: <b>%{y:+.1f}%</b><extra></extra>'))
        fig_cat.add_hline(y=0, line_color='rgba(255,255,255,0.12)', line_width=1)
        cat_layout = {**core.PLOTLY_BASE}
        cat_layout.update(
            title=dict(text='Variación por categoría — Ingresos vs Unidades (YoY %)',
                       **core.PLOTLY_BASE['title']),
            barmode='group', bargap=0.28, bargroupgap=0.06,
            yaxis=dict(**core.PLOTLY_BASE['yaxis'], tickformat='+.0f', ticksuffix='%'),
            legend=dict(**core.PLOTLY_BASE['legend'], orientation='h', x=0, y=1.12),
            height=360, margin=dict(l=16, r=16, t=72, b=48))
        fig_cat.update_layout(**cat_layout)

        # ── Tabla detalle por categoría ────────────────────────────────────────
        th_s = ('color:rgba(201,169,122,0.42);font-size:9px;letter-spacing:.12em;'
                'font-weight:700;padding:8px 10px;text-transform:uppercase')
        tbl_cat_rows = ''
        for d in cat_rows:
            tbl_cat_rows += (
                f'<tr>'
                f'<td style="padding:9px 12px;font-size:12px">'
                f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
                f'background:{d["color"]};margin-right:8px;vertical-align:middle"></span>'
                f'{d["cat"]}</td>'
                f'<td style="padding:9px 12px;font-size:11px;color:rgba(255,255,255,.45);'
                f'text-align:right">{core._fmt_clp(d["r25"])}</td>'
                f'<td style="padding:9px 12px;font-size:11px;color:#C9A97A;'
                f'text-align:right">{core._fmt_clp(d["r26"])}</td>'
                f'<td style="padding:9px 12px;text-align:center">{core._pct_badge(d["rv"])}</td>'
                f'<td style="padding:9px 12px;font-size:11px;color:rgba(255,255,255,.45);'
                f'text-align:right">{core._fmt_q(d["q25"])}</td>'
                f'<td style="padding:9px 12px;font-size:11px;color:#C9A97A;'
                f'text-align:right">{core._fmt_q(d["q26"])}</td>'
                f'<td style="padding:9px 12px;text-align:center">{core._pct_badge(d["qv"])}</td>'
                f'<td style="padding:9px 12px;font-size:11px;color:rgba(255,255,255,.45);'
                f'text-align:right">{core._fmt_clp(d["a25"])}</td>'
                f'<td style="padding:9px 12px;font-size:11px;color:#C9A97A;'
                f'text-align:right">{core._fmt_clp(d["a26"])}</td>'
                f'<td style="padding:9px 12px;text-align:center">{core._pct_badge(d["av"])}</td>'
                f'</tr>')
        tbl_cat = (
            f'<div style="overflow-x:auto"><table class="ventas-tbl"><thead><tr>'
            f'<th style="{th_s};text-align:left">CATEGORÍA</th>'
            f'<th style="{th_s};text-align:right">ING. 2025</th>'
            f'<th style="{th_s};text-align:right">ING. 2026</th>'
            f'<th style="{th_s};text-align:center">VAR.</th>'
            f'<th style="{th_s};text-align:right">UNID. 2025</th>'
            f'<th style="{th_s};text-align:right">UNID. 2026</th>'
            f'<th style="{th_s};text-align:center">VAR.</th>'
            f'<th style="{th_s};text-align:right">P.PROM 2025</th>'
            f'<th style="{th_s};text-align:right">P.PROM 2026</th>'
            f'<th style="{th_s};text-align:center">VAR.</th>'
            f'</tr></thead><tbody>{tbl_cat_rows}</tbody></table></div>')

        # ── Panel diagnóstico ──────────────────────────────────────────────────
        ult3       = sorted(common)[-3:]
        tend3      = sum(yoy[m] for m in ult3) / max(1, len(ult3))
        n_pos      = sum(1 for v in yoy.values() if v >= 0)
        desc25     = float(vd[(vd['año']==2025) & (vd['mes'].isin(common))]['descuento'].sum())
        desc26     = float(vd[(vd['año']==2026) & (vd['mes'].isin(common))]['descuento'].sum())
        dpct25     = desc25/tot25*100 if tot25 else 0
        dpct26     = desc26/tot26*100 if tot26 else 0
        worst_cat  = min(cat_rows, key=lambda x: x['rv'])
        best_cat   = max(cat_rows, key=lambda x: x['rv'])
        proy_anual = None
        if len(v26) >= 3:
            tot26_all  = float(v26.sum())
            mes_min    = int(min(v26.index))
            mes_max    = int(max(v26.index))
            meses_trans = mes_max - mes_min + 1   # meses reales transcurridos (no solo archivos presentes)
            mp          = tot26_all / meses_trans
            mr          = 12 - mes_max
            proy_anual  = tot26_all + mp * mr

        def _dc(title, body_txt, bc):
            return (f'<div class="diag-card" style="border-color:{bc}">'
                    f'<div class="diag-title">{title}</div>'
                    f'<div class="diag-body">{body_txt}</div></div>')

        tc = '#5CE8D4' if tend3 >= 0 else '#F7A8D0'
        gc = '#5CE8D4' if n_pos >= len(common)//2 else '#F7A8D0'
        diag_html = (
            _dc('TENDENCIA RECIENTE',
                f'Últimos {len(ult3)} meses: {"crecimiento" if tend3>=0 else "caída"} '
                f'promedio de {abs(tend3):.1f}%', tc) +
            _dc('MESES EN VERDE',
                f'{n_pos} de {len(common)} meses superan a 2025', gc) +
            _dc('CATEGORÍA MÁS AFECTADA',
                f'{worst_cat["cat"]}: ingresos {worst_cat["rv"]:+.1f}%, '
                f'unidades {worst_cat["qv"]:+.1f}%', '#F7A8D0') +
            _dc('MEJOR CATEGORÍA',
                f'{best_cat["cat"]}: ingresos {best_cat["rv"]:+.1f}%, '
                f'unidades {best_cat["qv"]:+.1f}%', '#5CE8D4') +
            _dc('DESCUENTOS SOBRE VENTAS',
                f'{dpct25:.1f}% (2025) vs {dpct26:.1f}% (2026)', core.GOLD)
        )
        if proy_anual:
            diag_html += _dc('PROYECCIÓN ANUAL 2026',
                f'~{core._fmt_clp(proy_anual)} si se mantiene el ritmo actual',
                core.GOLD_2)

        # ── AMEX placeholder / datos ───────────────────────────────────────────
        amex_meses = sorted(vdf[(vdf['año']==2026) & (vdf['mes']>=6)]['mes'].unique())
        if not amex_meses:
            amex_html = (
                '<div style="background:rgba(201,169,122,0.06);'
                'border:1px solid rgba(201,169,122,.18);border-radius:10px;'
                'padding:18px 20px;display:flex;align-items:center;gap:16px">'
                '<div style="font-size:24px">⭐</div>'
                '<div>'
                '<div style="font-size:13px;color:rgba(255,255,255,.85)">'
                'Promo activa desde el 7 Jun 2026</div>'
                '<div style="font-size:11px;color:rgba(255,255,255,.4);margin-top:4px">'
                'Los datos de impacto aparecerán aquí automáticamente cuando se agregue '
                '<b style="color:rgba(201,169,122,.7)">Jun26.xls</b> '
                'a la carpeta Ventas/</div></div></div>')
        else:
            amex_data = vdf[(vdf['año']==2026) & (vdf['mes'].isin(amex_meses))]
            amex_rows = ''
            for am in amex_meses:
                a26v = float(amex_data[amex_data['mes']==am]['bruto'].sum())
                a25v = float(vdf[(vdf['año']==2025) & (vdf['mes']==am)]['bruto'].sum())
                pv   = (a26v-a25v)/a25v*100 if a25v else 0
                pc   = '#5CE8D4' if pv >= 0 else '#F7A8D0'
                amex_rows += (
                    f'<div style="display:flex;align-items:center;gap:12px;padding:8px 0;'
                    f'border-bottom:1px solid rgba(255,255,255,.04)">'
                    f'<span style="min-width:32px;font-size:12px;color:rgba(255,255,255,.6)">'
                    f'{MN[am]}</span>'
                    f'<span style="font-size:11px;color:rgba(255,255,255,.4);min-width:74px">'
                    f'2025: {core._fmt_clp(a25v)}</span>'
                    f'<span style="font-size:11px;color:{core.GOLD};min-width:74px">'
                    f'2026: {core._fmt_clp(a26v)}</span>'
                    f'<span style="font-size:12px;font-weight:600;color:{pc}">'
                    f'{"+" if pv>=0 else ""}{pv:.1f}%</span></div>')
            amex_html = (
                '<div style="background:rgba(201,169,122,0.06);'
                'border:1px solid rgba(201,169,122,.18);border-radius:10px;padding:14px 18px">'
                '<div style="font-size:12px;color:rgba(201,169,122,.8);margin-bottom:10px">'
                '⭐ Meses con promo activa (Jun 2026 en adelante)</div>'
                f'{amex_rows}</div>')

        # Panel RESUMEN: barras mensuales + detalle + acumuladas
        p_resumen = f"""
        <div class="section-label">VENTAS MENSUALES — 2025 VS 2026</div>
        <div class="chart-box">{_fig_html(fig_main, 380)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
          <div>
            <div class="section-label">DETALLE MENSUAL</div>
            <div class="chart-box" style="padding:4px 0">{tbl_html}</div>
          </div>
          <div>
            <div class="section-label">VENTAS ACUMULADAS</div>
            <div class="chart-box">{_fig_html(fig_acum, 280)}</div>
          </div>
        </div>"""

        # Panel CATEGORÍAS: mix donut + variación + detalle por cat + mes a mes
        p_cats = f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
          <div>
            <div class="section-label">MIX POR CATEGORÍA</div>
            <div class="chart-box">{_fig_html(fig_mix, 300)}</div>
          </div>
          <div>
            <div class="section-label">VARIACIÓN — INGRESOS VS UNIDADES</div>
            <div class="chart-box">{_fig_html(fig_cat, 300)}</div>
          </div>
        </div>
        <div class="section-label">DETALLE POR CATEGORÍA</div>
        <div class="chart-box" style="padding:4px 0">{tbl_cat}</div>
        <div class="section-label">CATEGORÍAS MES A MES</div>
        <div class="chart-box">{_fig_html(fig_mm, 560)}</div>"""

        # Panel DIAGNÓSTICO
        p_diag = f'<div style="margin-top:16px">{diag_html}</div>'

        # Panel AMEX
        p_amex = f'<div style="margin-top:16px">{amex_html}</div>'

        ventas_tabs = _stabs([
            ('RESUMEN',        'res',  p_resumen),
            ('CATEGORÍAS',     'cat',  p_cats),
            ('DIAGNÓSTICO',    'diag', p_diag),
            ('PROMO DOM. 💰',  'amex', p_amex),   # ingresos; análisis de producción en tab ⭐ AMEX
        ])

        body = f'<h2>Ventas</h2>{kpis}{ventas_tabs}'
        self.render(_page(body))


# ── Tab: TENDENCIAS ────────────────────────────────────────────────────────────

class TabTendencias(WebTab):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        state.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.state
        if s.df is None or s.df.empty:
            self.render(_page('<h2>Tendencias</h2><p style="color:var(--t3)">Sin datos.</p>'))
            return
        top = (s.df[s.df['category']=='Fondo'].groupby('dish')['quantity']
               .mean().sort_values(ascending=False).head(8).index.tolist())
        fig_heat  = core.chart_heatmap(s.df)
        fig_trend = core.chart_trend(s.df, top)
        fig_week  = core.chart_weekly_total(s.df)
        tend_tabs = _stabs([
            ('HEATMAP',   'heat',  f'<div class="chart-box">{_fig_html(fig_heat,  380)}</div>'),
            ('TENDENCIA', 'trend', f'<div class="chart-box">{_fig_html(fig_trend, 460)}</div>'),
            ('VOLUMEN',   'vol',   f'<div class="chart-box">{_fig_html(fig_week,  340)}</div>'),
        ])
        self.render(_page(f'<h2>Tendencias</h2>{tend_tabs}'))


# ── Tab: AMEX ─────────────────────────────────────────────────────────────────

class TabAmex(WebTab):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        state.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        s = self.state
        if not s.model:
            self.render(_page('<h2>Promo AMEX</h2><p style="color:var(--t3)">Sin datos.</p>'))
            return
        n_promo = sum(1 for d in s.history if core.day_type(d) == 'Dom-Promo')
        lbl, clr = core.confidence_label(n_promo)
        fig = core.chart_promo_impact(s.model)
        body = (f'<h2>Promo AMEX Domingos</h2>'
                f'<p style="margin-bottom:16px">'
                f'Activa desde el 7 Jun 2026 · 50% descuento tarjeta AMEX<br>'
                f'<span style="color:{clr}">{lbl}</span> ({n_promo} domingos)</p>'
                f'<div class="chart-box">{_fig_html(fig, 460)}</div>')
        self.render(_page(body))


# ── Tab: HISTORIAL ─────────────────────────────────────────────────────────────

class TabHistorial(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        # Barra superior: selector fecha + modo comparación + buscador
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(QLabel("Día:"))
        self.date_combo = QComboBox()
        self.date_combo.setFixedWidth(230)
        top.addWidget(self.date_combo)
        top.addSpacing(8)
        self._chk_comparar = QCheckBox("Comparar días similares")
        self._chk_comparar.setToolTip(
            "Muestra las últimas 4 ocurrencias del mismo tipo de día\n"
            "(ej: los últimos 4 sábados) para comparar tendencias.")
        self._chk_comparar.stateChanged.connect(
            lambda _: self._on_date_change(self.date_combo.currentIndex()))
        top.addWidget(self._chk_comparar)
        top.addSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar plato...")
        self.search.setFixedWidth(200)
        self.search.textChanged.connect(lambda _: self._on_date_change(self.date_combo.currentIndex()))
        top.addWidget(self.search)
        top.addSpacing(12)
        self._btn_excluir = QPushButton("✕ Excluir del modelo")
        self._btn_excluir.setFixedHeight(28)
        self._btn_excluir.setToolTip(
            "Marca este día como atípico y lo excluye del modelo estadístico.\n"
            "Útil para eventos especiales, feriados no capturados o días con datos incorrectos.")
        self._btn_excluir.clicked.connect(self._on_toggle_excluded)
        top.addWidget(self._btn_excluir)
        top.addStretch()
        lay.addLayout(top)

        self.view = WebTab()
        lay.addWidget(self.view)

        self.date_combo.currentIndexChanged.connect(self._on_date_change)
        state.changed.connect(self._reload_dates)
        self._reload_dates()

    def _reload_dates(self):
        self.date_combo.blockSignals(True)
        self.date_combo.clear()
        for d in sorted(self.state.history.keys(), reverse=True):
            dt = core.day_type(d)
            self.date_combo.addItem(f"{core.DAYS_ES[d.weekday()]} {d.strftime('%d/%m/%Y')} · {dt}",
                                    userData=d)
        self.date_combo.blockSignals(False)
        self._on_date_change(0)

    def _on_toggle_excluded(self):
        idx = self.date_combo.currentIndex()
        if idx < 0: return
        d = self.date_combo.itemData(idx)
        if d is None: return
        is_excl = d in self.state.excluded_extra
        accion  = "incluir" if is_excl else "excluir"
        reply = QMessageBox.question(
            self, f"{'Incluir' if is_excl else 'Excluir'} día del modelo",
            f"¿Deseas {accion} el {core.DAYS_ES[d.weekday()]} "
            f"{d.strftime('%d/%m/%Y')} {'en' if is_excl else 'del'} modelo estadístico?\n\n"
            f"{'Esto lo volverá a incluir en los cálculos.' if is_excl else 'No afecta datos ya guardados — solo el cálculo del pronóstico.'}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.state.toggle_excluded(d)
        self._update_excluir_btn(d)
        # Recargar el modelo con el nuevo conjunto de excluidos
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, lambda: (
            setattr(self.state, 'history',
                    core.load_history(self.state.folder, [], self.state.excluded_extra)),
            setattr(self.state, 'model', core.build_model(self.state.history)),
            setattr(self.state, 'df',    core.build_df(self.state.history)),
            self.state.changed.emit()
        ))

    def _update_excluir_btn(self, d):
        if d is None:
            self._btn_excluir.setEnabled(False)
            return
        is_excl = d in self.state.excluded_extra
        self._btn_excluir.setText("✓ Incluir en modelo" if is_excl else "✕ Excluir del modelo")
        self._btn_excluir.setStyleSheet(
            "color:#5CE8D4;" if is_excl else "")

    def _on_date_change(self, idx):
        if idx < 0 or not self.state.history:
            return
        d = self.date_combo.itemData(idx)
        if d is None: return
        self._update_excluir_btn(d)

        comparar = self._chk_comparar.isChecked()
        if comparar:
            self._render_comparar(d)
        else:
            self._render_single(d)

    def _render_single(self, d):
        dt      = core.day_type(d)
        data    = self.state.history.get(d, {})
        dm      = self.state.model.get(dt, {})
        q       = self.search.text().strip().lower()
        is_excl = d in self.state.excluded_extra
        excl_banner = (
            '<div style="background:rgba(248,113,113,.08);border:1px solid rgba(248,113,113,.25);'
            'border-radius:8px;padding:8px 14px;margin-bottom:12px;font-size:12px;'
            'color:rgba(248,113,113,.9)">✕ Este día está <b>excluido del modelo estadístico</b>. '
            'Los datos se muestran pero no influyen en el pronóstico.</div>'
        ) if is_excl else ''

        rows = ''
        for cat in core.CAT_ORDER:
            items = sorted(
                [((n, c), qty) for (_, n, c), qty in data.items()
                 if c == cat and (not q or q in n.lower())],
                key=lambda x: -x[1])
            if not items: continue
            rows += (f'<tr><td colspan="4" style="padding:8px 10px;'
                     f'background:rgba(255,255,255,.03);font-size:9px;'
                     f'letter-spacing:.14em;color:var(--t3)">{cat.upper()}</td></tr>')
            for (name, cat2), real_qty in items:
                stats  = dm.get((name, cat2))
                fc_qty = round(core.dish_fc(stats, self.state.k_factor)) if stats else None
                diff   = real_qty - fc_qty if fc_qty is not None else None
                if diff is None:    diff_clr, diff_icon = 'rgba(255,255,255,.25)', ''
                elif diff > 0:      diff_clr, diff_icon = '#F87171', '↑'
                elif diff < 0:      diff_clr, diff_icon = '#FBBF24', '↓'
                else:               diff_clr, diff_icon = '#A5D6A7', '='
                diff_txt = f'{diff_icon}{abs(diff):.0f}' if diff is not None else '—'
                rows += (f'<tr><td style="padding:7px 10px;color:rgba(255,255,255,.8)">{_html_mod.escape(name)}</td>'
                         f'<td style="text-align:right;padding:7px 10px;font-family:monospace">{round(real_qty)}</td>'
                         f'<td style="text-align:right;padding:7px 10px;color:rgba(255,255,255,.4)">{fc_qty or "—"}</td>'
                         f'<td style="text-align:center;padding:7px 10px;color:{diff_clr};font-weight:600">{diff_txt}</td></tr>')

        leyenda = ('<div style="font-size:10px;color:rgba(255,255,255,.3);margin-bottom:10px">'
                   '<span style="color:#F87171">↑ faltó</span>&nbsp;·&nbsp;'
                   '<span style="color:#FBBF24">↓ sobró</span>&nbsp;·&nbsp;'
                   '<span style="color:#A5D6A7">= exacto</span></div>')
        th = ('font-size:9px;color:var(--t3);border-bottom:1px solid rgba(255,255,255,.06);padding:6px 10px')
        body = (f'<h2>{core.DAYS_ES[d.weekday()]} {d.strftime("%d/%m/%Y")}</h2>'
                f'<p style="color:var(--t3);margin-bottom:8px">Tipo: {dt}</p>'
                f'{excl_banner}'
                f'{leyenda}'
                f'<table style="width:100%;border-collapse:collapse;font-size:12px"><thead><tr>'
                f'<th style="text-align:left;{th}">Plato</th>'
                f'<th style="text-align:right;{th}">Real</th>'
                f'<th style="text-align:right;{th}">Pronóstico</th>'
                f'<th style="text-align:center;{th}">Balance</th>'
                f'</tr></thead><tbody>{rows}</tbody></table>')
        self.view.render(_page(body))

    def _render_comparar(self, d_ref):
        """Muestra las últimas 4 ocurrencias del mismo tipo de día, una por columna."""
        dt  = core.day_type(d_ref)
        q   = self.search.text().strip().lower()

        # Últimas 4 fechas del mismo tipo de día (incluyendo la seleccionada)
        fechas = sorted(
            [fd for fd in self.state.history if core.day_type(fd) == dt],
            reverse=True)[:4]
        if not fechas:
            self.view.render(_page(f'<h2>Sin datos para {dt}</h2>'))
            return
        fechas = list(reversed(fechas))  # orden cronológico

        # Recopilar todos los platos que aparecen en alguno de esos días
        nombres: dict = {}
        for fd in fechas:
            for (_, n, c), _ in self.state.history.get(fd, {}).items():
                if not q or q in n.lower():
                    nombres[(n, c)] = True

        # Construir tabla: filas = plato, columnas = fecha
        date_headers = ''.join(
            f'<th style="text-align:right;padding:6px 8px;font-size:9px;'
            f'color:{"#C9A97A" if fd==d_ref else "rgba(255,255,255,.35)"};'
            f'border-bottom:1px solid rgba(255,255,255,.06)">'
            f'{fd.strftime("%d/%m")}</th>'
            for fd in fechas)

        rows = ''
        for cat in core.CAT_ORDER:
            cat_items = [(n, c) for (n, c) in nombres if c == cat]
            if not cat_items: continue
            rows += (f'<tr><td colspan="{len(fechas)+1}" style="padding:8px 10px;'
                     f'background:rgba(255,255,255,.03);font-size:9px;'
                     f'letter-spacing:.14em;color:var(--t3)">{cat.upper()}</td></tr>')
            for name, cat2 in sorted(cat_items, key=lambda x: x[0]):
                row_cells = f'<td style="padding:6px 10px;color:rgba(255,255,255,.75);font-size:12px">{_html_mod.escape(name)}</td>'
                for fd in fechas:
                    qty = next((v for (_, n, c), v in self.state.history.get(fd, {}).items()
                                if n == name and c == cat2), None)
                    clr = '#C9A97A' if fd == d_ref else 'rgba(255,255,255,.6)'
                    cell = f'{round(qty):>3}' if qty else '—'
                    row_cells += (f'<td style="text-align:right;padding:6px 8px;'
                                  f'font-family:monospace;font-size:12px;color:{clr}">{cell}</td>')
                rows += f'<tr>{row_cells}</tr>'

        th = 'font-size:9px;color:var(--t3);border-bottom:1px solid rgba(255,255,255,.06);padding:6px 10px'
        body = (f'<h2>Comparativa — {dt}</h2>'
                f'<p style="color:var(--t3);margin-bottom:12px">Últimas {len(fechas)} ocurrencias '
                f'· <span style="color:#C9A97A">{d_ref.strftime("%d/%m/%Y")}</span> = referencia</p>'
                f'<table style="width:100%;border-collapse:collapse"><thead><tr>'
                f'<th style="text-align:left;{th}">Plato</th>{date_headers}'
                f'</tr></thead><tbody>{rows}</tbody></table>')
        self.view.render(_page(body))


# ── Tab: RECETAS ───────────────────────────────────────────────────────────────

# ── Ingredient row widget ──────────────────────────────────────────────────────

_CAT_OPTS_ED = [
    "Proteínas del mar", "Mariscos", "Carnes", "Aves",
    "Frutas", "Lácteos", "Huevos",
    "Pasta y cereales", "Repostería", "Helados", "Aceites y condimentos",
]
_TEMP_OPTS = ["refrigerado", "congelado", "ambiente"]
_UNID_OPTS = ["g", "kg", "ml", "l", "u", "oz", "porción", "cdta", "Tbsp"]
_DIAS_OPTS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

_ING_STYLE = """
QFrame#ingRow {
    background: rgba(255,255,255,0.02);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    margin-bottom: 4px;
    color: #E8DDD0;
}
"""

class IngredienteRow(QFrame):
    """Fila de ingrediente: campos + días de despacho."""
    sig_delete = pyqtSignal(object)

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("ingRow")
        self.setStyleSheet(_ING_STYLE)
        self._build(data)

    def _build(self, d: dict):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(6)

        # ── Fila 1: campos principales ────────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self.nombre = QLineEdit(d.get('nombre', ''))
        self.nombre.setPlaceholderText('Nombre del ingrediente')

        self.cantidad = QDoubleSpinBox()
        self.cantidad.setRange(0, 99999)
        self.cantidad.setDecimals(1)
        self.cantidad.setSingleStep(5)
        self.cantidad.setValue(float(d.get('cantidad', 100)))
        self.cantidad.setFixedWidth(90)

        self.unidad = QComboBox()
        self.unidad.addItems(_UNID_OPTS)
        self.unidad.setCurrentText(d.get('unidad', 'g'))
        self.unidad.setFixedWidth(70)

        self.categoria = QComboBox()
        self.categoria.addItems(_CAT_OPTS_ED)
        if d.get('categoria') in _CAT_OPTS_ED:
            self.categoria.setCurrentText(d['categoria'])

        self.temperatura = QComboBox()
        self.temperatura.addItems(_TEMP_OPTS)
        if d.get('temperatura') in _TEMP_OPTS:
            self.temperatura.setCurrentText(d['temperatura'])
        self.temperatura.setFixedWidth(110)

        self.precio_unit = QDoubleSpinBox()
        self.precio_unit.setRange(0, 999999)
        self.precio_unit.setDecimals(0)
        self.precio_unit.setSingleStep(100)
        self.precio_unit.setValue(float(d.get('precio_unitario', 0) or 0))
        self.precio_unit.setFixedWidth(90)
        self.precio_unit.setPrefix("$")

        btn_del = QPushButton('✕')
        btn_del.setFixedSize(26, 26)
        btn_del.setObjectName('danger')
        btn_del.clicked.connect(lambda: self.sig_delete.emit(self))

        row1.addWidget(self.nombre, 4)
        row1.addWidget(self.cantidad)
        row1.addWidget(self.unidad)
        row1.addWidget(self.categoria, 3)
        row1.addWidget(self.temperatura)
        row1.addWidget(self.precio_unit)
        row1.addWidget(btn_del)
        lay.addLayout(row1)

        # ── Fila 2: proveedor + días de despacho ─────────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(4)
        lbl_d = QLabel("DESPACHO")
        lbl_d.setObjectName("subtle")
        lbl_d.setFixedWidth(68)
        row2.addWidget(lbl_d)

        self.proveedor = QLineEdit(d.get('proveedor', ''))
        self.proveedor.setPlaceholderText('Proveedor')
        self.proveedor.setFixedWidth(140)
        self.proveedor.setStyleSheet("font-size:11px;")
        row2.addWidget(self.proveedor)
        row2.addSpacing(8)

        dias_activos = set(d.get('dias_despacho', []))
        self._dia_checks: dict[str, QCheckBox] = {}
        for dia in _DIAS_OPTS:
            cb = QCheckBox(dia[:3])
            cb.setChecked(dia in dias_activos)
            cb.setStyleSheet("font-size:11px; color:rgba(255,255,255,.65);")
            self._dia_checks[dia] = cb
            row2.addWidget(cb)
        btn_all = QPushButton("Todos")
        btn_all.setFixedHeight(20)
        btn_all.setStyleSheet("font-size:10px;padding:0 6px;")
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self._dia_checks.values()])
        btn_none = QPushButton("Ninguno")
        btn_none.setFixedHeight(20)
        btn_none.setStyleSheet("font-size:10px;padding:0 6px;")
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb in self._dia_checks.values()])
        row2.addSpacing(6)
        row2.addWidget(btn_all)
        row2.addWidget(btn_none)
        row2.addStretch()
        lay.addLayout(row2)

    def get_data(self) -> dict:
        return {
            'nombre':          self.nombre.text().strip(),
            'cantidad':        self.cantidad.value(),
            'unidad':          self.unidad.currentText(),
            'categoria':       self.categoria.currentText(),
            'temperatura':     self.temperatura.currentText(),
            'precio_unitario': self.precio_unit.value(),
            'proveedor':       self.proveedor.text().strip(),
            'dias_despacho':   [d for d, cb in self._dia_checks.items() if cb.isChecked()],
        }


# ── TabRecetas ─────────────────────────────────────────────────────────────────

class TabRecetas(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        self._current_sku  = None
        self._current_name = None
        self._ing_rows: list[IngredienteRow] = []
        self._build()
        state.changed.connect(self._reload)

    # ── Construcción UI ───────────────────────────────────────────────────────

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Panel izquierdo ───────────────────────────────────────────────────
        left_w = QWidget()
        left_w.setFixedWidth(272)
        left_w.setObjectName("recetasPanel")
        left_lay = QVBoxLayout(left_w)
        left_lay.setContentsMargins(14, 14, 14, 14)
        left_lay.setSpacing(8)

        self._lbl_prog = QLabel()
        self._lbl_prog.setWordWrap(True)
        self._lbl_prog.setTextFormat(Qt.TextFormat.RichText)
        left_lay.addWidget(self._lbl_prog)

        # Buscador
        self._search = QLineEdit()
        self._search.setPlaceholderText("Buscar plato...")
        self._search.setFixedHeight(28)
        self._search.textChanged.connect(self._reload)
        left_lay.addWidget(self._search)

        # Filtro por categoría
        self._cat_filter = QComboBox()
        self._cat_filter.addItem("Todas las categorías", "")
        for cat in core.CAT_ORDER:
            self._cat_filter.addItem(cat, cat)
        self._cat_filter.currentIndexChanged.connect(self._reload)
        left_lay.addWidget(self._cat_filter)

        # Pendientes primero
        self._chk_pending = QCheckBox("Pendientes primero")
        self._chk_pending.setStyleSheet("font-size:11px;color:rgba(255,255,255,.55);")
        self._chk_pending.stateChanged.connect(self._reload)
        left_lay.addWidget(self._chk_pending)

        self.dish_list = QListWidget()
        self.dish_list.setObjectName("recetasList")
        self.dish_list.currentRowChanged.connect(self._on_select)
        left_lay.addWidget(self.dish_list, 1)

        self._lbl_cat = QLabel()
        self._lbl_cat.setWordWrap(True)
        self._lbl_cat.setTextFormat(Qt.TextFormat.RichText)
        left_lay.addWidget(self._lbl_cat)

        root.addWidget(left_w)

        # ── Panel derecho: editor ─────────────────────────────────────────────
        right_w = QWidget()
        right_lay = QVBoxLayout(right_w)
        right_lay.setContentsMargins(20, 16, 20, 12)
        right_lay.setSpacing(8)

        # Cabecera
        self._lbl_title = QLabel("Selecciona un plato")
        self._lbl_title.setStyleSheet(
            "font-size:16px;font-family:'Playfair Display',Georgia,serif;"
            "color:rgba(255,255,255,.9);")
        self._lbl_sku = QLabel()
        self._lbl_sku.setObjectName("subtle")
        self._lbl_status = QLabel()
        self._lbl_status.setStyleSheet("font-size:11px;color:rgba(240,232,220,0.62);")

        precio_row = QHBoxLayout()
        precio_row.setSpacing(8)
        _lbl_pv = QLabel("Precio venta:")
        _lbl_pv.setStyleSheet("font-size:11px;color:rgba(255,255,255,.45);")
        self._spin_precio_venta = QDoubleSpinBox()
        self._spin_precio_venta.setRange(0, 9999999)
        self._spin_precio_venta.setDecimals(0)
        self._spin_precio_venta.setSingleStep(100)
        self._spin_precio_venta.setPrefix("$ ")
        self._spin_precio_venta.setFixedWidth(130)
        self._spin_precio_venta.setEnabled(False)
        precio_row.addWidget(_lbl_pv)
        precio_row.addWidget(self._spin_precio_venta)
        precio_row.addStretch()

        right_lay.addWidget(self._lbl_title)
        right_lay.addWidget(self._lbl_sku)
        right_lay.addWidget(self._lbl_status)
        right_lay.addLayout(precio_row)

        # Cabeceras de columnas
        hdr = QHBoxLayout()
        hdr.setContentsMargins(10, 0, 10, 0)
        hdr.setSpacing(6)
        for txt, stretch in [('INGREDIENTE',4),('CANTIDAD',0),('UNIDAD',0),
                              ('CATEGORÍA',3),('TEMPERATURA',0),('$/UNIT',0),('',0)]:
            lbl = QLabel(txt)
            lbl.setStyleSheet("font-size:9px;letter-spacing:.1em;color:rgba(255,255,255,.3);")
            if txt == 'CANTIDAD':    lbl.setFixedWidth(90)
            elif txt == 'UNIDAD':    lbl.setFixedWidth(70)
            elif txt == 'TEMPERATURA': lbl.setFixedWidth(110)
            elif txt == '$/UNIT':    lbl.setFixedWidth(90)
            elif txt == '':          lbl.setFixedWidth(26)
            if stretch: hdr.addWidget(lbl, stretch)
            else:       hdr.addWidget(lbl)
        right_lay.addLayout(hdr)

        # Área de scroll para ingredientes
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # Viewport explícitamente oscuro — sin esto Qt pone fondo blanco por defecto
        self._scroll.setStyleSheet(
            "QScrollArea{border:none;background:#09080C;}"
            "QScrollArea>QWidget{background:#09080C;}")
        self._ing_container = QWidget()
        self._ing_lay = QVBoxLayout(self._ing_container)
        self._ing_lay.setContentsMargins(0, 0, 0, 0)
        self._ing_lay.setSpacing(4)
        self._ing_lay.addStretch()
        self._scroll.setWidget(self._ing_container)
        right_lay.addWidget(self._scroll, 1)

        # Botones de acción
        btn_bar = QHBoxLayout()
        self._btn_add  = QPushButton("＋ Ingrediente")
        self._btn_save = QPushButton("💾 Guardar")
        self._btn_save.setObjectName("primary")
        self._btn_del  = QPushButton("🗑 Borrar receta")
        self._btn_del.setObjectName("danger")
        self._lbl_msg  = QLabel()
        self._lbl_msg.setStyleSheet("font-size:11px;color:rgba(240,232,220,0.55);")

        self._btn_add.clicked.connect(self._add_ing)
        self._btn_save.clicked.connect(self._save)
        self._btn_del.clicked.connect(self._delete_recipe)

        btn_bar.addWidget(self._btn_add)
        btn_bar.addWidget(self._btn_save)
        btn_bar.addWidget(self._btn_del)
        btn_bar.addWidget(self._lbl_msg, 1)
        right_lay.addLayout(btn_bar)

        root.addWidget(right_w, 1)
        self._set_editor_enabled(False)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_editor_enabled(self, enabled: bool):
        for w in (self._btn_add, self._btn_save, self._btn_del,
                  self._scroll, self._spin_precio_venta):
            w.setEnabled(enabled)

    def _clear_ing_rows(self):
        for row in self._ing_rows:
            self._ing_lay.removeWidget(row)
            row.deleteLater()
        self._ing_rows.clear()

    def _add_row(self, data: dict):
        row = IngredienteRow(data)
        row.sig_delete.connect(self._remove_ing)
        # Insert before the stretch (last item)
        idx = self._ing_lay.count() - 1
        self._ing_lay.insertWidget(idx, row)
        self._ing_rows.append(row)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _reload(self):
        """Rebuild dish list from history."""
        self.dish_list.blockSignals(True)
        self.dish_list.clear()

        s = self.state
        if not s.history:
            self.dish_list.blockSignals(False)
            return

        # Deduplicate
        seen: dict = {}
        for data in s.history.values():
            for (code, name, cat) in data:
                if (code, name, cat) not in seen:
                    seen[(code, name, cat)] = True

        n_total = len(seen)
        n_conf  = sum(1 for (code, name, cat) in seen
                      if s.name_to_sku.get(name, code) in s.recetas)
        pct     = round(n_conf / n_total * 100) if n_total else 0

        self._lbl_prog.setText(
            f'<div style="margin-bottom:8px">'
            f'<span style="font-size:18px;font-weight:700;color:#C9A97A">{n_conf}</span>'
            f'<span style="font-size:11px;color:rgba(255,255,255,.4)"> con receta  </span>'
            f'<span style="font-size:18px;color:rgba(255,255,255,.45)">{n_total-n_conf}</span>'
            f'<span style="font-size:11px;color:rgba(255,255,255,.4)"> sin receta</span></div>'
            f'<div style="height:5px;background:rgba(255,255,255,.07);border-radius:3px">'
            f'<div style="height:5px;width:{pct}%;background:#C9A97A;border-radius:3px"></div></div>'
            f'<div style="font-size:10px;color:rgba(255,255,255,.3);margin-top:3px">{pct}% configurado</div>')

        active_cat    = self._cat_filter.currentData()
        search_txt    = self._search.text().strip().lower()
        pending_first = self._chk_pending.isChecked()

        # Construir lista filtrada
        items = []
        for (code, name, cat) in seen:
            if active_cat and cat != active_cat:
                continue
            if search_txt and search_txt not in name.lower():
                continue
            sku = s.name_to_sku.get(name, code)
            has = sku in s.recetas
            items.append((cat, name, code, sku, has))

        # Orden: por categoría (CAT_ORDER), luego pendientes/conf, luego nombre
        cat_rank = {c: i for i, c in enumerate(core.CAT_ORDER)}
        if pending_first:
            items.sort(key=lambda x: (cat_rank.get(x[0], 99), x[4], x[1]))
        else:
            items.sort(key=lambda x: (cat_rank.get(x[0], 99), x[1]))

        for cat, name, code, sku, has in items:
            item = QListWidgetItem()
            item.setText(f"{'✓' if has else '○'}  {name}")
            item.setForeground(QColor('#C9A97A') if has else QColor(255, 255, 255, 120))
            item.setData(Qt.ItemDataRole.UserRole, (code, name, cat))
            self.dish_list.addItem(item)

        # Category stats (usa seen completo, no filtrado)
        by_cat: dict[str, list] = {}
        for (code, name, cat) in seen:
            sku = s.name_to_sku.get(name, code)
            by_cat.setdefault(cat, [0, 0])
            by_cat[cat][1] += 1
            if sku in s.recetas: by_cat[cat][0] += 1
        cat_html = '<div style="margin-top:8px">'
        for cat in core.CAT_ORDER:
            if cat not in by_cat: continue
            ok, tot = by_cat[cat]
            clr = '#A5D6A7' if ok == tot else ('#FBBF24' if ok >= tot / 2 else '#F87171')
            cat_html += (f'<div style="display:flex;justify-content:space-between;'
                         f'font-size:11px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.04)">'
                         f'<span style="color:rgba(255,255,255,.55)">{cat}</span>'
                         f'<span style="color:{clr}">{ok}/{tot}</span></div>')
        cat_html += '</div>'
        self._lbl_cat.setText(cat_html)

        self.dish_list.blockSignals(False)

        # Restaurar selección sin disparar _on_select
        if self._current_sku:
            for i in range(self.dish_list.count()):
                item = self.dish_list.item(i)
                if item:
                    code, name, cat = item.data(Qt.ItemDataRole.UserRole)
                    if s.name_to_sku.get(name, code) == self._current_sku:
                        self.dish_list.blockSignals(True)
                        self.dish_list.setCurrentRow(i)
                        self.dish_list.blockSignals(False)
                        break

    def _on_select(self, idx: int):
        if idx < 0: return
        item = self.dish_list.item(idx)
        if not item: return
        code, name, cat = item.data(Qt.ItemDataRole.UserRole)
        sku = self.state.name_to_sku.get(name, code)
        self._load_dish(sku, name, cat)

    def _load_dish(self, sku: str, name: str, cat: str):
        self._current_sku  = sku
        self._current_name = name
        self._lbl_msg.setText("")

        rec  = self.state.recetas.get(sku, {})
        ings = rec.get('ingredientes', [])

        self._lbl_title.setText(name)
        self._lbl_sku.setText(f"{cat.upper()}  ·  SKU {sku}")
        self._spin_precio_venta.setValue(float(rec.get('precio_venta', 0) or 0))

        has = sku in self.state.recetas
        if has:
            self._lbl_status.setText(
                f'<span style="color:#A5D6A7">✓ {len(ings)} ingrediente{"s" if len(ings)!=1 else ""} configurado{"s" if len(ings)!=1 else ""}</span>')
        else:
            self._lbl_status.setText(
                '<span style="color:#F87171">⚠ Sin receta · excluido de lista de compras</span>')

        self._clear_ing_rows()
        for ing in ings:
            self._add_row(ing)

        self._btn_del.setVisible(has)
        self._set_editor_enabled(True)

    def _add_ing(self):
        if self._current_sku is None: return
        self._add_row({
            'nombre': '', 'cantidad': 100.0, 'unidad': 'g',
            'categoria': _CAT_OPTS_ED[0], 'temperatura': 'refrigerado',
            'dias_despacho': [],
        })
        # Scroll to bottom
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()))

    def _remove_ing(self, row: IngredienteRow):
        self._ing_lay.removeWidget(row)
        self._ing_rows.remove(row)
        row.deleteLater()

    def _save(self):
        if self._current_sku is None: return

        all_data  = [r.get_data() for r in self._ing_rows]
        ings      = [d for d in all_data if d['nombre']]
        n_vacios  = len(all_data) - len(ings)
        if n_vacios:
            reply = QMessageBox.question(
                self, "Ingredientes sin nombre",
                f"{n_vacios} fila{'s' if n_vacios>1 else ''} sin nombre "
                f"{'serán descartadas' if n_vacios>1 else 'será descartada'} al guardar.\n"
                "¿Continuar de todas formas?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Save:
                return

        s = self.state
        s._recetas_raw[self._current_sku] = {
            'nombre':       self._current_name,
            'precio_venta': self._spin_precio_venta.value(),
            'ingredientes': ings,
        }
        s.recetas[self._current_sku] = s._recetas_raw[self._current_sku]

        try:
            core.save_recetas(s._recetas_raw)
            self._lbl_msg.setText(
                f'<span style="color:#A5D6A7">✓ Guardado · {len(ings)} ingredientes</span>')
            self._lbl_status.setText(
                f'<span style="color:#A5D6A7">✓ {len(ings)} ingrediente{"s" if len(ings)!=1 else ""} configurado{"s" if len(ings)!=1 else ""}</span>')
            self._btn_del.setVisible(True)
            self._update_dish_item_badge(self._current_sku, True)
            self._reload()
            self.state.changed.emit()   # actualiza TabCostos y TabCompras en tiempo real
            # Si el filtro activo excluye el plato guardado, resetear editor
            if self.dish_list.currentRow() < 0:
                self._current_sku = None
                self._current_name = None
                self._set_editor_enabled(False)
                self._lbl_title.setText("Selecciona un plato")
                self._lbl_sku.setText("")
                self._lbl_status.setText("")
        except Exception as e:
            self._lbl_msg.setText(f'<span style="color:#F87171">Error: {e}</span>')

    def _delete_recipe(self):
        if self._current_sku is None: return
        reply = QMessageBox.question(
            self, "Borrar receta",
            f"¿Eliminar la receta de «{self._current_name}»?\n"
            "Este plato quedará excluido de la lista de compras.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes:
            return
        s = self.state
        s._recetas_raw.pop(self._current_sku, None)
        s.recetas.pop(self._current_sku, None)
        try:
            core.save_recetas(s._recetas_raw)
            self._clear_ing_rows()
            self._lbl_status.setText(
                '<span style="color:#F87171">⚠ Sin receta · excluido de lista de compras</span>')
            self._lbl_msg.setText('<span style="color:#FBBF24">Receta eliminada</span>')
            self._btn_del.setVisible(False)
            self._update_dish_item_badge(self._current_sku, False)
            self._reload()
        except Exception as e:
            self._lbl_msg.setText(f'<span style="color:#F87171">Error: {e}</span>')

    def _update_dish_item_badge(self, sku: str, has: bool):
        for i in range(self.dish_list.count()):
            item = self.dish_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data:
                code, name, cat = data
                if self.state.name_to_sku.get(name, code) == sku:
                    name_txt = name
                    item.setText(f"{'✓' if has else '○'}  {name_txt}")
                    item.setForeground(QColor('#C9A97A') if has else QColor(255, 255, 255, 120))
                    break


# ── TabCostos ─────────────────────────────────────────────────────────────────

class TabCostos(QWidget):
    def __init__(self, state: AppState, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._web = WebTab()
        lay.addWidget(self._web)
        state.changed.connect(self._render)
        self._render()

    def _render(self):
        s = self.state
        if not s.recetas:
            self._web.render(self._html_empty())
            return
        rows = core.calc_costos(s._recetas_raw, s.model, s.df)
        self._web.render(self._html(rows))

    @staticmethod
    def _fc_color(pct):
        if pct is None:  return 'rgba(255,255,255,.2)'
        if pct < 28:     return '#5CE8D4'
        if pct < 35:     return '#A5D6A7'
        if pct < 45:     return '#FBBF24'
        return '#F87171'

    @staticmethod
    def _fmt_clp(v):
        if v is None or v == 0: return '—'
        return f"${v:,.0f}".replace(',', '.')

    def _html(self, rows):
        # ── KPIs ──
        conf = [r for r in rows if r['precio_venta'] > 0 and r['costo'] > 0]
        avg_fc  = (sum(r['food_cost_pct'] for r in conf) / len(conf)) if conf else None
        n_ok    = len(conf)
        n_total = len(rows)

        kpi_fc_color = self._fc_color(avg_fc)
        kpi_fc_txt   = f"{avg_fc:.1f}%" if avg_fc else "—"

        kpis_html = f"""
        <div class="kpi-strip">
          <div class="kpi">
            <div class="kpi-v" style="color:{kpi_fc_color}">{kpi_fc_txt}</div>
            <div class="kpi-l">Food Cost Promedio</div>
          </div>
          <div class="kpi">
            <div class="kpi-v">{n_ok}</div>
            <div class="kpi-l">Platos con costos completos</div>
          </div>
          <div class="kpi">
            <div class="kpi-v" style="color:rgba(255,255,255,.35)">{n_total - n_ok}</div>
            <div class="kpi-l">Sin precio / costo</div>
          </div>
        </div>"""

        # ── Tabla ──
        table_rows = ""
        for r in rows:
            fc  = r['food_cost_pct']
            clr = self._fc_color(fc)
            fc_txt  = f"{fc:.1f}%" if fc is not None else "—"
            bar_w   = min(fc, 100) if fc else 0
            pop_txt = f"{r['popularidad']:.1f}" if r['popularidad'] else "—"
            table_rows += f"""
            <tr>
              <td class="name">{r['nombre']}</td>
              <td class="num">{self._fmt_clp(r['precio_venta'])}</td>
              <td class="num">{self._fmt_clp(r['costo'])}</td>
              <td class="fc-cell">
                <div style="display:flex;align-items:center;gap:8px">
                  <div style="flex:1;height:4px;background:rgba(255,255,255,.07);border-radius:2px">
                    <div style="width:{bar_w:.0f}%;height:4px;background:{clr};border-radius:2px"></div>
                  </div>
                  <span style="color:{clr};font-size:12px;min-width:44px;text-align:right">{fc_txt}</span>
                </div>
              </td>
              <td class="num">{self._fmt_clp(r['margen'])}</td>
              <td class="num muted">{pop_txt}</td>
            </tr>"""

        # ── Plotly matrix menú ──
        chart_data, chart_layout = self._menu_engineering_chart(rows)

        return f"""<!DOCTYPE html><html><head>
        <meta charset="utf-8">
        <script src="{_PLOTLY_FILE}"></script>
        <style>
          * {{ box-sizing:border-box; margin:0; padding:0 }}
          body {{ background:#09080C; color:#F2EAE0; font-family:'Segoe UI',sans-serif;
                  padding:24px; overflow-x:hidden }}
          h2 {{ font-family:'Palatino Linotype',Georgia,serif; color:#C9A97A;
                font-size:18px; font-weight:400; letter-spacing:.04em; margin-bottom:16px }}
          h3 {{ font-size:13px; font-weight:600; color:rgba(255,255,255,.5);
                letter-spacing:.08em; text-transform:uppercase; margin:28px 0 12px }}
          .kpi-strip {{ display:flex; gap:16px; margin-bottom:24px }}
          .kpi {{ background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.07);
                  border-radius:12px; padding:14px 20px; flex:1 }}
          .kpi-v {{ font-size:28px; font-weight:700; color:#E8DDD0 }}
          .kpi-l {{ font-size:10px; color:rgba(255,255,255,.35); letter-spacing:.08em;
                    text-transform:uppercase; margin-top:4px }}
          table {{ width:100%; border-collapse:collapse; font-size:13px; margin-bottom:32px }}
          th {{ font-size:9px; letter-spacing:.1em; color:rgba(255,255,255,.3);
                padding:6px 12px; text-align:left; border-bottom:1px solid rgba(255,255,255,.08) }}
          td {{ padding:9px 12px; border-bottom:1px solid rgba(255,255,255,.04) }}
          tr:hover td {{ background:rgba(255,255,255,.02) }}
          .name {{ color:#E8DDD0; max-width:260px }}
          .num {{ text-align:right; color:rgba(255,255,255,.6); font-variant-numeric:tabular-nums }}
          .fc-cell {{ min-width:160px }}
          .muted {{ color:rgba(255,255,255,.3) }}
          #chart {{ margin-top:8px }}
        </style></head><body>
        <h2>Análisis de Costos</h2>
        {kpis_html}
        <h3>Matriz Menú Engineering</h3>
        <div id="chart"></div>
        <h3>Detalle por plato</h3>
        <table>
          <thead><tr>
            <th>PLATO</th>
            <th style="text-align:right">PRECIO VENTA</th>
            <th style="text-align:right">COSTO RECETA</th>
            <th>FOOD COST %</th>
            <th style="text-align:right">MARGEN</th>
            <th style="text-align:right">POP/DÍA</th>
          </tr></thead>
          <tbody>{table_rows}</tbody>
        </table>
        <script>
          var data = {chart_data};
          var layout = {chart_layout};
          Plotly.newPlot('chart', data, layout, {{responsive:true, displayModeBar:false}});
        </script>
        </body></html>"""

    def _menu_engineering_chart(self, rows):
        import json as _json
        conf = [r for r in rows if r['margen'] and r['popularidad']]
        if not conf:
            return '[]', '{}'

        med_pop = sorted(r['popularidad'] for r in conf)[len(conf)//2]
        med_mar = sorted(r['margen']      for r in conf)[len(conf)//2]

        # 4 cuadrantes
        QUADS = {
            'Estrellas':  ('#C9A97A', []),   # alta pop, alto margen
            'Vacas':      ('#7EB8F7', []),   # alta pop, bajo margen
            'Enigmas':    ('#F7A8D0', []),   # baja pop, alto margen
            'Perros':     ('#6B7280', []),   # baja pop, bajo margen
        }
        for r in conf:
            hi_pop = r['popularidad'] >= med_pop
            hi_mar = r['margen']      >= med_mar
            if   hi_pop and hi_mar:  q = 'Estrellas'
            elif hi_pop and not hi_mar: q = 'Vacas'
            elif not hi_pop and hi_mar: q = 'Enigmas'
            else:                       q = 'Perros'
            QUADS[q][1].append(r)

        traces = []
        for label, (color, items) in QUADS.items():
            if not items: continue
            traces.append({
                'type': 'scatter', 'mode': 'markers+text',
                'name': label,
                'x': [r['popularidad'] for r in items],
                'y': [r['margen']      for r in items],
                'text': [r['nombre']   for r in items],
                'textposition': 'top center',
                'textfont': {'size': 9, 'color': 'rgba(255,255,255,.5)'},
                'marker': {'size': 10, 'color': color,
                           'line': {'color': 'rgba(255,255,255,.2)', 'width': 1}},
            })

        layout = {
            'paper_bgcolor': '#09080C', 'plot_bgcolor': 'rgba(255,255,255,.02)',
            'font': {'color': '#E8DDD0', 'family': 'Segoe UI'},
            'height': 420, 'margin': {'l': 60, 'r': 20, 't': 20, 'b': 50},
            'xaxis': {'title': 'Popularidad (unidades/día promedio)',
                      'gridcolor': 'rgba(255,255,255,.06)',
                      'zerolinecolor': 'rgba(255,255,255,.15)'},
            'yaxis': {'title': 'Margen bruto ($ CLP)',
                      'gridcolor': 'rgba(255,255,255,.06)',
                      'zerolinecolor': 'rgba(255,255,255,.15)'},
            'legend': {'bgcolor': 'rgba(0,0,0,0)',
                       'font': {'size': 11}},
            'shapes': [
                {'type': 'line', 'x0': med_pop, 'x1': med_pop, 'y0': 0, 'y1': 1,
                 'xref': 'x', 'yref': 'paper',
                 'line': {'color': 'rgba(255,255,255,.15)', 'dash': 'dot', 'width': 1}},
                {'type': 'line', 'x0': 0, 'x1': 1, 'y0': med_mar, 'y1': med_mar,
                 'xref': 'paper', 'yref': 'y',
                 'line': {'color': 'rgba(255,255,255,.15)', 'dash': 'dot', 'width': 1}},
            ],
        }
        return _json.dumps(traces), _json.dumps(layout)

    @staticmethod
    def _html_empty():
        return """<!DOCTYPE html><html><head><meta charset="utf-8">
        <style>body{background:#09080C;color:rgba(255,255,255,.3);
        display:flex;align-items:center;justify-content:center;height:100vh;
        font-family:'Segoe UI',sans-serif;font-size:14px;text-align:center}
        p{line-height:1.8}</style></head><body>
        <p>No hay recetas cargadas.<br>
        Configura ingredientes y precios en la sección <b style="color:#C9A97A">Recetas</b>.</p>
        </body></html>"""


# ── Main Window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Margo · Nelí — Sistema de Gestión")
        self.resize(1440, 900)
        self.setMinimumSize(1024, 700)

        # Estado global — sin carga sincrónica: el worker arranca después de show()
        self.state = AppState()

        # ── Layout raíz: NavRail | separador | QStackedWidget ─────────────
        _root = QWidget()
        _lay  = QHBoxLayout(_root)
        _lay.setContentsMargins(0, 0, 0, 0)
        _lay.setSpacing(0)

        # Nav Rail — borde derecho manejado por QSS #navRail
        self.nav = NavRail(self.state)
        _lay.addWidget(self.nav)

        # Stack de páginas (una por item de nav)
        self.stack = QStackedWidget()
        self.stack.addWidget(TabProduccion(self.state))   # 0 – Producción
        self.stack.addWidget(TabCompras(self.state))      # 1 – Compras
        self.stack.addWidget(TabVentas(self.state))       # 2 – Ventas
        self.stack.addWidget(TabTendencias(self.state))   # 3 – Tendencias
        self.stack.addWidget(TabAmex(self.state))         # 4 – AMEX
        self.stack.addWidget(TabHistorial(self.state))    # 5 – Historial
        self.stack.addWidget(TabRecetas(self.state))      # 6 – Recetas
        self.stack.addWidget(TabCostos(self.state))       # 7 – Costos

        self.nav.page_changed.connect(self.stack.setCurrentIndex)
        _lay.addWidget(self.stack, 1)

        self.setCentralWidget(_root)
        self.setStyleSheet(QSS)

        # Arrancar carga asíncrona después de mostrar la UI (evita congelamiento inicial)
        QTimer.singleShot(100, self.nav._on_reload)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    import traceback

    # Necesario para QWebEngine en Windows
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")

    try:
        app = QApplication(sys.argv)
        app.setApplicationName("Margo · Nelí")
        app.setOrganizationName("Margo Gourmet")
        app.setFont(QFont("Segoe UI", 11))

        win = MainWindow()
        win.show()
        sys.exit(app.exec())

    except Exception:
        tb = traceback.format_exc()
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "startup_error.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(tb)
        try:
            _app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "Error de inicio",
                f"El programa no pudo iniciar.\n\nDetalle guardado en:\n{log_path}\n\n"
                f"{tb[:800]}")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
