"""KiCad-style wiring schematic of the HydroPin prototype bench (A3, one sheet).

Pure SVG generator (no KiCad needed), drawn with KiCad's default plot colours:
wires green, symbol outlines and pins dark red, symbol bodies pale yellow,
references/values teal, graphic notes blue, no-connect flags blue.
Source of every connection: hardware list of 18 Nov 2026, "Power and wiring",
plus the corrections of 23 Nov (flow-sensor divider 10 k / 20 k,
pump on its own ground, optional 100 nF filters).

Outputs in results/wiring/: .svg, .pdf, .png   (python run/wiring.py)
"""

from __future__ import annotations

from pathlib import Path

import cairosvg

W, H = 1680, 1188                      # A3 landscape, 4 px per mm
WIRE, BODY, FILL, REF, NOTE, PIN_NAME = "#009600", "#840000", "#FFFFC2", "#006464", "#0000C2", "#006464"
FONT = "DejaVu Sans"


class Sheet:
    def __init__(self):
        self.parts: list[str] = []

    def add(self, s: str):
        self.parts.append(s)

    # ── primitives ──────────────────────────────────────────────────────────────
    def line(self, x1, y1, x2, y2, c=BODY, w=2.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="{w}" stroke-linecap="round"{d}/>')

    def wire(self, *pts):
        p = " ".join(f"{x},{y}" for x, y in pts)
        self.add(f'<polyline points="{p}" fill="none" stroke="{WIRE}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')

    def dot(self, x, y):
        self.add(f'<circle cx="{x}" cy="{y}" r="4.5" fill="{WIRE}"/>')

    def text(self, x, y, s, size=13, c=REF, anchor="start", weight="normal", italic=False, rot=None):
        tr = f' transform="rotate({rot} {x} {y})"' if rot is not None else ""
        st = ' font-style="italic"' if italic else ""
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.add(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" fill="{c}" text-anchor="{anchor}" '
                 f'font-weight="{weight}"{st}{tr}>{s}</text>')

    def rect(self, x, y, w, h, c=BODY, fill=FILL, sw=2.0, dash=None, rx=0):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{c}" stroke-width="{sw}"{d}/>')

    # ── symbols ─────────────────────────────────────────────────────────────────
    def pin(self, x1, y1, x2, y2, num=None, name=None, side="left"):
        """Pin from body edge (x1,y1) to its end (x2,y2); number above the pin, name inside the body."""
        self.line(x1, y1, x2, y2, BODY, 2)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        if num is not None:
            if y1 == y2:
                self.text(mx, my - 5, str(num), 11, "#A90000", "middle")
            else:
                self.text(mx + 6, my + 4, str(num), 11, "#A90000", "start")
        if name:
            if side == "left":
                self.text(x1 + 8, y1 + 4.5, name, 12, PIN_NAME, "start")
            elif side == "right":
                self.text(x1 - 8, y1 + 4.5, name, 12, PIN_NAME, "end")
            elif side == "top":
                self.text(x1, y1 + 18, name, 12, PIN_NAME, "middle")
            elif side == "bottom":
                self.text(x1, y1 - 9, name, 12, PIN_NAME, "middle")

    def resistor_v(self, x, y, ref, val, note=None, side="right"):
        """Vertical resistor, pins at (x,y) and (x,y+100). KiCad 'R' (IEC rectangle)."""
        self.line(x, y, x, y + 30)
        self.rect(x - 10, y + 30, 20, 40, fill="none")
        self.line(x, y + 70, x, y + 100)
        tx, an = (x + 18, "start") if side == "right" else (x - 18, "end")
        self.text(tx, y + 47, ref, 13, REF, an)
        self.text(tx, y + 63, val, 13, REF, an)
        if note:
            self.text(tx, y + 79, note, 11, REF, an, italic=True)

    def resistor_h(self, x, y, ref, val):
        """Horizontal resistor, pins at (x,y) and (x+100,y)."""
        self.line(x, y, x + 30, y)
        self.rect(x + 30, y - 10, 40, 20, fill="none")
        self.line(x + 70, y, x + 100, y)
        self.text(x + 50, y - 18, ref, 13, REF, "middle")
        self.text(x + 50, y + 30, val, 13, REF, "middle")

    def cap_v(self, x, y, ref, val, note=None):
        """Vertical capacitor, pins at (x,y) and (x,y+100)."""
        self.line(x, y, x, y + 44)
        self.line(x - 20, y + 44, x + 20, y + 44, w=2.6)
        self.line(x - 20, y + 56, x + 20, y + 56, w=2.6)
        self.line(x, y + 56, x, y + 100)
        self.text(x + 26, y + 47, ref, 13, REF)
        self.text(x + 26, y + 63, val, 13, REF)
        if note:
            self.text(x + 26, y + 79, note, 11, REF, italic=True)

    def gnd(self, x, y, label="GND"):
        self.line(x, y, x, y + 12)
        self.add(f'<polygon points="{x - 16},{y + 12} {x + 16},{y + 12} {x},{y + 28}" fill="none" stroke="{BODY}" stroke-width="2"/>')
        self.text(x, y + 44, label, 11, BODY, "middle")

    def gndpwr(self, x, y):
        self.line(x, y, x, y + 14)
        self.line(x - 18, y + 14, x + 18, y + 14, w=4)
        for dx in (-14, -4, 6):
            self.line(x + dx + 8, y + 16, x + dx, y + 26, w=1.6)
        self.text(x, y + 42, "GNDPWR", 11, BODY, "middle")

    def power(self, x, y, label):
        """Supply symbol with its pin at (x,y), pointing up."""
        self.line(x, y, x, y - 18)
        self.add(f'<polyline points="{x - 9},{y - 12} {x},{y - 24} {x + 9},{y - 12}" fill="none" stroke="{BODY}" stroke-width="2"/>')
        self.text(x, y - 32, label, 12, BODY, "middle")

    def noconnect(self, x, y):
        self.line(x - 8, y - 8, x + 8, y + 8, NOTE, 2)
        self.line(x - 8, y + 8, x + 8, y - 8, NOTE, 2)

    def glabel(self, x, y, name, direction="right"):
        """Global label attached at (x,y); the flag extends in `direction`."""
        w = 10 + 8.2 * len(name)
        h = 22
        if direction == "right":
            pts = [(x, y), (x + 11, y - h / 2), (x + w + 11, y - h / 2), (x + w + 11, y + h / 2), (x + 11, y + h / 2)]
            tx = x + 14
            anchor = "start"
        else:
            pts = [(x, y), (x - 11, y - h / 2), (x - w - 11, y - h / 2), (x - w - 11, y + h / 2), (x - 11, y + h / 2)]
            tx = x - 14
            anchor = "end"
        p = " ".join(f"{a},{b}" for a, b in pts)
        self.add(f'<polygon points="{p}" fill="none" stroke="{BODY}" stroke-width="1.6"/>')
        self.text(tx, y + 4.5, name, 12, "#000000", anchor)

    def switch_h(self, x, y, ref, val):
        """SPST switch, pins at (x,y) and (x+80,y)."""
        self.line(x, y, x + 18, y)
        self.add(f'<circle cx="{x + 22}" cy="{y}" r="4" fill="none" stroke="{BODY}" stroke-width="2"/>')
        self.add(f'<circle cx="{x + 58}" cy="{y}" r="4" fill="none" stroke="{BODY}" stroke-width="2"/>')
        self.line(x + 25, y - 3, x + 58, y - 20)
        self.line(x + 62, y, x + 80, y)
        self.text(x + 40, y - 30, ref, 13, REF, "middle")
        self.text(x + 40, y + 24, val, 12, REF, "middle")

    def motor_v(self, x, y, ref, val):
        """DC motor/pump, pins at (x,y) and (x,y+110)."""
        self.line(x, y, x, y + 25)
        self.add(f'<circle cx="{x}" cy="{y + 55}" r="30" fill="{FILL}" stroke="{BODY}" stroke-width="2"/>')
        self.text(x, y + 62, "M", 20, BODY, "middle", "bold")
        self.text(x - 20, y + 30, "+", 13, BODY, "middle")
        self.line(x, y + 85, x, y + 110)
        self.text(x + 40, y + 50, ref, 13, REF)
        self.text(x + 40, y + 66, val, 12, REF)

    def antenna(self, x, y, ref, val):
        """Antenna with its pin at (x,y), pointing up."""
        self.line(x, y, x, y - 40)
        self.add(f'<polygon points="{x - 14},{y - 64} {x + 14},{y - 64} {x},{y - 40}" fill="none" stroke="{BODY}" stroke-width="2"/>')
        self.line(x, y - 40, x, y - 64)
        self.text(x + 22, y - 54, ref, 13, REF, weight="bold")
        self.text(x + 22, y - 38, val, 12, REF)

    def ra02(self, x, y, ref, nets_left, pitch=38, rpitch=25):
        """Ai-Thinker Ra-02 (SX1278, 433 MHz) module: SPI pins on the left, supply/antenna/DIO on the right.
        nets_left: list of (pin_name, pin_number); returns dict pin_name -> left pin end."""
        w, h = 150, 40 + rpitch * 9 + 24
        self.rect(x, y, w, h)
        self.text(x, y - 26, ref, 13, REF, weight="bold")
        self.text(x, y - 10, "Ra-02 (SX1278, 433 MHz)", 12, REF)
        ends = {}
        for k, (nm, num) in enumerate(nets_left):
            yy = y + 40 + pitch * k
            self.pin(x, yy, x - 40, yy, num, nm, "left")
            ends[nm] = (x - 40, yy)
        right = [("ANT", 1), ("3.3V", 3), ("GND", 2), ("GND", 9), ("GND", 16),
                 ("DIO1", 6), ("DIO2", 7), ("DIO3", 8), ("DIO4", 10), ("DIO5", 11)]
        rp = {}
        for k, (nm, num) in enumerate(right):
            yy = y + 24 + rpitch * k
            self.pin(x + w, yy, x + w + 40, yy, num, nm, "right")
            rp.setdefault(nm, []).append((x + w + 40, yy))
        # antenna
        ax, ay = rp["ANT"][0]
        self.wire((ax, ay), (ax + 20, ay), (ax + 20, ay - 4))
        self.antenna(ax + 20, ay - 4, "AE" + ref[1:], "433 MHz")
        # 3.3 V
        vx, vy = rp["3.3V"][0]
        self.wire((vx, vy), (vx + 90, vy), (vx + 90, vy - 6))
        self.power(vx + 90, vy - 6, "+3V3")
        # grounds tied together
        gx = rp["GND"][0][0] + 30
        for (px, py) in rp["GND"]:
            self.wire((px, py), (gx, py))
        self.wire((gx, rp["GND"][0][1]), (gx, rp["GND"][-1][1] + 10))
        for (px, py) in rp["GND"][1:]:
            self.dot(gx, py)
        self.gnd(gx, rp["GND"][-1][1] + 10)
        for nm in ("DIO1", "DIO2", "DIO3", "DIO4", "DIO5"):
            self.noconnect(*rp[nm][0])
        return ends

    def box(self, x, y, w, h, ref, val, sub=None, ref_pos="top"):
        self.rect(x, y, w, h)
        if ref_pos == "top":
            self.text(x, y - 26, ref, 13, REF, weight="bold")
            self.text(x, y - 10, val, 12, REF)
        if sub:
            for i, s in enumerate(sub):
                self.text(x + w / 2, y + h + 18 + 15 * i, s, 11, REF, "middle", italic=True)

    def section(self, x, y, w, h, title):
        self.rect(x, y, w, h, c=NOTE, fill="none", sw=1.2, dash="10 6")
        self.text(x + 12, y + 24, title, 16, NOTE, weight="bold")

    # ── sheet frame + title block ───────────────────────────────────────────────
    def frame(self):
        self.rect(20, 20, W - 40, H - 40, fill="none", sw=1.4)
        self.rect(40, 40, W - 80, H - 80, fill="none", sw=1.4)
        cols, rows = 8, 6
        cw, rh = (W - 80) / cols, (H - 80) / rows
        for i in range(cols):
            cx = 40 + cw * (i + 0.5)
            for yy in (32, H - 26):
                self.text(cx, yy + 4, str(i + 1), 12, BODY, "middle")
            if i:
                self.line(40 + cw * i, 20, 40 + cw * i, 40, BODY, 1.2)
                self.line(40 + cw * i, H - 40, 40 + cw * i, H - 20, BODY, 1.2)
        for j in range(rows):
            cy = 40 + rh * (j + 0.5)
            for xx in (30, W - 30):
                self.text(xx, cy + 4, "ABCDEF"[j], 12, BODY, "middle")
            if j:
                self.line(20, 40 + rh * j, 40, 40 + rh * j, BODY, 1.2)
                self.line(W - 40, 40 + rh * j, W - 20, 40 + rh * j, BODY, 1.2)

    def title_block(self, title="HydroPin – prototype bench wiring", sheet_id="1/1", fname="hydropin_bench_wiring"):
        x0, y0, w, h = W - 40 - 620, H - 40 - 130, 620, 130
        self.rect(x0, y0, w, h, fill="none", sw=1.6)
        for yy in (y0 + 30, y0 + 70, y0 + 100):
            self.line(x0, yy, x0 + w, yy, BODY, 1.2)
        self.line(x0 + 330, y0 + 70, x0 + 330, y0 + 130, BODY, 1.2)
        self.text(x0 + 8, y0 + 20, f"Sheet: /{sheet_id.split('/')[0]}/   File: {fname}.pdf", 12, BODY)
        self.text(x0 + 8, y0 + 44, "Title:", 11, BODY)
        self.text(x0 + 60, y0 + 60, title, 20, BODY, weight="bold")
        self.text(x0 + 8, y0 + 90, "Size: A3     Date: 2026-11-23", 12, BODY)
        self.text(x0 + 338, y0 + 90, "Rev: 1", 12, BODY)
        self.text(x0 + 8, y0 + 120, "TSYP 14 · AOTN · HydroPin team (INSAT)", 12, BODY)
        self.text(x0 + 338, y0 + 120, f"Id: {sheet_id}   KiCad-style drawing", 12, BODY)

    def svg(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
                f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>' + "".join(self.parts) + "</svg>")


def draw(lora: bool = False) -> Sheet:
    """Sheet of the bench. lora=False: one ESP32 on Wi-Fi (current design); lora=True: node + Ra-02 (sheet 1 of 2)."""
    s = Sheet()
    s.frame()

    # ══ POWER ═══════════════════════════════════════════════════════════════════
    s.section(60, 60, 495, 600, "Power (three adapters, one power strip)")
    # PS1 12 V → J1 → SW1 → M1, own ground
    s.box(80, 140, 120, 90, "PS1", "AC/DC adapter 12 V 3 A", ["5.5 × 2.1 mm plug"])
    s.add(f'<path d="M200,185 L250,185" stroke="{BODY}" stroke-width="2" stroke-dasharray="6 4"/>')
    s.text(225, 177, "plug", 11, REF, "middle", italic=True)
    s.rect(250, 140, 60, 90)
    s.text(250, 114, "J1", 13, REF, weight="bold")
    s.text(250, 130, "Barrel jack", 12, REF)
    s.pin(310, 165, 340, 165, 1, "+", "right")
    s.pin(310, 205, 340, 205, 2, "−", "right")
    s.wire((340, 165), (350, 165))
    s.switch_h(350, 165, "SW1", "inline switch")
    s.wire((430, 165), (445, 165), (445, 190))
    s.motor_v(445, 190, "M1", "R365 12 V")
    s.text(445 + 40, 190 + 82, "pump", 11, REF, italic=True)
    s.wire((445, 300), (445, 320))
    s.gndpwr(445, 320)
    s.wire((340, 205), (370, 205), (370, 320))
    s.gndpwr(370, 320)
    # PS2 24 V → J2 → +24V / GND
    s.box(80, 420, 120, 90, "PS2", "AC/DC adapter 24 V 1 A")
    s.add(f'<path d="M200,465 L250,465" stroke="{BODY}" stroke-width="2" stroke-dasharray="6 4"/>')
    s.text(225, 457, "plug", 11, REF, "middle", italic=True)
    s.rect(250, 420, 60, 90)
    s.text(250, 394, "J2", 13, REF, weight="bold")
    s.text(250, 410, "Barrel jack", 12, REF)
    s.pin(310, 445, 340, 445, 1, "+", "right")
    s.pin(310, 485, 340, 485, 2, "−", "right")
    s.wire((340, 445), (400, 445), (400, 425))
    s.power(400, 425, "+24V")
    s.wire((340, 485), (440, 485), (440, 500))
    s.gnd(440, 500)
    # PS3 USB charger → U1 USB
    s.box(80, 570, 120, 60, "PS3", "USB charger 5 V")
    s.pin(200, 600, 240, 600, None)
    s.wire((240, 600), (280, 600))
    s.glabel(280, 600, "USB_5V", "right")

    # ══ SENSORS ═════════════════════════════════════════════════════════════════
    s.section(575, 60, 475, 940, "Sensors and level shifting")
    def pressure(y0, ref, name, rtop, rbot, cref, label):
        x0 = 600
        s.rect(x0, y0, 120, 100)
        s.text(x0 + 72, y0 - 46, ref, 13, REF, weight="bold")
        s.text(x0 + 72, y0 - 30, name, 12, REF)
        s.text(x0 + 60, y0 + 46, "Swagelok S", 12, BODY, "middle")
        s.text(x0 + 60, y0 + 62, "−1…1.6 bar", 11, BODY, "middle")
        s.pin(x0 + 60, y0, x0 + 60, y0 - 30, 1, "+V", "top")
        s.pin(x0 + 60, y0 + 100, x0 + 60, y0 + 130, 2, "0V", "bottom")
        s.pin(x0 + 120, y0 + 30, x0 + 150, y0 + 30, 3, "OUT", "right")
        s.text(x0 - 12, y0 + 198, "DIN 175301-803 plug, 0–10 V out", 11, REF, "start", italic=True)
        s.power(x0 + 60, y0 - 30, "+24V")
        s.gnd(x0 + 60, y0 + 130)
        yo = y0 + 30
        s.wire((x0 + 150, yo), (x0 + 160, yo))
        s.resistor_h(x0 + 160, yo, rtop[0], rtop[1])
        nx = x0 + 290
        s.wire((x0 + 260, yo), (nx, yo))
        s.dot(nx, yo)
        s.resistor_v(nx, yo, rbot[0], rbot[1], side="left")
        s.wire((nx, yo + 100), (nx, yo + 120))
        s.gnd(nx, yo + 120)
        cx = nx + 60
        s.wire((nx, yo), (cx, yo))
        s.dot(cx, yo)
        s.cap_v(cx, yo, cref, "100 nF", "optional")
        s.wire((cx, yo + 100), (cx, yo + 120))
        s.gnd(cx, yo + 120)
        s.wire((cx, yo), (cx + 20, yo))
        s.glabel(cx + 20, yo, label, "right")

    pressure(160, "PT1", "P1 – branch A", ("R1", "22 kΩ"), ("R2", "10 kΩ"), "C1", "ADC_A0")
    pressure(470, "PT2", "P2 – branch B", ("R3", "22 kΩ"), ("R4", "10 kΩ"), "C2", "ADC_A1")
    # flow sensor
    x0, y0 = 600, 790
    s.rect(x0, y0, 120, 100)
    s.text(x0 + 72, y0 - 46, "FS1", 13, REF, weight="bold")
    s.text(x0 + 72, y0 - 30, "F0 – brass Hall flow sensor G1/2", 12, REF)
    s.text(x0 + 60, y0 + 46, "Hall", 12, BODY, "middle")
    s.text(x0 + 60, y0 + 62, "f = K·Q", 11, BODY, "middle")
    s.pin(x0 + 60, y0, x0 + 60, y0 - 30, "red", "VCC", "top")
    s.pin(x0 + 60, y0 + 100, x0 + 60, y0 + 130, "black", "GND", "bottom")
    s.pin(x0 + 120, y0 + 30, x0 + 150, y0 + 30, "yellow", "PULSE", "right")
    s.power(x0 + 60, y0 - 30, "+5V")
    s.gnd(x0 + 60, y0 + 130)
    yo = y0 + 30
    s.wire((x0 + 150, yo), (x0 + 160, yo))
    s.resistor_h(x0 + 160, yo, "R5", "10 kΩ")
    nx = x0 + 290
    s.wire((x0 + 260, yo), (nx, yo))
    s.dot(nx, yo)
    s.resistor_v(nx, yo, "R6", "20 kΩ", "2 × 10 kΩ", side="left")
    s.wire((nx, yo + 100), (nx, yo + 120))
    s.gnd(nx, yo + 120)
    s.wire((nx, yo), (nx + 60, yo))
    s.glabel(nx + 60, yo, "F0_PULSE", "right")

    # ══ ACQUISITION ═════════════════════════════════════════════════════════════
    s.section(1065, 60, 555, 940, "Acquisition (ADS1115 + ESP32)")
    # U2 ADS1115 module
    ux, uy, uw, uh = 1240, 150, 180, 330
    s.rect(ux, uy, uw, uh)
    s.text(ux, uy - 26, "U2", 13, REF, weight="bold")
    s.text(ux, uy - 10, "ADS1115 module (16 bit, I²C 0x48)", 12, REF)
    left = [("A0", 200), ("A1", 250), ("A2", 300), ("A3", 350)]
    right = [("VDD", 200), ("GND", 250), ("SCL", 300), ("SDA", 350), ("ADDR", 400), ("ALRT", 450)]
    for k, (nm, yy) in enumerate(left):
        s.pin(ux, yy, ux - 40, yy, 7 + k, nm, "left")
    for k, (nm, yy) in enumerate(right):
        s.pin(ux + uw, yy, ux + uw + 40, yy, k + 1, nm, "right")
    s.glabel(ux - 40, 200, "ADC_A0", "left")
    s.glabel(ux - 40, 250, "ADC_A1", "left")
    s.noconnect(ux - 40, 300)
    s.noconnect(ux - 40, 350)
    s.text(ux - 130, 330, "free: 3rd sensor", 11, NOTE, italic=True)
    s.wire((ux + uw + 40, 200), (ux + uw + 80, 200), (ux + uw + 80, 180))
    s.power(ux + uw + 80, 180, "+3V3")
    s.wire((ux + uw + 40, 250), (ux + uw + 120, 250), (ux + uw + 120, 262))
    s.gnd(ux + uw + 120, 262)
    s.glabel(ux + uw + 40, 300, "SCL", "right")
    s.glabel(ux + uw + 40, 350, "SDA", "right")
    s.wire((ux + uw + 40, 400), (ux + uw + 120, 400), (ux + uw + 120, 410))
    s.gnd(ux + uw + 120, 410)
    s.text(ux + uw + 132, 398, "addr 0x48", 11, NOTE, italic=True)
    s.noconnect(ux + uw + 40, 450)
    if lora:
            # U1 ESP32 (sensor node)
        ex, ey, ew, eh = 1240, 560, 180, 400
        s.rect(ex, ey, ew, eh)
        s.text(ex, ey - 26, "U1", 13, REF, weight="bold")
        s.text(ex, ey - 10, "ESP32-DevKitC – sensor node", 12, REF)
        lp = [("3V3", 600), ("GND", 650), ("GPIO21", 720), ("GPIO22", 770), ("GPIO27", 830)]
        rp = [("5V/VIN", 600), ("GND", 640), ("USB", 680), ("GPIO5", 730), ("GPIO18", 770),
              ("GPIO19", 810), ("GPIO23", 850), ("GPIO14", 890), ("GPIO26", 930)]
        for nm, yy in lp:
            s.pin(ex, yy, ex - 40, yy, None, nm, "left")
        for nm, yy in rp:
            s.pin(ex + ew, yy, ex + ew + 40, yy, None, nm, "right")
        s.wire((ex - 40, 600), (ex - 80, 600), (ex - 80, 580))
        s.power(ex - 80, 580, "+3V3")
        s.wire((ex - 40, 650), (ex - 120, 650), (ex - 120, 664))
        s.gnd(ex - 120, 664)
        s.glabel(ex - 40, 720, "SDA", "left")
        s.glabel(ex - 40, 770, "SCL", "left")
        s.glabel(ex - 40, 830, "F0_PULSE", "left")
        s.wire((ex + ew + 40, 600), (ex + ew + 80, 600), (ex + ew + 80, 580))
        s.power(ex + ew + 80, 580, "+5V")
        s.wire((ex + ew + 40, 640), (ex + ew + 150, 640), (ex + ew + 150, 646))
        s.gnd(ex + ew + 150, 646)
        s.glabel(ex + ew + 40, 680, "USB_5V", "right")
        for nm, lab in (("GPIO5", "LORA_NSS"), ("GPIO18", "LORA_SCK"), ("GPIO19", "LORA_MISO"),
                        ("GPIO23", "LORA_MOSI"), ("GPIO14", "LORA_RST"), ("GPIO26", "LORA_DIO0")):
            yy = dict(rp)[nm]
            s.glabel(ex + ew + 40, yy, lab, "right")
        s.text(ex + 10, ey + eh - 40, "LoRa: VSPI → U3", 12, BODY)
        s.text(ex + 10, ey + eh - 22, "gateway: sheet 2", 11, BODY)

        # ══ LORA RADIO OF THE NODE ══════════════════════════════════════════════════
        s.section(60, 690, 495, 440, "LoRa radio (node)")
        ends = s.ra02(220, 790, "U3", [("NSS", 15), ("SCK", 12), ("MISO", 13), ("MOSI", 14), ("RESET", 4), ("DIO0", 5)],
                      pitch=34, rpitch=22)
        for nm, lab in (("NSS", "LORA_NSS"), ("SCK", "LORA_SCK"), ("MISO", "LORA_MISO"), ("MOSI", "LORA_MOSI"),
                        ("RESET", "LORA_RST"), ("DIO0", "LORA_DIO0")):
            s.glabel(*ends[nm], lab, "left")

        s.title_block("HydroPin – bench sensor node", "1/2")
        return s
    # U1 ESP32: reads everything and sends it over its built-in Wi-Fi (current design, 23 Nov)
    ex, ey, ew, eh = 1240, 560, 180, 310
    s.rect(ex, ey, ew, eh)
    s.text(ex, ey - 26, "U1", 13, REF, weight="bold")
    s.text(ex, ey - 10, "ESP32-DevKitC (ESP32-WROOM-32)", 12, REF)
    lp = [("3V3", 620), ("GND", 670), ("GPIO21", 730), ("GPIO22", 780), ("GPIO27", 830)]
    rp = [("5V/VIN", 620), ("GND", 670), ("USB", 780)]
    for nm, yy in lp:
        s.pin(ex, yy, ex - 40, yy, None, nm, "left")
    for nm, yy in rp:
        s.pin(ex + ew, yy, ex + ew + 40, yy, None, nm, "right")
    s.wire((ex - 40, 620), (ex - 80, 620), (ex - 80, 600))
    s.power(ex - 80, 600, "+3V3")
    s.wire((ex - 40, 670), (ex - 120, 670), (ex - 120, 684))
    s.gnd(ex - 120, 684)
    s.glabel(ex - 40, 730, "SDA", "left")
    s.glabel(ex - 40, 780, "SCL", "left")
    s.glabel(ex - 40, 830, "F0_PULSE", "left")
    s.wire((ex + ew + 40, 620), (ex + ew + 80, 620), (ex + ew + 80, 600))
    s.power(ex + ew + 80, 600, "+5V")
    s.wire((ex + ew + 40, 670), (ex + ew + 120, 670), (ex + ew + 120, 684))
    s.gnd(ex + ew + 120, 684)
    s.glabel(ex + ew + 40, 780, "USB_5V", "right")
    s.text(ex + ew / 2, ey + 24, "Wi-Fi (built in) → laptop", 12, BODY, "middle")
    s.text(ex + ew / 2, ey + 40, "MQTT, 1-s means", 11, BODY, "middle")
    # laptop
    s.rect(1300, 930, 200, 60, c=NOTE, fill="none", sw=1.4, rx=6)
    s.text(1400, 956, "Laptop: MQTT broker", 13, NOTE, "middle", weight="bold")
    s.text(1400, 976, "+ dashboard", 12, NOTE, "middle")
    s.add(f'<path d="M1330,{ey + eh} L1330,930" fill="none" stroke="{NOTE}" stroke-width="1.6" stroke-dasharray="7 5"/>')
    s.text(1338, 912, "Wi-Fi", 11, NOTE, italic=True)

    # ══ NOTES ═══════════════════════════════════════════════════════════════════
    notes = [
        "Notes",
        "1. GND joins: PS2 −, PT1/PT2 pin 2, U2 GND, U1 GND, FS1 black.",
        "2. GNDPWR (pump) is NOT joined to GND: keeps motor noise away.",
        "3. Never connect +24V to R1–R4 or to U2: 24 V → 7.5 V on the ADS1115.",
        "4. R5/R6: 5 V pulse → 3.3 V (the 22 k / 10 k of the list gives only 1.6 V).",
        "5. If PT2 is the 4–20 mA version: pin 1 to +24V, pin 2 to 150 Ω",
        "    to GND, ADC_A1 at pin 2; leave out R3/R4.",
        "6. Firmware: V_sensor = V_ADC × 3.2; p [bar] = −1 + 0.26 × V_sensor.",
        "7. PT pin numbers: usual DIN 175301-803 layout, check the datasheet.",
        "8. One ESP32 only: it reads P1, P2, F0 and publishes over Wi-Fi.",
        "9. U1: wire by GPIO name, header pin numbers differ between boards.",
    ]
    nx0, ny0 = 60, 690
    s.rect(nx0, ny0, 495, 370, c=NOTE, fill="none", sw=1.2, dash="10 6")
    for i, ln in enumerate(notes):
        if i == 0:
            s.text(nx0 + 12, ny0 + 26, ln, 16, NOTE, weight="bold")
        else:
            s.text(nx0 + 12, ny0 + 30 + 31 * i, ln, 11.5, NOTE)
    s.title_block("HydroPin – prototype bench wiring", "1/1")
    return s


def draw_gateway() -> Sheet:
    """Sheet 2: LoRa receiver + Wi-Fi to the PC, and the notes for both sheets."""
    s = Sheet()
    s.frame()
    s.section(60, 60, 1240, 560, "LoRa gateway (second ESP32): receives the node, forwards to the PC over Wi-Fi")
    # power
    s.box(90, 150, 120, 60, "PS4", "USB port of the PC (or a charger)")
    s.pin(210, 180, 250, 180, None)
    s.wire((250, 180), (290, 180))
    s.text(270, 172, "USB", 11, REF, "middle", italic=True)
    # U4 ESP32
    ex, ey, ew, eh = 520, 140, 180, 400
    s.rect(ex, ey, ew, eh)
    s.text(ex, ey - 26, "U4", 13, REF, weight="bold")
    s.text(ex, ey - 10, "ESP32-DevKitC – gateway", 12, REF)
    lp = [("USB", 180), ("3V3", 260), ("GND", 320)]
    for nm, yy in lp:
        s.pin(ex, yy, ex - 40, yy, None, nm, "left")
    s.wire((290, 180), (ex - 40, 180))
    s.wire((ex - 40, 260), (ex - 80, 260), (ex - 80, 244))
    s.power(ex - 80, 244, "+3V3")
    s.wire((ex - 40, 320), (ex - 120, 320), (ex - 120, 334))
    s.gnd(ex - 120, 334)
    rp = [("GPIO5", 200), ("GPIO18", 240), ("GPIO19", 280), ("GPIO23", 320), ("GPIO14", 360), ("GPIO26", 400)]
    for nm, yy in rp:
        s.pin(ex + ew, yy, ex + ew + 40, yy, None, nm, "right")
    s.text(ex + ew / 2, ey + eh - 40, "Wi-Fi (built in)", 12, BODY, "middle")
    s.text(ex + ew / 2, ey + eh - 24, "MQTT → PC dashboard", 11, BODY, "middle")
    # U5 Ra-02, wired straight to U4
    ux = 900
    ends = s.ra02(ux, 160, "U5", [("NSS", 15), ("SCK", 12), ("MISO", 13), ("MOSI", 14), ("RESET", 4), ("DIO0", 5)],
                  pitch=40)
    order = ["NSS", "SCK", "MISO", "MOSI", "RESET", "DIO0"]
    for k, (nm, yy) in enumerate(rp):
        x2, y2 = ends[order[k]]
        s.wire((ex + ew + 40, yy), (x2, y2))
    # PC
    s.rect(160, 400, 200, 110, c=NOTE, fill="none", sw=1.4, rx=6)
    s.text(260, 440, "PC / laptop", 14, NOTE, "middle", weight="bold")
    s.text(260, 462, "MQTT broker + dashboard", 12, NOTE, "middle")
    s.text(260, 480, "(demo viewer format)", 11, NOTE, "middle", italic=True)
    s.add(f'<path d="M520,470 C470,470 420,470 362,470" fill="none" stroke="{NOTE}" stroke-width="1.6" stroke-dasharray="7 5"/>')
    s.text(440, 460, "Wi-Fi", 12, NOTE, "middle", italic=True)

    notes = [
        "Notes (both sheets)",
        "1. GND joins: PS2 −, PT1/PT2 pin 2, U2 GND, U1 GND, FS1 black, U3 GND.",
        "2. GNDPWR (pump) is NOT joined to GND: keeps motor noise away.",
        "3. Never connect +24V to R1–R4 or to U2: 24 V would put 7.5 V on the ADS1115.",
        "4. R5/R6: 5 V pulse → 3.3 V (the 22 k / 10 k of the 18 Nov list gives only 1.6 V).",
        "5. If PT2 is the 4–20 mA version: pin 1 to +24V, pin 2 to 150 Ω to GND, ADC_A1 at pin 2; leave out R3/R4.",
        "6. Ra-02 runs on 3.3 V only (never 5 V). Add 10 µF + 100 nF across 3.3V–GND close to each module.",
        "7. Always connect the 433 MHz antenna before transmitting: without it the SX1278 can be damaged.",
        "8. On the bench the radios are ~1 m apart: set TX power low (2–10 dBm) so the receiver is not saturated.",
        "9. Both radios must use the same frequency, bandwidth, spreading factor and sync word (e.g. 433 MHz, 125 kHz, SF7).",
        "10. GPIO5 is a boot strapping pin; the Ra-02 NSS line idles high, which is what the ESP32 needs at boot.",
        "11. Firmware: V_sensor = V_ADC × 3.2; p [bar] = −1 + 0.26 × V_sensor. Node sends P1, P2, F0, seq every 1 s.",
        "12. Pin numbers of PT1/PT2: usual DIN 175301-803 layout; Ra-02 pins: Ai-Thinker datasheet. Check before wiring.",
    ]
    nx0, ny0 = 60, 650
    s.rect(nx0, ny0, 940, 470, c=NOTE, fill="none", sw=1.2, dash="10 6")
    for i, ln in enumerate(notes):
        if i == 0:
            s.text(nx0 + 12, ny0 + 28, ln, 16, NOTE, weight="bold")
        else:
            s.text(nx0 + 12, ny0 + 32 + 33 * i, ln, 12.5, NOTE)
    s.title_block("HydroPin – LoRa gateway + notes", "2/2")
    return s


LORA = False        # 23 Nov: back to one ESP32 with its built-in Wi-Fi (the LoRa variant stays available)


def main():
    import io

    from pypdf import PdfWriter
    out = Path(__file__).resolve().parents[1] / "results" / "wiring"
    out.mkdir(parents=True, exist_ok=True)
    base = out / "hydropin_bench_wiring"
    writer = PdfWriter()
    sheets = (draw(lora=True), draw_gateway()) if LORA else (draw(),)
    for k, sheet in enumerate(sheets, start=1):
        svg = sheet.svg()
        name = base.name if len(sheets) == 1 else f"{base.name}_sheet{k}"
        (out / f"{name}.svg").write_text(svg, encoding="utf-8")
        cairosvg.svg2png(bytestring=svg.encode(), write_to=str(out / f"{name}.png"), output_width=3360)
        writer.append(io.BytesIO(cairosvg.svg2pdf(bytestring=svg.encode())))
    with open(base.with_suffix(".pdf"), "wb") as fh:
        writer.write(fh)
    print(base)


if __name__ == "__main__":
    main()
