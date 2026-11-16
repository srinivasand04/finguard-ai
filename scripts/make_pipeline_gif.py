"""Render the FinGuard AI pipeline as an animated GIF (1200x675, LinkedIn 16:9).

    cd backend
    .venv/Scripts/python ../scripts/make_pipeline_gif.py      # -> docs/assets/finguard_pipeline.gif

A "data packet" travels through the 12 stages of the four phases; each stage lights up
with the real result measured in this project.
"""
from __future__ import annotations

from pathlib import Path

from matplotlib import font_manager as fm
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 675
BG, CARD, CARD_LINE, MUTED, TEXT = "#0b1220", "#172033", "#2a3650", "#7c8aa5", "#e8edf6"
PHASES = [("PHASE 1 · DETECT", "#3b82f6"), ("PHASE 2 · UNDERSTAND", "#14b8a6"),
          ("PHASE 3 · INVESTIGATE", "#a855f7"), ("PHASE 4 · GOVERN", "#f59e0b")]
STAGES = [  # (phase, title, subtitle, result caption)
    (0, "Synthetic bank data", "AMLSim format · 8 typologies", "229k transactions, 1,500 customers, 8 laundering typologies - synthetic only"),
    (0, "Validate & ingest", "PostgreSQL · COPY · audit", "2,712 bad rows rejected with a reason each - nothing dropped silently"),
    (0, "ML detection", "XGBoost + Isolation Forest", "28 point-in-time features, time-based split, an explanation for every score"),
    (0, "Risk & alerts", "explainable indicators", "Customer risk from transparent indicators + 7 alert types"),
    (1, "Graph intelligence", "cycles · chains · networks", "Graph context lifts laundering-customer recall from 17% to 83%"),
    (1, "Compliance RAG", "Qdrant · BM25 · reranker", "Hybrid search + reranking finds the right policy passage first 87% of the time"),
    (2, "9 MCP tools", "validated · permissioned · audited", "Agents and external AI clients share one audited tool layer"),
    (2, "8 LangGraph agents", "supervisor → specialists", "Retries, conditional routing, case memory, schema-checked LLM narrative"),
    (2, "Evidence & report", "E1…En → source rows", "Every finding cites evidence - 10-section report (e.g. score 95/100)"),
    (3, "Human approval", "four-eyes · overrides tracked", "AI recommends, a manager decides - never on a case they submitted"),
    (3, "Security & monitoring", "JWT · RBAC · Prometheus", "6 roles, full audit trail, Grafana dashboards, Langfuse traces"),
    (3, "CI/CD & Docker", "73 tests · image builds", "Every push: offline tests, frontend build and Docker images"),
]

COL_W, BOX_H, GAP_X, GAP_Y, TOP = 262, 78, 28, 22, 128
LEFT = (W - (4 * COL_W + 3 * GAP_X)) // 2


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = fm.findfont(fm.FontProperties(family="DejaVu Sans", weight="bold" if bold else "normal"))
    return ImageFont.truetype(path, size)


F_TITLE, F_SUB, F_BOX, F_BOXSUB = font(30, True), font(15), font(17, True), font(13)
F_PHASE, F_CAP, F_NUM = font(13, True), font(19), font(15, True)


def layout() -> list[tuple[int, int, int, int]]:
    boxes, row = [], {0: 0, 1: 0, 2: 0, 3: 0}
    for phase, *_ in STAGES:
        x = LEFT + phase * (COL_W + GAP_X)
        y = TOP + row[phase] * (BOX_H + GAP_Y)
        row[phase] += 1
        boxes.append((x, y, x + COL_W, y + BOX_H))
    return boxes


BOXES = layout()


def path_between(i: int) -> list[tuple[float, float]]:
    """Connector from stage i-1 to stage i: straight down inside a column, elbow between columns."""
    a, b = BOXES[i - 1], BOXES[i]
    if STAGES[i][0] == STAGES[i - 1][0]:
        cx = (a[0] + a[2]) / 2
        return [(cx, a[3]), (cx, b[1])]
    mx = (a[2] + b[0]) / 2
    ay, by = (a[1] + a[3]) / 2, (b[1] + b[3]) / 2
    return [(a[2], ay), (mx, ay), (mx, by), (b[0], by)]


def point_on(path, t: float):
    segs = list(zip(path[:-1], path[1:]))
    lens = [abs(x2 - x1) + abs(y2 - y1) for (x1, y1), (x2, y2) in segs]
    d = t * sum(lens)
    for ((x1, y1), (x2, y2)), L in zip(segs, lens):
        if d <= L or L == 0:
            f = 0 if L == 0 else d / L
            return x1 + (x2 - x1) * f, y1 + (y2 - y1) * f
        d -= L
    return path[-1]


def blend(hex_a: str, hex_b: str, f: float) -> str:
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * f):02x}" for x, y in zip(a, b))


