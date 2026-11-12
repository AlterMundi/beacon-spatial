#!/usr/bin/env python3
"""Flask web UI for Harmonic Beacon Spatializer.

Serves a dark-themed control surface (default http://localhost:5050).
Sends OSC to sclang (beacon.scd) on BEACON_OSC_PORT (default 57120).

Usage:
    ./start-beacon.sh
    # or manually:
    #   source venv/bin/activate
    #   python3 webui.py
"""

from flask import Flask, render_template_string, request, jsonify
from pythonosc.udp_client import SimpleUDPClient
import os, json, glob, re, time, math

app = Flask(__name__)
osc = SimpleUDPClient(
    os.environ.get("BEACON_OSC_TARGET_HOST", "127.0.0.1"),
    int(os.environ.get("BEACON_OSC_PORT", "57120")),
)
# Second OSC target: PD replica sclang on port 9001 (when running)
osc_pd = SimpleUDPClient("127.0.0.1", 9001)

CONFIG_DIR = os.path.expanduser("~/Projects/beacon-spatial/configs")
RECORD_DIR = os.path.expanduser("~/Music/beacon")
os.makedirs(CONFIG_DIR, exist_ok=True)
os.makedirs(RECORD_DIR, exist_ok=True)

BANDS = [
    {"freq": 40.4,   "color": "#c0392b", "default_gain": 1.2, "default_az": 180, "default_dist": 2.0, "default_q": 1.0,   "default_solo": 0},
    {"freq": 80.8,   "color": "#e67e22", "default_gain": 1.0, "default_az": 135, "default_dist": 2.5, "default_q": 0.5,   "default_solo": 0},
    {"freq": 121.2,  "color": "#f1c40f", "default_gain": 1.0, "default_az": -90, "default_dist": 3.0, "default_q": 0.333, "default_solo": 0},
    {"freq": 161.6,  "color": "#2ecc71", "default_gain": 1.0, "default_az": -45, "default_dist": 2.5, "default_q": 0.25,  "default_solo": 0},
    {"freq": 202,  "color": "#1abc9c", "default_gain": 1.0, "default_az": 45,  "default_dist": 2.0, "default_q": 0.2,   "default_solo": 0},
    {"freq": 242.4,  "color": "#3498db", "default_gain": 1.3, "default_az": 0,   "default_dist": 1.5, "default_q": 0.167, "default_solo": 0},
    {"freq": 484.8,  "color": "#2980b9", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_q": 0.5,   "default_solo": 0},
    {"freq": 727.2,  "color": "#8e44ad", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_q": 0.333, "default_solo": 0},
    {"freq": 969.6,  "color": "#9b59b6", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_q": 0.25,  "default_solo": 0},
    {"freq": 1212, "color": "#e84393", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_q": 0.2,   "default_solo": 0},
    {"freq": 1454.4, "color": "#fd79a8", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_q": 0.167, "default_solo": 0},
    {"freq": 1696.8, "color": "#a29bfe", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_q": 0.143, "default_solo": 0},
    {"freq": "1818+", "color": "#dfe6e9", "default_gain": 1.0, "default_az": 0,   "default_dist": 2.0, "default_solo": 0},
]

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
    <title>Harmonic Beacon • Spatializer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&amp;family=Space+Grotesk:wght@500;600&amp;display=swap');
        
        :root {
            --accent: #22d3ee;
        }
        
        body {
            font-family: 'Inter', system_ui, sans-serif;
        }
        
        .font-display {
            font-family: 'Space Grotesk', 'Inter', sans-serif;
            font-weight: 600;
            letter-spacing: -0.02em;
        }

        .section {
            background: #0f1117;
            border: 1px solid #1f2937;
        }

        .band-card {
            background: #0f1117;
            border: 1px solid #1f2937;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .band-card:hover {
            border-color: #374151;
            transform: translateY(-1px);
        }

        .slider {
            accent-color: #22d3ee;
        }

        .value-display {
            font-variant-numeric: tabular-nums;
            font-feature-settings: "tnum";
        }

        .sensor-card {
            background: #0f1117;
            border: 1px solid #1f2937;
            transition: all 0.2s ease;
        }

        .live-dot {
            animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }

        .param-pill {
            background: #1f2937;
            font-size: 0.65rem;
            padding: 1px 6px;
            border-radius: 9999px;
            font-weight: 600;
        }

        .driver-row {
            background: #11151f;
            border: 1px solid #1f2937;
            font-family: ui-monospace, monospace;
            font-size: 0.75rem;
        }

        .spectrum-bar {
            transition: height 80ms linear;
        }

        .navy {
            background: #0a0c12;
        }

        .control-label {
            font-size: 0.625rem;
            letter-spacing: 0.5px;
            font-weight: 600;
            color: #64748b;
        }

        .big-value {
            font-size: 1.1rem;
            font-weight: 600;
            font-variant-numeric: tabular-nums;
        }

        .modern-slider {
            height: 6px;
            background: #1f2937;
            border-radius: 999px;
            outline: none;
        }

        .modern-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            height: 16px;
            width: 16px;
            background: #22d3ee;
            border-radius: 999px;
            box-shadow: 0 0 0 3px rgba(34, 211, 238, 0.2);
            cursor: pointer;
            transition: all 0.1s ease;
        }

        .modern-slider::-webkit-slider-thumb:hover {
            box-shadow: 0 0 0 5px rgba(34, 211, 238, 0.35);
        }

        .band-header {
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.5px;
        }

        .canvas-orientation {
            background: #11151f;
            border-radius: 12px;
            border: 1px solid #1f2937;
        }

        .stat {
            font-size: 0.7rem;
            color: #64748b;
        }
    </style>
</head>
<body class="bg-[#0a0c12] text-slate-200">
    <!-- Top Bar -->
    <div class="sticky top-0 z-50 bg-[#0a0c12]/95 backdrop-blur border-b border-slate-800">
        <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
            <div class="flex items-center gap-x-3">
                <div class="flex items-center gap-x-2">
                    <div class="w-8 h-8 rounded-xl bg-gradient-to-br from-cyan-400 to-teal-500 flex items-center justify-center">
                        <i class="fa-solid fa-satellite text-white text-lg"></i>
                    </div>
                    <div>
                        <div class="font-display text-2xl font-semibold tracking-tighter">Beacon</div>
                        <div class="text-[10px] text-slate-500 -mt-1">HARMONIC SPATIALIZER</div>
                    </div>
                </div>
                <div class="hidden sm:block text-xs px-2.5 py-1 rounded-full bg-slate-900 border border-slate-800 text-slate-400">
                    13-band • 40.4Hz series
                </div>
            </div>

            <!-- Global Sensor Controls -->
            <div class="flex items-center gap-x-2">
                <!-- Influence -->
                <div class="flex items-center gap-x-2 bg-slate-900 border border-slate-800 rounded-2xl px-3 py-1.5">
                    <div class="flex items-center gap-x-1.5">
                        <i class="fa-solid fa-waveform-lines text-cyan-400 text-sm"></i>
                        <span class="text-xs font-medium text-slate-400">INFLUENCE</span>
                    </div>
                    <input type="range" id="sensor-influence" 
                           class="w-24 accent-cyan-400" 
                           min="0" max="1" step="0.01" value="0.65"
                           oninput="updateSensorInfluence(this.value)">
                    <span id="influence-val" class="font-mono text-sm font-semibold w-8 text-right text-cyan-300">0.65</span>
                </div>

                <!-- Live Toggle -->
                <button onclick="toggleLiveSensorsUI()"
                        id="live-btn"
                        class="flex items-center gap-x-2 px-4 py-1.5 rounded-2xl text-sm font-medium border transition-all active:scale-[0.985]
                               bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20">
                    <i class="fa-solid fa-play text-xs"></i>
                    <span id="live-text" class="font-semibold">LIVE</span>
                </button>

                <!-- Permissions -->
                <button onclick="requestSensorPermissions()"
                        class="flex items-center gap-x-2 px-3 py-1.5 text-xs font-medium rounded-2xl border border-slate-700 hover:bg-slate-900 transition-colors">
                    <i class="fa-solid fa-mobile-screen-button"></i>
                    <span class="hidden sm:inline">Permissions</span>
                </button>
            </div>
        </div>
    </div>

    <div class="max-w-7xl mx-auto px-4 pb-8 pt-4">

        <!-- Tabs (Manual / Sensors / Presets) -->
        <div class="flex items-center gap-2 mb-4" id="tab-bar">
            <button data-tab-target="manual" class="tab-btn px-4 py-2 rounded-2xl text-sm font-medium border border-cyan-500/40 bg-cyan-500/10 text-cyan-300">
                <i class="fa-solid fa-sliders text-xs mr-1.5"></i>Manual
            </button>
            <button data-tab-target="sensors" class="tab-btn px-4 py-2 rounded-2xl text-sm font-medium border border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200">
                <i class="fa-solid fa-mobile-screen text-xs mr-1.5"></i>Sensors
            </button>
            <button data-tab-target="presets" class="tab-btn px-4 py-2 rounded-2xl text-sm font-medium border border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200">
                <i class="fa-solid fa-folder-open text-xs mr-1.5"></i>Presets
            </button>
        </div>

        <!-- Status badges (always visible) -->
        <div class="flex flex-wrap items-center gap-2 mb-4">
            <div id="sensor-status"
                 class="text-xs px-3 py-1 bg-slate-900 border border-slate-800 rounded-full text-slate-400 font-medium flex items-center gap-1.5">
                <i class="fa-solid fa-circle text-emerald-400 text-[8px]"></i>
                <span>Ready</span>
            </div>
            <div id="config-status" class="text-xs px-3 py-1 bg-slate-900 border border-slate-800 rounded-full text-slate-400 font-medium">
                Presets ready
            </div>
        </div>

        <!-- Spectrum Visual (always visible) -->
        <div class="mb-5">
            <div class="flex items-end gap-1 h-16 px-1 bg-slate-950/70 border border-slate-800 rounded-3xl p-2" id="spectrum">
                {% for band in bands %}
                <div class="flex-1 flex flex-col items-center">
                    <div class="spectrum-bar w-full rounded-t-full transition-all duration-75"
                         id="spec{{ loop.index }}"
                         style="background: {{ band.color }}; height: {{ (band.default_gain / 3.0 * 100)|int }}%; min-height: 4px;"></div>
                    <div class="text-[9px] text-slate-500 mt-0.5 font-mono">{{ band.freq }}</div>
                </div>
                {% endfor %}
            </div>
        </div>

        <!-- ============= TAB: MANUAL ============= -->
        <section data-tab="manual" class="tab-panel">
            <div class="flex items-center justify-between mb-2 px-1">
                <div class="flex items-center gap-x-2">
                    <span class="font-semibold tracking-tight text-lg">Manual Controls</span>
                    <span class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-500">13 bands</span>
                </div>
                <button onclick="resetAll()"
                        class="text-xs flex items-center gap-1.5 px-3 py-1 rounded-xl border border-orange-500/30 text-orange-400 hover:bg-orange-500/10 transition-colors">
                    <i class="fa-solid fa-undo text-xs"></i>
                    <span class="font-medium">Reset</span>
                </button>
            </div>

            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-7 gap-2" id="band-grid">
                {% for band in bands %}
                <div class="band-card rounded-2xl p-2.5 border border-slate-800" id="band{{ loop.index }}" style="border-color: {{ band.color }}20;">
                    <div class="flex items-center justify-between mb-1.5">
                        <div>
                            <div class="band-header font-mono" style="color: {{ band.color }};">{{ band.freq }} Hz</div>
                        </div>
                        <button onclick="toggleSolo({{ loop.index }}, this)" id="s{{ loop.index }}"
                                class="solo-btn text-[9px] px-2 py-px border border-slate-700 hover:border-slate-600 rounded-lg font-bold text-slate-400 active:bg-white active:text-black transition-all">SOLO</button>
                    </div>

                    <!-- Gain -->
                    <div class="mb-2">
                        <div class="flex justify-between items-baseline mb-0.5">
                            <span class="control-label">GAIN</span>
                            <span id="g{{ loop.index }}" class="value-display font-mono text-cyan-300 text-sm">{{ band.default_gain }}</span>
                        </div>
                        <input type="range" min="0" max="3" step="0.05" value="{{ band.default_gain }}" id="gain{{ loop.index }}"
                               class="modern-slider w-full accent-cyan-400"
                               oninput="send('gain', {{ loop.index }}, this.value); show(this, 'g{{ loop.index }}'); updateSpec({{ loop.index }}, this.value)">
                    </div>

                    <!-- Azimuth -->
                    <div class="mb-2">
                        <div class="flex justify-between items-baseline mb-0.5">
                            <span class="control-label">AZIMUTH</span>
                            <span id="a{{ loop.index }}" class="value-display font-mono text-amber-300 text-sm">{{ band.default_az }}°</span>
                        </div>
                        <input type="range" min="-180" max="180" step="1" value="{{ band.default_az }}" id="az{{ loop.index }}"
                               class="modern-slider w-full accent-amber-400"
                               oninput="send('az', {{ loop.index }}, this.value); show(this, 'a{{ loop.index }}')">
                    </div>

                    <!-- Distance -->
                    <div class="mb-2">
                        <div class="flex justify-between items-baseline mb-0.5">
                            <span class="control-label">DISTANCE</span>
                            <span id="d{{ loop.index }}" class="value-display font-mono text-emerald-300 text-sm">{{ band.default_dist }}</span>
                        </div>
                        <input type="range" min="0" max="10" step="0.1" value="{{ band.default_dist }}" id="dist{{ loop.index }}"
                               class="modern-slider w-full accent-emerald-400"
                               oninput="send('dist', {{ loop.index }}, this.value); show(this, 'd{{ loop.index }}')">
                    </div>

                    {% if band.default_q is defined %}
                    <!-- Q -->
                    <div>
                        <div class="flex justify-between items-baseline mb-0.5">
                            <span class="control-label">Q (resonance)</span>
                            <span id="vq{{ loop.index }}" class="value-display font-mono text-violet-300 text-sm">{{ band.default_q }}</span>
                        </div>
                        <input type="range" min="0.01" max="2.0" step="0.001" value="{{ band.default_q }}" id="q{{ loop.index }}"
                               class="modern-slider w-full accent-violet-400"
                               oninput="send('q', {{ loop.index }}, this.value); show(this, 'vq{{ loop.index }}')">
                    </div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </section>

        <!-- ============= TAB: SENSORS ============= -->
        <section data-tab="sensors" class="tab-panel" hidden>
            <div class="flex items-center justify-between mb-3 px-1">
                <div class="flex items-center gap-x-2">
                    <span class="font-semibold tracking-tight text-lg">Sensor Interpreter</span>
                    <span class="px-2 py-0.5 text-[10px] bg-teal-900/50 text-teal-400 rounded-full text-center font-medium">Phone → Parameters</span>
                </div>
                <div class="text-[10px] text-slate-500 font-mono" id="sensor-tab-hint">
                    tap LIVE to start
                </div>
            </div>

            <div class="section rounded-3xl p-4 border border-slate-800">

                <!-- Orientation Visual -->
                <div class="mb-4">
                    <div class="flex justify-between items-center mb-1.5 px-1">
                        <span class="control-label">ORIENTATION VISUAL</span>
                        <span id="orientation-label" class="text-[10px] text-slate-500 font-mono">—</span>
                    </div>
                    <canvas id="orientation-canvas" width="300" height="140" class="canvas-orientation w-full"></canvas>
                </div>

                <!-- Sensor Cards -->
                <div class="grid grid-cols-2 gap-3 mb-4" id="sensor-cards">
                    <!-- Populated by JS: Yaw, Pitch, Roll, Accel -->
                </div>

                <!-- Mapping Editor -->
                <div class="mb-3">
                    <div class="flex items-center justify-between mb-1.5 px-0.5">
                        <span class="control-label">MAPPING EDITOR</span>
                        <button onclick="resetSensorMappingToDefault(); buildSensorMappingUI(); updateDebugViz();"
                                class="text-[10px] px-2 py-0.5 rounded-lg border border-slate-700 hover:bg-slate-900 text-slate-400">Reset defaults</button>
                    </div>

                    <div id="sensor-mapping-rows" class="space-y-2 text-sm">
                        <!-- JS populated beautiful rows -->
                    </div>
                </div>

                <!-- Active Drivers -->
                <div>
                    <div class="flex items-center justify-between mb-1.5 px-0.5">
                        <span class="control-label">CURRENTLY DRIVING</span>
                        <button onclick="applyCurrentMappingAndSend()"
                                class="text-emerald-400 hover:text-emerald-300 text-xs flex items-center gap-1 px-2 py-0.5 rounded-lg border border-emerald-900 hover:bg-emerald-950">
                            <i class="fa-solid fa-paper-plane text-xs"></i>
                            <span class="font-medium text-[10px]">FORCE SEND</span>
                        </button>
                    </div>
                    <div id="sensor-driving"
                         class="bg-[#0a0c12] border border-slate-800 rounded-2xl p-3 min-h-[68px] text-xs font-mono leading-snug text-emerald-300/90 whitespace-pre-line">
                        (enable LIVE and move your phone)
                    </div>
                </div>

                <!-- Sensor Debug Panel (visible, no DevTools needed) -->
                <div class="mt-4 border-t border-slate-800 pt-3">
                    <div class="flex items-center justify-between mb-1.5 px-0.5">
                        <span class="control-label">SENSOR DEBUG</span>
                        <button onclick="updateSensorDebugPanel()"
                                class="text-[10px] px-2 py-0.5 rounded-lg border border-slate-700 hover:bg-slate-900 text-slate-400">Refresh</button>
                    </div>
                    <div id="sensor-debug-panel"
                         class="bg-[#0a0c12] border border-slate-800 rounded-2xl p-3 text-[10px] font-mono leading-relaxed text-slate-400 space-y-0.5">
                        <!-- JS populated -->
                    </div>
                    <div class="text-[9px] text-slate-500 mt-1 px-0.5 leading-relaxed">
                        Shows: browser support, last event timestamps, listener state, fetch count, errors. Tap Refresh to update.
                    </div>
                </div>

                <div class="flex flex-wrap gap-2 mt-3 text-xs">
                    <button onclick="recenterSensors()"
                            title="Set the current phone pose as the new 'center' / neutral position. Subsequent rotations are measured relative to this point."
                            class="flex-1 sm:flex-none px-3 py-1.5 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 rounded-2xl text-cyan-400 text-xs font-medium flex items-center justify-center gap-2">
                        <i class="fa-solid fa-crosshairs"></i> <span>Recenter</span>
                    </button>
                    <button onclick="saveSensorConfigToPreset()"
                            class="flex-1 sm:flex-none px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-2xl text-emerald-400 text-xs font-medium flex items-center justify-center gap-2">
                        <i class="fa-solid fa-save"></i> <span>Save mapping to preset</span>
                    </button>
                    <button onclick="exportSensorConfig()"
                            class="flex-1 sm:flex-none px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-2xl text-xs font-medium flex items-center justify-center gap-2">
                        <i class="fa-solid fa-download"></i> <span>Export JSON</span>
                    </button>
                </div>
            </div>
        </section>

        <!-- ============= TAB: PRESETS ============= -->
        <section data-tab="presets" class="tab-panel" hidden>
            <div class="flex items-center justify-between mb-3 px-1">
                <div class="flex items-center gap-x-2">
                    <span class="font-semibold tracking-tight text-lg">Presets</span>
                    <span id="preset-count" class="text-[10px] px-2 py-0.5 rounded bg-slate-800 text-slate-500">0 files</span>
                </div>
                <button onclick="loadConfigList()"
                        class="text-xs flex items-center gap-1.5 px-3 py-1 rounded-xl border border-slate-700 text-slate-400 hover:bg-slate-900">
                    <i class="fa-solid fa-arrows-rotate text-xs"></i>
                    <span class="font-medium">Refresh</span>
                </button>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <!-- Save panel -->
                <div class="section rounded-3xl p-4 border border-slate-800">
                    <div class="control-label mb-2">SAVE CURRENT STATE</div>
                    <input id="save-name" type="text" placeholder="preset name"
                           class="w-full bg-slate-950 border border-slate-700 rounded-2xl px-3 py-2 text-sm outline-none text-slate-300 placeholder:text-slate-600 mb-3">
                    <button onclick="saveConfig()"
                            class="w-full py-2 rounded-2xl border border-emerald-500/40 text-emerald-400 hover:bg-emerald-950 font-medium text-sm flex items-center justify-center gap-2">
                        <i class="fa-solid fa-save text-xs"></i>
                        <span>Save (bands + mix + master + sensor_mappings)</span>
                    </button>
                    <div class="text-[10px] text-slate-500 mt-2 leading-relaxed">
                        Includes the current <span class="font-mono text-slate-400">sensor_mappings</span> from the Sensors tab so a preset can be loaded on any device with the same mapping intact.
                    </div>
                </div>

                <!-- Load panel -->
                <div class="section rounded-3xl p-4 border border-slate-800">
                    <div class="flex items-center justify-between mb-2">
                        <span class="control-label">LOAD FROM DISK</span>
                    </div>
                    <select id="load-select-large"
                            class="w-full bg-slate-950 border border-slate-700 rounded-2xl px-3 py-2 text-sm outline-none text-slate-300 mb-3">
                        <option value="">— pick a preset —</option>
                    </select>
                    <button onclick="loadConfigFromLargeSelect()"
                            class="w-full py-2 rounded-2xl border border-cyan-500/40 text-cyan-400 hover:bg-cyan-950 font-medium text-sm flex items-center justify-center gap-2">
                        <i class="fa-solid fa-download text-xs"></i>
                        <span>Load preset</span>
                    </button>
                </div>
            </div>

            <!-- Preset list (visible, clickable cards) -->
            <div class="mt-4">
                <div class="control-label mb-2 px-1">FILES IN configs/</div>
                <div id="preset-cards" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                    <!-- JS populated from /list_configs -->
                </div>
            </div>
        </section>

        <!-- Global Mix & Master -->
        <div class="mt-5 section rounded-3xl p-4 border border-slate-800">
            <div class="grid grid-cols-1 md:grid-cols-4 gap-5">
                <!-- Mix -->
                <div>
                    <div class="flex justify-between items-center mb-1">
                        <span class="font-semibold text-sm tracking-tight">MIX (wet)</span>
                        <span id="vmix" class="font-mono text-cyan-300">0.85</span>
                    </div>
                    <input type="range" min="0" max="1" step="0.01" value="0.85" id="mix"
                           class="modern-slider w-full accent-cyan-400"
                           oninput="sendGlobal('mix', this.value); show(this, 'vmix')">
                </div>
                
                <!-- Master -->
                <div>
                    <div class="flex justify-between items-center mb-1">
                        <span class="font-semibold text-sm tracking-tight">MASTER</span>
                        <span id="vmaster" class="font-mono text-cyan-300">0.90</span>
                    </div>
                    <input type="range" min="0" max="2" step="0.01" value="0.9" id="master"
                           class="modern-slider w-full accent-cyan-400"
                           oninput="sendGlobal('master', this.value); show(this, 'vmaster')">
                </div>

                <!-- Record -->
                <div>
                    <div class="flex justify-between items-center mb-1">
                        <span class="font-semibold text-sm tracking-tight text-red-400">RECORD</span>
                    </div>
                    <button id="rec-btn" onclick="toggleRecord(this)"
                            class="w-full py-2 rounded-2xl border border-red-500/40 text-red-400 hover:bg-red-950 font-medium text-sm flex items-center justify-center gap-2">
                        <i class="fa-solid fa-circle"></i>
                        <span>START</span>
                    </button>
                </div>

                <!-- Reset All -->
                <div>
                    <div class="flex justify-between items-center mb-1">
                        <span class="font-semibold text-sm tracking-tight">GLOBAL</span>
                    </div>
                    <button onclick="resetAll()"
                            class="w-full py-2 rounded-2xl border border-orange-500/30 text-orange-400 hover:bg-orange-950 font-medium text-sm flex items-center justify-center gap-2">
                        <i class="fa-solid fa-undo"></i>
                        <span>RESET ALL</span>
                    </button>
                </div>
            </div>
        </div>

        <div class="text-center mt-6 text-[10px] text-slate-600">
            Phone sensors → live modulation • Works on iOS Safari &amp; Android Chrome • Send feedback to the Beacon
        </div>

    </div>

    <script>
        // Tailwind script
        function initTailwind() {
            document.documentElement.style.setProperty('--accent', '#22d3ee');
        }

        // Keep all the original logic + enhance for new UI
        const defaults = {
            gains: [1.2, 1.0, 1.0, 1.0, 1.0, 1.3, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
            azs:   [180, 135, -90, -45, 45, 0, 0, 0, 0, 0, 0, 0, 0],
            dists: [2.0, 2.5, 3.0, 2.5, 2.0, 1.5, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
            qs:    [1.0, 0.5, 0.333, 0.25, 0.2, 0.167, 0.5, 0.333, 0.25, 0.2, 0.167, 0.143],
            solos: [0,0,0,0,0,0,0,0,0,0,0,0,0],
            mix: 0.85, master: 0.9
        };

        function send(param, band, value) {
            if (!Number.isFinite(parseFloat(value))) return;
            fetch('/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({address: '/beacon/' + param + '/' + band, value: parseFloat(value)})
            });
        }
        
        function sendGlobal(param, value) {
            const v = (typeof value === 'number' && !isNaN(value)) ? value : String(value);
            fetch('/control', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({address: '/beacon/' + param, value: v})
            });
        }
        
        function show(el, id) {
            const unit = id.startsWith('a') ? '°' : '';
            const target = document.getElementById(id);
            if (target) target.textContent = parseFloat(el.value).toFixed( id.startsWith('vq') ? 3 : 2 ) + unit;
        }
        
        function updateSpec(band, value) {
            const bar = document.getElementById('spec' + band);
            if (bar) bar.style.height = (parseFloat(value) / 3.0 * 100) + '%';
        }

        let recording = false;
        function toggleRecord(btn) {
            recording = !recording;
            const span = btn.querySelector('span') || btn;
            
            if (recording) {
                const preset = document.getElementById('load-select-large').value || 'session';
                sendGlobal('record/start', preset);
                btn.classList.add('!bg-red-600', '!border-red-600', '!text-white');
                span.textContent = 'STOP';
            } else {
                sendGlobal('record/stop', 0);
                btn.classList.remove('!bg-red-600', '!border-red-600', '!text-white');
                span.textContent = 'START';
            }
        }

        const soloState = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
        
        function toggleSolo(band, btn) {
            soloState[band - 1] = soloState[band - 1] ? 0 : 1;
            const isActive = soloState[band - 1];
            btn.classList.toggle('!bg-white', isActive);
            btn.classList.toggle('!text-black', isActive);
            btn.classList.toggle('!border-white', isActive);
            
            send('solo', band, isActive ? 1 : 0);
            
            const anySolo = soloState.some(s => s === 1);
            for (let i = 1; i <= 13; i++) {
                const card = document.getElementById('band' + i);
                if (card) {
                    if (anySolo && !soloState[i - 1]) {
                        card.style.opacity = '0.35';
                    } else {
                        card.style.opacity = '1';
                    }
                }
            }
        }

        function resetAll() {
            sendGlobal('reset', 1);
            
            for (let i = 1; i <= 13; i++) {
                const g = document.getElementById('gain' + i);
                const a = document.getElementById('az' + i);
                const d = document.getElementById('dist' + i);
                const q = document.getElementById('q' + i);
                const s = document.getElementById('s' + i);
                
                if (g) { g.value = defaults.gains[i-1]; show(g, 'g'+i); updateSpec(i, g.value); }
                if (a) { a.value = defaults.azs[i-1]; show(a, 'a'+i); }
                if (d) { d.value = defaults.dists[i-1]; show(d, 'd'+i); }
                if (q && defaults.qs[i-1]) { q.value = defaults.qs[i-1]; show(q, 'vq'+i); }
                if (s && soloState[i-1]) { toggleSolo(i, s); }
            }
            
            const mix = document.getElementById('mix');
            const master = document.getElementById('master');
            if (mix) { mix.value = defaults.mix; show(mix, 'vmix'); }
            if (master) { master.value = defaults.master; show(master, 'vmaster'); }
            
            const status = document.getElementById('config-status');
            if (status) {
                status.textContent = 'Reset to defaults';
                setTimeout(() => status.textContent = 'Presets ready', 1400);
            }
        }

        function gatherState() {
            const state = { 
                bands: [], 
                mix: parseFloat(document.getElementById('mix').value), 
                master: parseFloat(document.getElementById('master').value),
                sensor_mappings: getCurrentSensorMappings()
            };
            for (let i = 1; i <= 13; i++) {
                const b = { 
                    gain: parseFloat(document.getElementById('gain'+i).value), 
                    az: parseFloat(document.getElementById('az'+i).value), 
                    dist: parseFloat(document.getElementById('dist'+i).value), 
                    solo: soloState[i-1] 
                };
                const q = document.getElementById('q'+i);
                if (q) { const value = parseFloat(q.value); b.q = Number.isFinite(value) && value >= .01 && value <= 2 ? value : defaults.qs[i-1]; }
                state.bands.push(b);
            }
            return state;
        }

        function applyState(state) {
            for (let i = 1; i <= 13; i++) {
                const b = state.bands[i-1];
                const g = document.getElementById('gain'+i);
                const a = document.getElementById('az'+i);
                const d = document.getElementById('dist'+i);
                const q = document.getElementById('q'+i);
                const s = document.getElementById('s'+i);
                
                if (g) { g.value = b.gain; send('gain', i, b.gain); show(g, 'g'+i); updateSpec(i, b.gain); }
                if (a) { a.value = b.az; send('az', i, b.az); show(a, 'a'+i); }
                if (d) { d.value = b.dist; send('dist', i, b.dist); show(d, 'd'+i); }
                if (q) { const value = Number.isFinite(b.q) && b.q >= .01 && b.q <= 2 ? b.q : defaults.qs[i-1]; q.value = value; send('q', i, value); show(q, 'vq'+i); }
                if (s && b.solo !== soloState[i-1]) { toggleSolo(i, s); }
            }
            
            const mix = document.getElementById('mix');
            const master = document.getElementById('master');
            if (mix) { mix.value = state.mix; sendGlobal('mix', state.mix); show(mix, 'vmix'); }
            if (master) { master.value = state.master; sendGlobal('master', state.master); show(master, 'vmaster'); }

            if (state.sensor_mappings) {
                const ta = document.getElementById('sensor-mapping-json');
                if (ta) {
                    ta.value = JSON.stringify(state.sensor_mappings, null, 2);
                }
                buildSensorMappingUI();
            }
        }

        // === Sensor Logic (kept and enhanced) ===
        let currentSensors = {};
        // Unwrap state for yaw (alpha). The browser delivers alpha as a
        // compass bearing 0..360 that wraps at 0/360. When the user
        // rotates past 180 -> -180 the raw value JUMPS (179 -> -179),
        // which makes the spatialization feel glitchy. We track the
        // cumulative angle (no wrap) and the most recent raw alpha so
        // unwrapYaw() can subtract the wrap correctly.
        let yawUnwrapped = 0;
        let yawLastAlpha = null;
        // Center / "calibration" offsets. When LIVE is pressed we
        // capture the current pose as the new zero, so the user
        // starts the session in whatever position feels natural to
        // them. Updates to these are applied to every subsequent
        // deviceorientation event in the listener.
        let centerOffset = { yaw: 0, pitch: 0, roll: 0 };
        let centerCalibrated = false;  // true after the first reading post-LIVE
        let liveSensorsActive = false;
        let sensorInfluence = 0.65;
        let lastSensorSend = 0;
        let orientationCanvasCtx = null;
        let sensorVizInterval = null;  // single shared interval, cleared on STOP/leave

        function updateSensorInfluence(val) {
            sensorInfluence = parseFloat(val);
            const el = document.getElementById('influence-val');
            if (el) el.textContent = parseFloat(val).toFixed(2);
        }

        function requestSensorPermissions() {
            const statusEl = document.getElementById('sensor-status');
            if (statusEl) statusEl.innerHTML = '<i class="fa-solid fa-circle text-amber-400 text-[8px]"></i> <span>Requesting...</span>';
            
            let promises = [];
            if (typeof DeviceOrientationEvent !== 'undefined' && typeof DeviceOrientationEvent.requestPermission === 'function') {
                promises.push(DeviceOrientationEvent.requestPermission());
            }
            if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
                promises.push(DeviceMotionEvent.requestPermission());
            }
            
            Promise.all(promises).then(() => {
                if (statusEl) statusEl.innerHTML = '<i class="fa-solid fa-circle text-emerald-400 text-[8px]"></i> <span>Permissions OK</span>';
                startSensorListeners();
            }).catch(err => {
                if (statusEl) statusEl.innerHTML = '<i class="fa-solid fa-circle text-red-400 text-[8px]"></i> <span>Permission denied</span>';
            });
        }

        // Unwrap a compass bearing sequence (0..360) into a continuous
        // accumulating angle with no wrap. Each call integrates one new
        // sample; on the first call we just seed with the raw value.
        // We expose the helper as window.__unwrapYaw for the debug panel.
        function unwrapYaw(rawAlpha) {
            if (rawAlpha == null || isNaN(rawAlpha)) return yawUnwrapped;
            if (yawLastAlpha === null) {
                yawLastAlpha = rawAlpha;
                yawUnwrapped = rawAlpha;
                return yawUnwrapped;
            }
            let delta = rawAlpha - yawLastAlpha;
            // If the delta is more than 180 in absolute value, the sensor
            // crossed the 0/360 wrap point; correct by adding/subtracting 360.
            if (delta > 180)  delta -= 360;
            if (delta < -180) delta += 360;
            yawUnwrapped += delta;
            yawLastAlpha = rawAlpha;
            return yawUnwrapped;
        }
        window.__unwrapYaw = unwrapYaw;

        // Same idea for pitch (beta) — flips phone face-down makes beta
        // jump 180 → -180. Unwrap to a continuous accumulating angle.
        let pitchUnwrapped = 0;
        let pitchLastBeta = null;
        function unwrapPitch(rawBeta) {
            if (rawBeta == null || isNaN(rawBeta)) return pitchUnwrapped;
            if (pitchLastBeta === null) {
                pitchLastBeta = rawBeta;
                pitchUnwrapped = rawBeta;
                return pitchUnwrapped;
            }
            let delta = rawBeta - pitchLastBeta;
            if (delta > 180)  delta -= 360;
            if (delta < -180) delta += 360;
            pitchUnwrapped += delta;
            pitchLastBeta = rawBeta;
            return pitchUnwrapped;
        }
        window.__unwrapPitch = unwrapPitch;

        // And roll (gamma). Less common to wrap, but the same logic
        // applies if the user holds the phone at extreme angles.
        let rollUnwrapped = 0;
        let rollLastGamma = null;
        function unwrapRoll(rawGamma) {
            if (rawGamma == null || isNaN(rawGamma)) return rollUnwrapped;
            if (rollLastGamma === null) {
                rollLastGamma = rawGamma;
                rollUnwrapped = rawGamma;
                return rollUnwrapped;
            }
            let delta = rawGamma - rollLastGamma;
            if (delta > 180)  delta -= 360;
            if (delta < -180) delta += 360;
            rollUnwrapped += delta;
            rollLastGamma = rawGamma;
            return rollUnwrapped;
        }
        window.__unwrapRoll = unwrapRoll;

        function startSensorListeners() {
            window.addEventListener('deviceorientation', (event) => {
                const rawAlpha = event.alpha || 0;
                const rawBeta = event.beta || 0;
                const rawGamma = event.gamma || 0;
                // Store BOTH raw and offset-applied values:
                //  - raw (yawRaw etc) so the debug panel can show the wrap
                //  - centered values (yaw/pitch/roll) for the spatial
                //    mapping so the user can pick any "neutral" pose.
                // The unwrap* helpers make the centered value monotonic
                // even when the user rotates past the 180/-180 boundary.
                const unwrappedYaw   = unwrapYaw(rawAlpha);
                const unwrappedPitch = unwrapPitch(rawBeta);
                const unwrappedRoll  = unwrapRoll(rawGamma);
                currentSensors.yaw   = unwrappedYaw   - centerOffset.yaw;
                currentSensors.yawRaw = rawAlpha;
                currentSensors.pitch = unwrappedPitch - centerOffset.pitch;
                currentSensors.pitchRaw = rawBeta;
                currentSensors.roll  = unwrappedRoll  - centerOffset.roll;
                currentSensors.rollRaw = rawGamma;
                updateSensorDisplay();
                drawOrientationCanvas();
                if (liveSensorsActive) throttledSensorSend();
            }, true);

            window.addEventListener('devicemotion', (event) => {
                const acc = event.acceleration || event.accelerationIncludingGravity || {};
                const ax = acc.x || 0, ay = acc.y || 0, az = acc.z || 0;
                currentSensors.accel = Math.sqrt(ax*ax + ay*ay + az*az);
                
                const rot = event.rotationRate || {};
                const rx = rot.alpha || 0, ry = rot.beta || 0, rz = rot.gamma || 0;
                currentSensors.rotrate = Math.sqrt(rx*rx + ry*ry + rz*rz);
                
                updateSensorDisplay();
                if (liveSensorsActive) throttledSensorSend();
            }, true);
            
            const status = document.getElementById('sensor-status');
            if (status) status.innerHTML = '<i class="fa-solid fa-circle text-emerald-400 text-[8px]"></i> <span>Sensors active</span>';
        }

        function updateSensorDisplay() {
            // Update the sensor cards (populated by buildSensorCards)
            const cards = document.getElementById('sensor-cards');
            if (!cards) return;

            const sensors = [
                {key: 'yaw', label: 'YAW', unit: '°', color: '#f59e0b'},
                {key: 'pitch', label: 'PITCH', unit: '°', color: '#10b981'},
                {key: 'roll', label: 'ROLL', unit: '°', color: '#8b5cf6'},
                {key: 'accel', label: 'ACCEL', unit: 'm/s²', color: '#ef4444'}
            ];

            sensors.forEach(s => {
                const valEl = document.getElementById('sensor-val-' + s.key);
                const barEl = document.getElementById('sensor-bar-' + s.key);
                if (valEl) {
                    let v = currentSensors[s.key] || 0;
                    // Yaw is already unwrapped (no wrap at 180/-180). Show
                    // the actual continuous angle, mod 720 so the display
                    // stays readable after many rotations.
                    if (s.key === 'yaw') {
                        const shown = ((v % 720) + 720) % 720 - 360;
                        valEl.textContent = (v >= 0 ? '+' : '') + v.toFixed(0) + '° (' + shown.toFixed(0) + '°)';
                    } else {
                        valEl.textContent = v.toFixed(1) + s.unit;
                    }
                }
                if (barEl) {
                    let pct = 50;
                    let v = currentSensors[s.key] || 0;
                    if (s.key === 'yaw') {
                        // Map -360..360 to 0..100%, so the bar oscillates as
                        // the user rotates and visibly resets when they
                        // spin through 0 (vs. the old hard jump at 180).
                        pct = Math.min(100, Math.max(0, (v + 360) / 720 * 100));
                    }
                    else if (s.key === 'pitch') pct = Math.min(100, Math.max(0, (v + 90) / 180 * 100));
                    else if (s.key === 'roll') pct = Math.min(100, Math.max(0, (v + 90) / 180 * 100));
                    else if (s.key === 'accel') pct = Math.min(100, v * 15);
                    barEl.style.width = pct + '%';
                }
            });
        }

        function drawOrientationCanvas() {
            const canvas = document.getElementById('orientation-canvas');
            if (!canvas || !orientationCanvasCtx) return;
            const ctx = orientationCanvasCtx;
            const w = canvas.width;
            const h = canvas.height;
            
            ctx.clearRect(0, 0, w, h);
            
            const yaw = currentSensors.yaw || 0;
            const pitch = currentSensors.pitch || 0;
            const roll = currentSensors.roll || 0;

            // Background circle
            ctx.strokeStyle = '#1f2937';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(w/2, h/2 + 10, 52, 0, Math.PI * 2);
            ctx.stroke();

            // Horizon line (pitch influence). Clamp pitch to the canvas
            // bounds so unwrapped large values don't push it off-screen;
            // the underlying currentSensors.pitch still flows unbounded
            // to the spatial mapping.
            ctx.strokeStyle = '#475569';
            ctx.lineWidth = 1.5;
            const pitchForCanvas = Math.max(-90, Math.min(90, pitch));
            const horizonY = h/2 + 10 + (pitchForCanvas * 0.35);
            ctx.beginPath();
            ctx.moveTo(w/2 - 55, horizonY);
            ctx.lineTo(w/2 + 55, horizonY);
            ctx.stroke();

            // Yaw arrow — the canvas only shows the cardinal direction,
            // so we use the unwrapped yaw mod 360 to keep the arrow at
            // the correct bearing without spin-jumping.
            ctx.save();
            ctx.translate(w/2, h/2 + 10);
            const yawForArrow = ((yaw % 360) + 360) % 360;
            ctx.rotate((yawForArrow - 180) * Math.PI / 180);
            
            ctx.strokeStyle = '#f59e0b';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(0, -28);
            ctx.lineTo(0, 28);
            ctx.stroke();
            
            // Arrow head
            ctx.fillStyle = '#f59e0b';
            ctx.beginPath();
            ctx.moveTo(0, -28);
            ctx.lineTo(-8, -18);
            ctx.lineTo(8, -18);
            ctx.fill();
            ctx.restore();
            
            // Roll indicator
            ctx.strokeStyle = '#8b5cf6';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.arc(w/2 + 70, h/2 + 10, 18, 0, Math.PI * 2);
            ctx.stroke();
            
            ctx.fillStyle = '#8b5cf6';
            const rollRad = (roll * 0.01745);
            ctx.beginPath();
            ctx.arc(w/2 + 70 + Math.cos(rollRad) * 18, h/2 + 10 + Math.sin(rollRad) * 18, 4, 0, Math.PI * 2);
            ctx.fill();
            
            // Label
            const label = document.getElementById('orientation-label');
            if (label) {
                // Show unwrapped yaw as the canonical "how much have you
                // turned" reading, plus the cardinal bearing mod 360 so
                // the user can also see which compass direction they're
                // facing right now.
                const yawShown = ((yaw % 360) + 360) % 360;
                label.textContent = `Y:${yaw.toFixed(0)}° (→${yawShown.toFixed(0)}°) P:${pitch.toFixed(0)}° R:${roll.toFixed(0)}°`;
            }
        }

        function parseBands(bandsSpec) {
            if (!bandsSpec) return [];
            if (typeof bandsSpec === 'string') {
                if (bandsSpec === 'all') return Array.from({length:13}, (_,i)=>i+1);
                if (bandsSpec === 'low') return [1,2,3,4,5,6];
                if (bandsSpec === 'high') return [7,8,9,10,11,12,13];
                if (bandsSpec.includes('-')) {
                    const [s,e] = bandsSpec.split('-').map(Number);
                    return Array.from({length: e-s+1}, (_,i)=>s+i);
                }
                return bandsSpec.split(',').map(s => parseInt(s.trim())).filter(Boolean);
            }
            return Array.isArray(bandsSpec) ? bandsSpec : [];
        }

        function throttledSensorSend() {
            const now = Date.now();
            if (now - lastSensorSend < 55) return;
            lastSensorSend = now;
            computeAndSendSensorUpdates();
        }

        function computeAndSendSensorUpdates() {
            if (!liveSensorsActive || sensorInfluence <= 0) return;
            const mappings = getCurrentSensorMappings();
            const influence = sensorInfluence;

            // Build a single batch of updates so we send ONE HTTP request per
            // tick instead of N (one per band). This keeps the browser's
            // connection pool happy and the UI feels fluid.
            const updates = [];
            Object.entries(mappings).forEach(([sensorKey, map]) => {
                if (!map.enabled) return;

                let sensorVal = 0;
                if (sensorKey === 'yaw') {
                    // Already unwrapped by the listener — no % 360 here.
                    // Scale defaults to 1.0 → mod(-inf, +inf) range. UI
                    // mapping on the bands controls how fast az sweeps.
                    sensorVal = currentSensors.yaw || 0;
                }
                else if (sensorKey === 'pitch') sensorVal = currentSensors.pitch || 0;
                else if (sensorKey === 'roll') sensorVal = currentSensors.roll || 0;
                else if (sensorKey === 'accel') sensorVal = Math.max(0, (currentSensors.accel || 0) - 1) * 0.5;
                else if (sensorKey === 'rotrate') sensorVal = currentSensors.rotrate || 0;

                const targetParam = map.param;
                const bands = parseBands(map.bands);
                const scale = (map.scale || 1) * influence;
                const offset = map.offset || 0;

                let computed = sensorVal * scale + offset;

                if (targetParam === 'az') computed = Math.max(-180, Math.min(180, computed));
                if (targetParam === 'dist') computed = Math.max(0.5, Math.min(10, computed));
                if (targetParam === 'gain') computed = Math.max(0, Math.min(3, computed));
                if (targetParam === 'q') computed = Math.max(0.1, Math.min(2, computed));

                const isGlobal = (targetParam === 'mix' || targetParam === 'master');
                bands.forEach(bandIdx => {
                    const addr = isGlobal
                        ? `/beacon/${targetParam}`
                        : `/beacon/${targetParam}/${bandIdx}`;
                    updates.push({address: addr, value: computed});
                });
            });

            if (updates.length === 0) return;

            // Fire-and-forget: keepalive lets the browser send without holding
            // a connection open. No .then() / .catch() — sensor pipeline
            // shouldn't await ack on the critical path.
            try {
                fetch('/control/batch', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({updates: updates}),
                    keepalive: true
                });
            } catch (e) {
                // ignore — we don't care about the response on the audio path
            }
        }

        // === Beautiful new sensor mapping UI ===
        function buildSensorMappingUI() {
            const container = document.getElementById('sensor-mapping-rows');
            if (!container) return;
            
            const mappings = getCurrentSensorMappings();
            container.innerHTML = '';

            const sensors = ['yaw', 'pitch', 'roll', 'accel'];
            const paramOptions = ['az', 'dist', 'gain', 'q', 'mix', 'master'];
            const bandOptions = ['1-6', 'low', '7-12', 'high', 'all'];

            sensors.forEach(sensor => {
                const map = mappings[sensor] || {param: 'az', bands: '1-6', scale: 1, offset: 0, enabled: true};
                
                const row = document.createElement('div');
                row.className = 'sensor-card rounded-2xl p-3 flex flex-col gap-2';
                
                row.innerHTML = `
                    <div class="flex items-center justify-between">
                        <div class="font-semibold text-sm flex items-center gap-2" style="color: ${sensor === 'yaw' ? '#f59e0b' : sensor === 'pitch' ? '#10b981' : sensor === 'roll' ? '#8b5cf6' : '#ef4444'}">
                            <i class="fa-solid ${sensor === 'yaw' ? 'fa-compass' : sensor === 'pitch' ? 'fa-arrow-up' : sensor === 'roll' ? 'fa-sync' : 'fa-bolt'}"></i>
                            <span class="uppercase tracking-wider">${sensor}</span>
                        </div>
                        <label class="flex items-center gap-1 text-xs cursor-pointer">
                            <input type="checkbox" data-sensor="${sensor}" data-field="enabled" ${map.enabled ? 'checked' : ''} class="accent-cyan-400">
                            <span class="text-emerald-400 text-xs">ON</span>
                        </label>
                    </div>
                    
                    <div class="grid grid-cols-5 gap-2">
                        <div class="col-span-2">
                            <div class="text-[10px] text-slate-400 mb-0.5">PARAM</div>
                            <select data-sensor="${sensor}" data-field="param" class="bg-slate-950 border border-slate-700 text-xs rounded-xl px-2 py-1 w-full">
                                ${paramOptions.map(p => `<option value="${p}" ${map.param===p?'selected':''}>${p}</option>`).join('')}
                            </select>
                        </div>
                        <div class="col-span-2">
                            <div class="text-[10px] text-slate-400 mb-0.5">BANDS</div>
                            <select data-sensor="${sensor}" data-field="bands" class="bg-slate-950 border border-slate-700 text-xs rounded-xl px-2 py-1 w-full">
                                ${bandOptions.map(b => `<option value="${b}" ${map.bands===b?'selected':''}>${b}</option>`).join('')}
                            </select>
                        </div>
                        <div>
                            <div class="text-[10px] text-slate-400 mb-0.5">SCALE</div>
                            <input type="number" step="0.1" data-sensor="${sensor}" data-field="scale" value="${map.scale}" 
                                   class="bg-slate-950 border border-slate-700 text-xs rounded-xl px-2 py-1 w-full font-mono">
                        </div>
                    </div>
                    <div class="grid grid-cols-5 gap-2">
                        <div class="col-span-2">
                            <div class="text-[10px] text-slate-400 mb-0.5">OFFSET</div>
                            <input type="number" step="0.1" data-sensor="${sensor}" data-field="offset" value="${map.offset}" 
                                   class="bg-slate-950 border border-slate-700 text-xs rounded-xl px-2 py-1 w-full font-mono">
                        </div>
                    </div>
                `;
                
                container.appendChild(row);
                
                // listeners
                row.querySelectorAll('select, input').forEach(el => {
                    const handler = () => {
                        syncMappingFromUI();
                        updateDebugViz();
                    };
                    el.addEventListener('change', handler);
                    el.addEventListener('input', handler);
                });
            });
        }

        function syncMappingFromUI() {
            const container = document.getElementById('sensor-mapping-rows');
            if (!container) return;
            
            const newMappings = {};
            container.querySelectorAll('.sensor-card').forEach(card => {
                const sensor = card.querySelector('select[data-field="param"]').getAttribute('data-sensor');
                newMappings[sensor] = {
                    param: card.querySelector('select[data-field="param"]').value,
                    bands: card.querySelector('select[data-field="bands"]').value,
                    scale: parseFloat(card.querySelector('input[data-field="scale"]').value) || 1,
                    offset: parseFloat(card.querySelector('input[data-field="offset"]').value) || 0,
                    enabled: card.querySelector('input[data-field="enabled"]').checked
                };
            });
            
            const ta = document.getElementById('sensor-mapping-json');
            if (ta) ta.value = JSON.stringify(newMappings, null, 2);
        }

        function getCurrentSensorMappings() {
            const ta = document.getElementById('sensor-mapping-json');
            if (!ta || !ta.value.trim()) return getDefaultSensorMappings();
            try {
                return JSON.parse(ta.value);
            } catch (e) {
                return getDefaultSensorMappings();
            }
        }

        function getDefaultSensorMappings() {
            return {
                "yaw": { "param": "az", "bands": "1-6", "scale": 1.0, "offset": 0, "enabled": true },
                "pitch": { "param": "dist", "bands": "1-6", "scale": 0.025, "offset": 2.0, "enabled": true },
                "roll": { "param": "q", "bands": "7-12", "scale": 0.6, "offset": 0, "enabled": true },
                "accel": { "param": "gain", "bands": "1-6", "scale": 0.35, "offset": 0, "enabled": true }
            };
        }

        function updateDebugViz() {
            const drivingEl = document.getElementById('sensor-driving');
            if (!drivingEl || !liveSensorsActive) return;

            const mappings = getCurrentSensorMappings();
            const influence = sensorInfluence;
            let lines = [];

            Object.entries(mappings).forEach(([sensorKey, map]) => {
                if (!map.enabled) return;
                
                let sensorVal = currentSensors[sensorKey] || 0;
                if (sensorKey === 'yaw') sensorVal = ((sensorVal + 180) % 360) - 180;
                if (sensorKey === 'accel') sensorVal = Math.max(0, sensorVal - 1) * 0.5;

                const computed = sensorVal * (map.scale || 1) * influence + (map.offset || 0);
                const addr = `/beacon/${map.param}` + (map.param === 'mix' || map.param === 'master' ? '' : ' (' + map.bands + ')');
                
                lines.push(`${sensorKey.toUpperCase()} → ${map.param} ${map.bands}: ${computed.toFixed(2)}`);
            });

            drivingEl.textContent = lines.length ? lines.join('\\n') : '(no active mappings)';
        }

        function buildSensorCards() {
            const container = document.getElementById('sensor-cards');
            if (!container) return;
            
            const sensors = [
                {key:'yaw', label:'YAW', unit:'°', color:'#f59e0b', icon:'fa-compass'},
                {key:'pitch', label:'PITCH', unit:'°', color:'#10b981', icon:'fa-arrow-up'},
                {key:'roll', label:'ROLL', unit:'°', color:'#8b5cf6', icon:'fa-sync-alt'},
                {key:'accel', label:'ACCEL', unit:'', color:'#ef4444', icon:'fa-bolt'}
            ];
            
            container.innerHTML = '';
            
            sensors.forEach(s => {
                const div = document.createElement('div');
                div.className = `sensor-card rounded-2xl p-3 border border-slate-700`;
                div.innerHTML = `
                    <div class="flex justify-between items-start">
                        <div>
                            <div class="flex items-center gap-1.5">
                                <i class="fa-solid ${s.icon}" style="color:${s.color}"></i>
                                <span class="text-xs font-bold tracking-widest" style="color:${s.color}">${s.label}</span>
                            </div>
                            <div id="sensor-val-${s.key}" class="big-value font-mono mt-0.5" style="color:${s.color}">—</div>
                        </div>
                        <div class="text-right">
                            <div class="w-14 h-1.5 bg-slate-800 rounded mt-1.5 overflow-hidden">
                                <div id="sensor-bar-${s.key}" class="h-1.5 transition-all" style="width:50%; background:${s.color}"></div>
                            </div>
                        </div>
                    </div>
                `;
                container.appendChild(div);
            });
        }

        function toggleLiveSensorsUI() {
            liveSensorsActive = !liveSensorsActive;
            const btn = document.getElementById('live-btn');
            const text = document.getElementById('live-text');

            if (liveSensorsActive) {
                btn.classList.remove('bg-emerald-500/10', 'border-emerald-500/30', 'text-emerald-400');
                btn.classList.add('bg-emerald-500', 'border-emerald-500', 'text-white');
                text.textContent = 'STOP';

                const status = document.getElementById('sensor-status');
                if (status) status.innerHTML = '<i class="fa-solid fa-circle text-emerald-400 text-[8px]"></i> <span>LIVE — calibrating center…</span>';

                if (!currentSensors.yaw && !currentSensors.pitch) startSensorListeners();

                // Calibrate the center from the next deviceorientation
                // event. We schedule a one-shot capture so we use a real
                // sensor reading (not zeros from the cold start) as the
                // user's "neutral" pose.
                centerCalibrated = false;
                const onFirstEvent = (ev) => {
                    if (centerCalibrated) return;
                    const a = (ev.alpha != null) ? ev.alpha : 0;
                    const b = (ev.beta  != null) ? ev.beta  : 0;
                    const g = (ev.gamma != null) ? ev.gamma : 0;
                    // Reset unwrap state so the offset is applied against
                    // a clean baseline.
                    yawUnwrapped = a; yawLastAlpha = a;
                    pitchUnwrapped = b; pitchLastBeta = b;
                    rollUnwrapped = g; rollLastGamma = g;
                    centerOffset = { yaw: a, pitch: b, roll: g };
                    centerCalibrated = true;
                    if (status) status.innerHTML = '<i class="fa-solid fa-circle text-emerald-400 text-[8px]"></i> <span>LIVE — centered. Move freely.</span>';
                    window.removeEventListener('deviceorientation', onFirstEvent, true);
                };
                window.addEventListener('deviceorientation', onFirstEvent, true);

                // Viz loop: single shared interval, no leak on toggle
                if (sensorVizInterval) clearInterval(sensorVizInterval);
                sensorVizInterval = setInterval(() => {
                    if (!liveSensorsActive) return;
                    updateDebugViz();
                    drawOrientationCanvas();
                }, 160);
            } else {
                btn.classList.add('bg-emerald-500/10', 'border-emerald-500/30', 'text-emerald-400');
                btn.classList.remove('bg-emerald-500', 'border-emerald-500', 'text-white');
                text.textContent = 'LIVE';

                const status = document.getElementById('sensor-status');
                if (status) status.innerHTML = '<i class="fa-solid fa-circle text-slate-400 text-[8px]"></i> <span>Live paused</span>';
            }
        }

        // Manual "set center to current pose" — usable mid-session if the
        // user wants to redefine "neutral" without stopping the live.
        function recenterSensors() {
            const a = currentSensors.yawRaw != null ? currentSensors.yawRaw : (currentSensors.yaw || 0);
            const b = currentSensors.pitchRaw != null ? currentSensors.pitchRaw : (currentSensors.pitch || 0);
            const g = currentSensors.rollRaw != null ? currentSensors.rollRaw : (currentSensors.roll || 0);
            // Reset unwrap accumulators so subsequent values are relative
            // to this pose and stay monotonic.
            yawUnwrapped = a; yawLastAlpha = a;
            pitchUnwrapped = b; pitchLastBeta = b;
            rollUnwrapped = g; rollLastGamma = g;
            centerOffset = { yaw: a, pitch: b, roll: g };
            centerCalibrated = true;
            const status = document.getElementById('sensor-status');
            if (status) status.innerHTML = '<i class="fa-solid fa-circle text-emerald-400 text-[8px]"></i> <span>Recentered.</span>';
        }

        function getSensorMappingJSONEl() {
            let ta = document.getElementById('sensor-mapping-json');
            if (!ta) {
                ta = document.createElement('textarea');
                ta.id = 'sensor-mapping-json';
                ta.style.display = 'none';
                document.body.appendChild(ta);
            }
            return ta;
        }

        function initSensorUI() {
            // Create hidden JSON textarea for compatibility
            const ta = getSensorMappingJSONEl();
            ta.value = JSON.stringify(getDefaultSensorMappings(), null, 2);
            
            // Build beautiful UI components
            buildSensorCards();
            buildSensorMappingUI();
            
            // Orientation canvas
            const canvas = document.getElementById('orientation-canvas');
            if (canvas) {
                orientationCanvasCtx = canvas.getContext('2d');
                // initial draw
                setTimeout(drawOrientationCanvas, 300);
            }
            
            // Influence init
            const inf = document.getElementById('sensor-influence');
            if (inf) {
                inf.value = sensorInfluence;
                const valEl = document.getElementById('influence-val');
                if (valEl) valEl.textContent = sensorInfluence.toFixed(2);
            }

            // Viz loop is created on first LIVE press (toggleLiveSensorsUI)
            // — not here, to avoid running before the user opts in.
        }

        function resetSensorMappingToDefault() {
            const ta = getSensorMappingJSONEl();
            ta.value = JSON.stringify(getDefaultSensorMappings(), null, 2);
        }

        function saveSensorConfigToPreset() {
            const nameInput = document.getElementById('save-name');
            if (nameInput && !nameInput.value.trim()) {
                nameInput.value = 'sensor-' + Date.now().toString(36);
            }
            saveConfig();
        }

        function exportSensorConfig() {
            const ta = getSensorMappingJSONEl();
            const data = ta.value || JSON.stringify(getCurrentSensorMappings(), null, 2);
            const blob = new Blob([data], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'beacon-sensor-mapping.json';
            a.click();
            URL.revokeObjectURL(url);
        }

        // Load/Save config (kept intact)
        function loadConfig() {
            const name = document.getElementById('load-select-large').value;
            if (!name) { 
                const status = document.getElementById('config-status');
                if (status) status.textContent = 'Select a preset';
                return; 
            }
            fetch('/load_config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name})
            }).then(r => r.json()).then(data => {
                if (data.ok && data.state) {
                    applyState(data.state);
                    const status = document.getElementById('config-status');
                    if (status) status.textContent = 'Loaded: ' + name;
                } else {
                    const status = document.getElementById('config-status');
                    if (status) status.textContent = 'Error loading';
                }
            }).catch(err => {
                const status = document.getElementById('config-status');
                if (status) status.textContent = 'Load error';
            });
        }

        function loadConfigList() {
            fetch('/list_configs').then(r => r.json()).then(data => {
                const sel = document.getElementById('load-select-large');
                sel.innerHTML = '<option value="">Load preset...</option>';
                (data.configs || []).forEach(c => {
                    const opt = document.createElement('option');
                    opt.value = c;
                    opt.textContent = c;
                    sel.appendChild(opt);
                });
            });
        }

        function saveConfig() {
            let name = document.getElementById('save-name').value.trim();
            if (!name) {
                name = document.getElementById('load-select-large').value;
                if (!name) {
                    const status = document.getElementById('config-status');
                    if (status) status.textContent = 'Enter a name or load a preset first';
                    return;
                }
                if (!confirm('Overwrite "' + name + '"?')) return;
            }
            const state = gatherState();
            
            fetch('/save_config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name: name, state: state})
            }).then(r => r.json()).then(data => {
                const status = document.getElementById('config-status');
                if (status) status.textContent = data.ok ? 'Saved: ' + name : 'Save failed';
                loadConfigList();
                setTimeout(() => { if (status) status.textContent = 'Presets ready'; }, 1800);
            });
        }

        // Initialize everything
        function initializeUI() {
            initTailwind();

            // Initial values for mix/master
            const mix = document.getElementById('mix');
            const master = document.getElementById('master');
            if (mix) show(mix, 'vmix');
            if (master) show(master, 'vmaster');

            // Wire up tab buttons
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const target = btn.getAttribute('data-tab-target');
                    switchTab(target);
                });
            });

            // Boot sensor stuff
            initSensorUI();
            loadConfigList();
            renderPresetCards();

            // Default influence
            updateSensorInfluence(sensorInfluence);

            // Restore last tab (or default to manual)
            const last = localStorage.getItem('beacon.activeTab') || 'manual';
            switchTab(last);

            // First paint of sensor debug panel
            updateSensorDebugPanel();

            // Keyboard hint
            console.log('%c[Beacon] Excellent UI loaded. Sensors ready for phone.', 'color:#64748b');
        }

        function switchTab(name) {
            // Show/hide panels
            document.querySelectorAll('.tab-panel').forEach(p => {
                p.hidden = p.getAttribute('data-tab') !== name;
            });
            // Style active button
            document.querySelectorAll('.tab-btn').forEach(b => {
                const active = b.getAttribute('data-tab-target') === name;
                b.classList.toggle('border-cyan-500/40', active);
                b.classList.toggle('bg-cyan-500/10', active);
                b.classList.toggle('text-cyan-300', active);
                b.classList.toggle('border-slate-700', !active);
                b.classList.toggle('bg-slate-900', !active);
                b.classList.toggle('text-slate-400', !active);
            });
            localStorage.setItem('beacon.activeTab', name);
        }

        function renderPresetCards() {
            fetch('/list_configs').then(r => r.json()).then(data => {
                const configs = data.configs || [];
                const big = document.getElementById('load-select-large');
                const small = document.getElementById('load-select');
                const cards = document.getElementById('preset-cards');
                const count = document.getElementById('preset-count');
                if (count) count.textContent = configs.length + ' files';

                if (big) {
                    big.innerHTML = '<option value="">— pick a preset —</option>';
                    configs.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c; opt.textContent = c;
                        big.appendChild(opt);
                    });
                }
                if (small) {
                    // The original top-bar small select (kept for back-compat)
                    small.innerHTML = '<option value="">Load preset...</option>';
                    configs.forEach(c => {
                        const opt = document.createElement('option');
                        opt.value = c; opt.textContent = c;
                        small.appendChild(opt);
                    });
                }
                if (cards) {
                    cards.innerHTML = '';
                    configs.forEach(c => {
                        const card = document.createElement('button');
                        card.className = 'text-left rounded-2xl border border-slate-800 bg-slate-900 hover:bg-slate-800 hover:border-cyan-500/40 transition-colors p-3';
                        card.innerHTML = '<div class="flex items-center gap-2 mb-1">' +
                            '<i class="fa-solid fa-file-audio text-cyan-400 text-sm"></i>' +
                            '<span class="font-mono text-sm text-slate-200">' + c + '</span>' +
                            '</div>' +
                            '<div class="text-[10px] text-slate-500">click to load</div>';
                        card.onclick = () => {
                            const big = document.getElementById('load-select-large');
                            if (big) big.value = c;
                            loadConfig();
                        };
                        cards.appendChild(card);
                    });
                }
            });
        }

        // === Sensor Debug Panel (no DevTools required) ===
        // Counter of received events — updated by listeners, read by debug panel.
        let sensorEventCounts = {deviceorientation: 0, devicemotion: 0, lastOrientTs: 0, lastMotionTs: 0};
        let sensorDebugErrors = [];
        let sensorFetchCount = 0;
        let sensorLastFetchTs = 0;
        let sensorFirstError = null;
        let sensorDebugLastRender = 0;

        function updateSensorDebugPanel() {
            // Throttle: skip if last render was <100ms ago (prevents excessive work
            // when called from the setInterval AND from event listeners).
            const el = document.getElementById('sensor-debug-panel');
            if (!el) return;
            const now = Date.now();
            if (now - sensorDebugLastRender < 100) return;
            sensorDebugLastRender = now;

            // Detect support (defensive: every property read wrapped in try)
            let hasOrient = false, hasMotion = false, needsPerm = false;
            let isSecure = false, isHttps = false, isLocal = false, uaStr = 'unknown';
            try {
                hasOrient = typeof DeviceOrientationEvent !== 'undefined';
                hasMotion = typeof DeviceMotionEvent !== 'undefined';
                needsPerm = !!(hasOrient && typeof DeviceOrientationEvent.requestPermission === 'function');
                isSecure = !!window.isSecureContext;
                isHttps = location.protocol === 'https:';
                isLocal = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
                const m = (navigator.userAgent || '').match(/(iPhone|iPad|iPod|Android|Macintosh|Linux|Windows)/i);
                uaStr = m ? m[0] : 'unknown';
            } catch (e) {
                sensorFirstError = sensorFirstError || ('detect: ' + e.message);
            }

            const orientAge = sensorEventCounts.lastOrientTs ? Math.round((now - sensorEventCounts.lastOrientTs) / 100) / 10 : null;
            const motionAge = sensorEventCounts.lastMotionTs ? Math.round((now - sensorEventCounts.lastMotionTs) / 100) / 10 : null;
            const fetchAge = sensorLastFetchTs ? Math.round((now - sensorLastFetchTs) / 100) / 10 : null;

            // Build with textContent (no HTML injection / no crash on null)
            const lines = [
                'browser:        ' + uaStr + ' / ' + location.protocol + '//' + location.hostname,
                'secureContext:  ' + isSecure,
                'HTTPS/local?    ' + (isHttps || isLocal ? 'YES ✓' : 'NO ✗ (sensors may be blocked on LAN http)'),
                'DeviceOrient:   ' + (hasOrient ? 'YES' : 'NO'),
                'DeviceMotion:   ' + (hasMotion ? 'YES' : 'NO'),
                'iOS perm API:   ' + (needsPerm ? 'YES (tap Permissions!)' : 'no'),
                'LIVE state:     ' + (liveSensorsActive ? 'ON' : 'OFF'),
                'orient events:  ' + sensorEventCounts.deviceorientation + (orientAge !== null ? '  (last: ' + orientAge + 's ago)' : '  (never)'),
                'motion events:  ' + sensorEventCounts.devicemotion + (motionAge !== null ? '  (last: ' + motionAge + 's ago)' : '  (never)'),
                'fetch /control: ' + sensorFetchCount + (fetchAge !== null ? '  (last: ' + fetchAge + 's ago)' : '  (never)'),
                'yaw raw→unwrap: ' + (currentSensors.yawRaw != null ? currentSensors.yawRaw.toFixed(0) + '° → ' + (currentSensors.yaw || 0).toFixed(0) + '°' : 'n/a'),
                'pitch raw→unwrap: ' + (currentSensors.pitchRaw != null ? currentSensors.pitchRaw.toFixed(0) + '° → ' + (currentSensors.pitch || 0).toFixed(0) + '°' : 'n/a'),
                'center offset:   ' + (centerCalibrated ? 'yaw=' + centerOffset.yaw.toFixed(0) + '° pitch=' + centerOffset.pitch.toFixed(0) + '° roll=' + centerOffset.roll.toFixed(0) + '°' : 'not calibrated'),
                'last error:     ' + (sensorFirstError || 'none'),
            ];

            // textContent assignment is safe (no HTML parsing, no XSS, no null crash)
            // Use String.fromCharCode(10) as a real newline (the JS escape
            // sequence breaks when this script is inside a Python
            // triple-quoted string and a literal newline creeps in).
            const NL = String.fromCharCode(10);
            try {
                el.textContent = lines.join(NL);
            } catch (e) {
                // Last-ditch fallback
            }

            // Add warnings as separate <div>s (only when applicable)
            try {
                let warnings = '';
                if (!isHttps && !isLocal) {
                    warnings += '<div class="text-amber-400 mt-1.5">⚠ sensors are BLOCKED on http://&lt;LAN-IP&gt;. Use https:// or tunnel via cloudflared/ngrok.</div>';
                }
                if (needsPerm && sensorEventCounts.deviceorientation === 0 && liveSensorsActive) {
                    warnings += '<div class="text-amber-400 mt-1.5">⚠ iOS: tap the Permissions button (top bar) — sensors need a one-time gesture unlock.</div>';
                }
                if (hasOrient && liveSensorsActive && sensorEventCounts.deviceorientation === 0 && (orientAge === null || orientAge > 2)) {
                    warnings += '<div class="text-amber-400 mt-1.5">⚠ LIVE is ON but no orientation events have arrived in 2s+.</div>';
                }
                // Append warnings as a sibling node we control
                let warnEl = document.getElementById('sensor-debug-warnings');
                if (!warnEl && warnings) {
                    warnEl = document.createElement('div');
                    warnEl.id = 'sensor-debug-warnings';
                    el.parentNode?.insertBefore(warnEl, el.nextSibling);
                }
                if (warnEl) warnEl.innerHTML = warnings;
            } catch (e) {
                // ignore
            }
        }

        // Hook into listeners to count events.
        // We add our own listeners that ONLY count, so they coexist with
        // the real sensor listeners installed by startSensorListeners().
        window.addEventListener('deviceorientation', () => {
            sensorEventCounts.deviceorientation++;
            sensorEventCounts.lastOrientTs = Date.now();
        }, true);
        window.addEventListener('devicemotion', () => {
            sensorEventCounts.devicemotion++;
            sensorEventCounts.lastMotionTs = Date.now();
        }, true);

        // Hook fetch to count /control calls (defensive: check Function is OK)
        try {
            const __origFetch = window.fetch;
            if (__origFetch && !window.__beaconFetchHooked) {
                window.__beaconFetchHooked = true;
                window.fetch = function(url, opts) {
                    try {
                        const u = (typeof url === 'string') ? url : (url?.url || '');
                        if (u.includes('/control')) {
                            sensorFetchCount++;
                            sensorLastFetchTs = Date.now();
                        }
                    } catch (e) { /* ignore */ }
                    return __origFetch.apply(this, arguments);
                };
            }
        } catch (e) {
            sensorFirstError = sensorFirstError || ('fetch hook: ' + e.message);
        }

        // Capture errors globally
        try {
            window.addEventListener('error', e => {
                sensorFirstError = sensorFirstError || (e.message + ' @ ' + (e.filename || '') + ':' + (e.lineno || ''));
            });
            window.addEventListener('unhandledrejection', e => {
                sensorFirstError = sensorFirstError || 'promise: ' + String(e.reason).substring(0, 200);
            });
        } catch (e) { /* ignore */ }

        // Auto-refresh the debug panel every 500ms
        setInterval(updateSensorDebugPanel, 500);

        // Also update right after a sensor event fires (immediate feedback)
        const __updateAfterOrient = () => { sensorDebugLastRender = 0; updateSensorDebugPanel(); };
        window.addEventListener('deviceorientation', __updateAfterOrient, true);
        window.addEventListener('devicemotion', __updateAfterOrient, true);

        function loadConfigFromLargeSelect() {
            loadConfig();
        }

        window.onload = initializeUI;
    </script>
