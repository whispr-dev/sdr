from reportlab.lib.pagesizes import A4
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, PageBreak,
                                Table, TableStyle)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.graphics.shapes import Drawing, Line, String, Circle, Rect, Polygon
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

# Register fallback font
pdfmetrics.registerFont(UnicodeCIDFont('HeiseiMin-W3'))

output_path = "/mnt/data/rf_sdr_primer.pdf"

doc = SimpleDocTemplate(output_path, pagesize=A4,
                        rightMargin=40, leftMargin=40,
                        topMargin=40, bottomMargin=40)

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleStyle', fontName="Courier", fontSize=22, leading=26, alignment=1, spaceAfter=20))
styles.add(ParagraphStyle(name='MyHeading1', fontName="Courier", fontSize=16, leading=20, spaceBefore=12, spaceAfter=6))
styles.add(ParagraphStyle(name='MyHeading2', fontName="Courier", fontSize=13, leading=16, spaceBefore=10, spaceAfter=4))
styles.add(ParagraphStyle(name='NormalType', fontName="Courier", fontSize=10, leading=14))

story = []

# Cover
story.append(Spacer(1, 100))
story.append(Paragraph("RF & SDR Primer (UK Edition)", styles['TitleStyle']))
story.append(Spacer(1, 20))
story.append(Paragraph("A practical illustrated guide to RF basics, SDR hardware, UK law, antennas, DSP, and more.", styles['NormalType']))
story.append(Spacer(1, 200))
story.append(Paragraph("Generated for fren", styles['NormalType']))
story.append(PageBreak())

# TOC
story.append(Paragraph("Table of Contents", styles['MyHeading1']))
toc_items = [
    "0) The 10-minute Mental Model",
    "1) SDR Hardware Map",
    "2) Antennas You’ll Actually Build",
    "3) DSP You’ll Touch",
    "4) UK Law and Licensing",
    "5) Gotchas and Fixes",
    "6) Quick RF Math Cheat-Sheet",
    "7) Spectrum Placemat Diagram",
    "8) Diagrams (IQ & Antennas)",
    "9) References & Links",
]
for item in toc_items:
    story.append(Paragraph(item, styles['NormalType']))
story.append(PageBreak())

# Fundamentals
story.append(Paragraph("0) The 10-minute Mental Model", styles['MyHeading1']))
points = [
    "Frequency ↔ Wavelength: λ = c/f. Example: 2.4 GHz → ~12.5 cm.",
    "Bandwidth (B): span a signal occupies. Sampling ≥ 2×B (Nyquist).",
    "dB/dBm: +3 dB ≈ ×2 power, +10 dB = ×10.",
    "Modulation: AM/FM/PM (analog), FSK/PSK/QAM/OFDM (digital).",
    "IQ samples: every modulation maps into movements on the I/Q plane."
]
for p in points:
    story.append(Paragraph("• " + p, styles['NormalType']))

# RX Chain Diagram
d = Drawing(400, 80)
x = 10
blocks = ["Antenna", "LNA", "Mixer+LO", "ADC", "DSP"]
for b in blocks:
    d.add(Rect(x, 30, 60, 20, strokeColor=colors.black, fillColor=colors.lightgrey))
    d.add(String(x+5, 35, b, fontName="Courier", fontSize=8))
    if b != "DSP":
        d.add(Line(x+60, 40, x+80, 40))
    x += 80
story.append(d)

# Hardware
story.append(Paragraph("1) SDR Hardware Map", styles['MyHeading1']))
hw = [
    "RTL-SDR: cheap, RX only (500 kHz–1.7 GHz).",
    "Airspy: better dynamic range.",
    "HackRF One: TX/RX, 1–6 GHz, but 8-bit only.",
    "LimeSDR Mini v2: TX/RX 10 MHz–3.5 GHz, 12-bit.",
    "USRP: lab grade, flexible, expensive."
]
for h in hw:
    story.append(Paragraph("• " + h, styles['NormalType']))

# Antennas
story.append(Paragraph("2) Antennas You’ll Actually Build", styles['MyHeading1']))
ants = [
    "λ/2 dipole: two elements, each 0.234·(c/f MHz).",
    "Quarter-wave ground-plane: one vertical, four sloping radials.",
    "Discone: wideband, great for scanning.",
    "Yagi: directional, gain for VHF/UHF.",
    "Patch: flat, 2.4 GHz Wi-Fi."
]
for a in ants:
    story.append(Paragraph("• " + a, styles['NormalType']))

# DSP
story.append(Paragraph("3) DSP You’ll Touch", styles['MyHeading1']))
dsps = [
    "Filters: low-pass, band-pass.",
    "AM demod: magnitude of IQ.",
    "FM demod: differentiate phase.",
    "FSK demod: frequency discriminator.",
    "PSK/QAM: Costas loop, constellation."
]
for dsp in dsps:
    story.append(Paragraph("• " + dsp, styles['NormalType']))