def frame(active: int, done: int, packet=None, travel_edge: int | None = None, final: bool = False) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((LEFT, 26), "FinGuard AI", font=F_TITLE, fill=TEXT)
    d.text((LEFT + 205, 38), "financial-crime detection → investigation → human decision", font=F_SUB, fill=MUTED)
    for p, (label, col) in enumerate(PHASES):
        x = LEFT + p * (COL_W + GAP_X)
        lit = any(STAGES[k][0] == p for k in range(done + 1))
        d.text((x, 98), label, font=F_PHASE, fill=col if lit else MUTED)
        d.line([(x, 118), (x + COL_W, 118)], fill=col if lit else CARD_LINE, width=2)
    # connectors
    for i in range(1, len(STAGES)):
        travelled = i <= done or (travel_edge is not None and i == travel_edge)
        col = PHASES[STAGES[i][0]][1] if travelled else CARD_LINE
        d.line(path_between(i), fill=blend(BG, col, 0.85 if travelled else 1), width=3 if travelled else 2, joint="curve")
    # boxes
    for i, ((phase, title, sub, _), (x1, y1, x2, y2)) in enumerate(zip(STAGES, BOXES)):
        col = PHASES[phase][1]
        if i == active and not final:
            fill, line, tc, sc = col, blend(col, "#ffffff", 0.35), "#ffffff", blend(col, "#ffffff", 0.8)
        elif i <= done:
            fill, line, tc, sc = blend(BG, col, 0.22), col, TEXT, blend(MUTED, "#ffffff", 0.3)
        else:
            fill, line, tc, sc = CARD, CARD_LINE, MUTED, blend(MUTED, BG, 0.3)
        d.rounded_rectangle([x1, y1, x2, y2], radius=10, fill=fill, outline=line, width=2)
        f_title = F_BOX if d.textlength(title, font=F_BOX) <= COL_W - 58 else font(15, True)   # keep clear of the tick
        d.text((x1 + 16, y1 + 15 + (F_BOX.size - f_title.size) // 2), title, font=f_title, fill=tc)
        d.text((x1 + 16, y1 + 44), sub, font=F_BOXSUB, fill=sc)
        if i < done or (final and i <= done):
            d.ellipse([x2 - 30, y1 + 12, x2 - 12, y1 + 30], fill=col)
            d.line([(x2 - 25, y1 + 21), (x2 - 22, y1 + 25), (x2 - 16, y1 + 16)], fill=BG, width=3)
    if packet:
        px, py = packet
        d.ellipse([px - 9, py - 9, px + 9, py + 9], fill="#ffffff")
        d.ellipse([px - 5, py - 5, px + 5, py + 5], fill=PHASES[STAGES[travel_edge][0]][1])
    # caption panel
    cy = 548
    d.rounded_rectangle([LEFT, cy, W - LEFT, cy + 92], radius=12, fill=CARD, outline=CARD_LINE, width=1)
    if final:
        d.text((LEFT + 24, cy + 18), "4 phases · 10 types of intelligent system · 73 automated tests",
               font=font(22, True), fill=TEXT)
        d.text((LEFT + 24, cy + 54), "ML · anomaly detection · rules · explainable AI · graph analytics · RAG · "
               "multi-agent · MCP tools · human-in-the-loop · MLOps", font=F_BOXSUB, fill=MUTED)
    else:
        phase, title, _, cap = STAGES[active]
        col = PHASES[phase][1]
        d.ellipse([LEFT + 22, cy + 30, LEFT + 54, cy + 62], fill=col)
        num = str(active + 1)
        tw = d.textlength(num, font=F_NUM)
        d.text((LEFT + 38 - tw / 2, cy + 37), num, font=F_NUM, fill="#ffffff")
        d.text((LEFT + 72, cy + 18), title.upper(), font=F_PHASE, fill=col)
        d.text((LEFT + 72, cy + 42), cap, font=F_CAP, fill=TEXT)
    d.text((W - LEFT - 300, H - 24), "github.com/srinivasand04/finguard-ai", font=F_BOXSUB, fill=MUTED)
    return im


def build(out: Path) -> None:
    frames, durations = [], []
    for i in range(len(STAGES)):
        if i > 0:
            path = path_between(i)
            for t in [k / 7 for k in range(8)]:
                frames.append(frame(active=i - 1, done=i - 1, packet=point_on(path, t), travel_edge=i))
                durations.append(45)
        frames.append(frame(active=i, done=i))
        durations.append(1600)          # hold each stage long enough to read its result
    frames.append(frame(active=len(STAGES) - 1, done=len(STAGES) - 1, final=True))
    durations.append(4500)
    pal = [f.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    out.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True, disposal=1)
    frames[-1].save(out.with_suffix(".png"))   # static version (README fallback / resume)
    print(f"{out} - {len(frames)} frames, {out.stat().st_size / 1e6:.2f} MB, {sum(durations) / 1000:.1f}s per loop")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1] / "docs" / "assets" / "finguard_pipeline.gif")