</body>
</html>"""

@app.route("/")
def index():
    return render_template_string(HTML, bands=BANDS)

def valid_q(address, value):
    """Invalid saved/browser values must never become zero-width filters."""
    if not re.fullmatch(r"/beacon/q/(?:[1-9]|1[0-2])", address):
        return True
    try:
        return value is not None and not isinstance(value, bool) and math.isfinite(float(value)) and 0.01 <= float(value) <= 2
    except (TypeError, ValueError):
        return False


def repair_preset_q(state):
    """Recover the old duplicate-DOM-ID save bug without altering other controls."""
    state = json.loads(json.dumps(state))
    for i, band in enumerate(state.get("bands", [])[:12]):
        if not valid_q(f"/beacon/q/{i+1}", band.get("q")):
            band["q"] = BANDS[i]["default_q"]
    return state


@app.route("/control", methods=["POST"])
def control():
    data = request.get_json()
    addr = data.get("address", "")
    val = data.get("value", 0)
    if not valid_q(addr, val):
        return jsonify({"ok": False, "error": "Q must be a finite value between0.01 and2"}), 400
    if addr == "/beacon/record/start":
        label = str(val) if val is not None else "session"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_") or "session"
        ts = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(RECORD_DIR, f"{safe}_{ts}.wav")
        osc.send_message(addr, path)
        return jsonify({"ok": True, "path": path})
    # OSC value must be numeric; coerce strings to float when possible.
    # record/start|stop can carry a non-numeric label, so we forward a
    # numeric 1/0 to sclang and use the address itself to convey intent.
    try:
        val = float(val)
    except (TypeError, ValueError):
        val = 1.0 if isinstance(val, str) and val else 0.0
    osc.send_message(addr, val)
    # Also forward to PD replica sclang (port 9001) if running
    try:
        osc_pd.send_message(addr, val)
    except Exception:
        pass  # PD replica not running — silently ignore
    return jsonify({"ok": True})

@app.route("/control/batch", methods=["POST"])
def control_batch():
    # Sensor pipeline sends all per-tick updates in one POST so the
    # browser's connection pool isn't exhausted at high event rates.
    data = request.get_json() or {}
    updates = data.get("updates") or []
    if not isinstance(updates, list):
        return jsonify({"ok": False, "error": "updates must be a list"}), 400
    sent = 0
    for u in updates:
        if not isinstance(u, dict):
            continue
        addr = u.get("address", "")
        raw = u.get("value", 0)
        if not valid_q(addr, raw):
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = 1.0 if isinstance(raw, str) and raw else 0.0
        try:
            osc.send_message(addr, val)
            sent += 1
        except Exception:
            pass
        try:
            osc_pd.send_message(addr, val)
        except Exception:
            pass
    return jsonify({"ok": True, "sent": sent})

@app.route("/save_config", methods=["POST"])
def save_config():
    data = request.get_json()
    name = data.get("name", "").strip()
    state = repair_preset_q(data.get("state", {}))
    if not name:
        return jsonify({"ok": False, "error": "No name"})
    path = os.path.join(CONFIG_DIR, name + ".json")
    with open(path, "w") as f:
        json.dump(state, f, indent=2)
    return jsonify({"ok": True})

@app.route("/list_configs")
def list_configs():
    files = sorted(glob.glob(os.path.join(CONFIG_DIR, "*.json")))
    configs = [os.path.splitext(os.path.basename(f))[0] for f in files]
    return jsonify({"ok": True, "configs": configs})

@app.route("/load_config", methods=["POST"])
def load_config():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "No name"})
    path = os.path.join(CONFIG_DIR, name + ".json")
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "Not found"})
    with open(path) as f:
        state = repair_preset_q(json.load(f))
    return jsonify({"ok": True, "state": state})

if __name__ == "__main__":
    print("=" * 50)
    print("Harmonic Beacon Web UI")
    print("=" * 50)
    print("Open your browser at: http://localhost:5050")
    print("Make sure start-beacon.sh (scsynth + sclang/beacon.scd) is running!")
    print("=" * 50)
    # threaded=True so concurrent sensor-batch POSTs don't serialize
    # behind each other on the Werkzeug dev server's main request loop.
    app.run(host=os.environ.get("BEACON_WEB_HOST", "0.0.0.0"), port=5050, debug=False, threaded=True)