# UK Law
story.append(Paragraph("4) UK Law and Licensing", styles['MyHeading1']))
data = [
    ["Area", "What’s legal?", "What’s not"],
    ["Receive-only", "Broadcast radio/TV, your own amateur signals", "Intercepting private/emergency/business comms"],
    ["Licence-exempt", "433 MHz (10 mW ERP), 868 MHz LoRa (25 mW EIRP), Wi-Fi/BLE (100 mW EIRP)", "Over-power, external antennas on PMR446"],
    ["Amateur Radio", "Operate within licence terms (Foundation/Intermediate/Full), keep EMF records", "TX without licence, exceed band/power limits"]
]
t = Table(data, colWidths=[90, 210, 210])
t.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                       ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                       ('FONTNAME', (0,0), (-1,-1), 'Courier'),
                       ('FONTSIZE', (0,0), (-1,-1), 8),
                       ('VALIGN', (0,0), (-1,-1), 'TOP')]))
story.append(t)

# Gotchas
story.append(Paragraph("5) Gotchas and Fixes", styles['MyHeading1']))
gotchas = [
    "Overload: too much gain, adds intermod.",
    "Clock drift: RTL dongles need PPM correction.",
    "Aliasing: respect Nyquist, decimate properly.",
    "Ground loops: isolate power/audio.",
    "Antennas > DSP: better antenna beats software tricks."
]
for g in gotchas:
    story.append(Paragraph("• " + g, styles['NormalType']))

# Cheat-sheet
story.append(Paragraph("6) Quick RF Math Cheat-Sheet", styles['MyHeading1']))
formulas = [
    "FSPL(dB) = 32.44 + 20·log10(d_km) + 20·log10(f_MHz)",
    "Thermal noise (dBm) = -174 + 10·log10(B_Hz) + NF_dB",
    "EIRP(dBm) = TX(dBm) + Gain(dBi) – Loss(dB)",
    "ERP(dBW) = TX(dBW) + Gain(dBd) – Loss(dB)"
]
for f in formulas:
    story.append(Paragraph("• " + f, styles['NormalType']))

# Spectrum Placemat
story.append(Paragraph("7) Spectrum Placemat Diagram", styles['MyHeading1']))
d2 = Drawing(400, 80)
bands = [("HF 3–30 MHz", colors.lightblue),
         ("VHF 30–300 MHz", colors.lightgreen),
         ("UHF 300–3000 MHz", colors.orange),
         ("SHF 3–30 GHz", colors.pink)]
x = 10
w = 85
for name, col in bands:
    d2.add(Rect(x, 30, w, 20, strokeColor=colors.black, fillColor=col))
    d2.add(String(x+5, 35, name, fontName="Courier", fontSize=8))
    x += w + 5
story.append(d2)

# IQ diagram
story.append(Paragraph("8) Diagrams: IQ & Antennas", styles['MyHeading1']))
iq = Drawing(200, 200)
iq.add(Line(100, 10, 100, 190)) # Q axis
iq.add(Line(10, 100, 190, 100)) # I axis
iq.add(Circle(100, 100, 80, strokeColor=colors.black))
# constellation points
points = [(180,100),(20,100),(100,180),(100,20)]
for px,py in points:
    iq.add(Circle(px,py,5, fillColor=colors.red))
story.append(iq)

# Antenna sketches
ants_d = Drawing(400,120)
# dipole
ants_d.add(Line(50,60,50,100))
ants_d.add(Line(50,60,50,20))
ants_d.add(String(40,10,"Dipole", fontName="Courier", fontSize=8))
# ground-plane
ants_d.add(Line(150,60,150,100))
for dx in [-30,-15,15,30]:
    ants_d.add(Line(150,60,150+dx,20))
ants_d.add(String(140,10,"GP", fontName="Courier", fontSize=8))
# discone
ants_d.add(Line(250,60,250,100))
ants_d.add(Line(230,60,270,60))
ants_d.add(Line(230,60,250,20))
ants_d.add(Line(270,60,250,20))
ants_d.add(String(230,10,"Discone", fontName="Courier", fontSize=8))
# yagi (simplified)
ants_d.add(Line(350,20,350,100)) # boom
ants_d.add(Line(330,80,370,80)) # reflector
ants_d.add(Line(340,60,360,60)) # driven
ants_d.add(Line(345,40,355,40)) # director
ants_d.add(String(340,10,"Yagi", fontName="Courier", fontSize=8))
story.append(ants_d)

# References
story.append(Paragraph("9) References & Links", styles['MyHeading1']))
refs = [
    "Ofcom IR2030 Licence-exempt SRD tables",
    "UK Amateur Radio Licence Terms & Conditions",
    "RSGB (Radio Society of Great Britain)",
    "rtl-sdr.com tutorials",
    "GNU Radio, GQRX, SDR# software"
]
for r in refs:
    story.append(Paragraph("• " + r, styles['NormalType']))

doc.build(story)
output_path = "/home/user/D:_/code/rf_stuff/rf_sdr_primer.pdf"