

from __future__ import annotations

import os
import random
import threading
from dataclasses import replace

from nicegui import ui

from maze.agent import TrainConfig, TrainResult, greedy_policy, greedy_rollout, train
from maze.draw import render_svg
from maze.generate import MAX_SIDE, MIN_SIDE, generate_maze
from maze.model import Maze, is_reachable, validate_ends
from maze.reward import PRESETS, RewardError, RewardFunction, preview
from maze.store import MAZES_DIR, dumps, list_stems, load, save, safe_stem

ui.button.default_props("no-caps")
ui.input.default_props("outlined dense")
ui.number.default_props("outlined dense")
ui.select.default_props("outlined dense")
ui.textarea.default_props("outlined dense")

CUSTOM = "Personalizada"
PRESET_OPTIONS = [*PRESETS.keys(), CUSTOM]


def _whole(value: object, fallback: int) -> int:
    if value is None or value == "":
        return fallback
    return int(round(float(value)))


def _chart_options() -> dict:
    label = {"color": "#cbd5e1"}
    return {
        "backgroundColor": "transparent",
        "animation": False,
        "grid": {"left": 52, "right": 16, "top": 28, "bottom": 36},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category",
            "name": "episodio",
            "data": [],
            "axisLabel": label,
            "nameTextStyle": label,
            "axisLine": {"lineStyle": {"color": "#334155"}},
        },
        "yAxis": {
            "type": "value",
            "name": "retorno",
            "axisLabel": label,
            "nameTextStyle": label,
            "splitLine": {"lineStyle": {"color": "#1f2937"}},
        },
        "series": [
            {
                "type": "line",
                "name": "retorno",
                "data": [],
                "showSymbol": False,
                "lineStyle": {"color": "#38bdf8", "width": 2},
            }
        ],
    }


def _buckets(values: list[float], limit: int = 240) -> tuple[list[int], list[float]]:
    count = len(values)
    if count == 0:
        return [], []
    if count <= limit:
        return list(range(1, count + 1)), values
    width = count / limit
    xs: list[int] = []
    ys: list[float] = []
    start = 0.0
    while int(start) < count:
        end = min(count, int(start + width))
        if end <= int(start):
            end = int(start) + 1
        chunk = values[int(start) : end]
        ys.append(round(sum(chunk) / len(chunk), 4))
        xs.append(end)
        start = end
    return xs, ys


def _opening_maze() -> tuple[Maze, str]:
    demo = MAZES_DIR / "demo.yaml"
    if demo.exists():
        return load(demo)
    return generate_maze(8, 8, seed=7, name="demo"), PRESETS["Coste por paso"]


@ui.page("/")
def index() -> None:
    ui.colors(primary="#38bdf8", secondary="#94a3b8", accent="#fbbf24", positive="#4ade80", negative="#f87171")
    ui.add_head_html(
        """
        <style>
          .maze-layout {
            display: grid;
            gap: 1rem;
            align-items: start;
            grid-template-columns: minmax(0, 1fr);
          }
          @media (min-width: 980px) {
            .maze-layout { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
            .maze-layout .board,
            .maze-layout .returns { grid-column: 1 / -1; }
          }
          .maze-svg svg {
            display: block;
            width: min(100%, 640px);
            height: auto;
            margin: 0 auto;
          }
        </style>
        """
    )
    maze0, reward0 = _opening_maze()
    preset0 = next((name for name, expr in PRESETS.items() if expr == reward0.strip()), CUSTOM)

    state: dict = {
        "maze": maze0,
        "Q": None,
        "path": None,
        "agent": maze0.start,
        "training": False,
    }
    job = {"id": 0}
    lock = threading.Lock()
    shared: dict = {
        "job": 0,
        "episode": 0,
        "total": 1,
        "returns": [],
        "done": False,
        "error": None,
        "result": None,
    }
    syncing = {"on": False}
    anim_i = {"n": 0}

    with ui.header().classes("items-center px-6 bg-slate-950 text-white"):
        with ui.column().classes("gap-0 py-1"):
            ui.label("Laberinto").classes("text-h5 leading-tight")
            ui.label("Q-learning tabular").classes("text-caption text-slate-300")

    with ui.element("div").classes("maze-layout w-full max-w-7xl mx-auto p-4"):
        with ui.column().classes("w-full gap-3"):
            with ui.card().classes("w-full"):
                ui.label("Laberinto").classes("text-lg")
                ui.label("Las filas y columnas empiezan en 0.").classes("text-caption text-slate-400")
                with ui.grid(columns=2).classes("w-full gap-2"):
                    rows_in = ui.number("Filas", value=maze0.rows, min=MIN_SIDE, max=MAX_SIDE, step=1, format="%.0f")
                    cols_in = ui.number("Columnas", value=maze0.cols, min=MIN_SIDE, max=MAX_SIDE, step=1, format="%.0f")
                    seed_in = ui.number("Semilla", value=maze0.seed, min=0, step=1, format="%.0f")
                    extra_in = ui.number(
                        "Pasillos extra",
                        value=maze0.extra_passages,
                        min=0,
                        max=80,
                        step=1,
                        format="%.0f",
                    )
                    start_r = ui.number("Fila salida", value=maze0.start[0], min=0, max=MAX_SIDE - 1, step=1, format="%.0f")
                    start_c = ui.number("Columna salida", value=maze0.start[1], min=0, max=MAX_SIDE - 1, step=1, format="%.0f")
                    goal_r = ui.number("Fila meta", value=maze0.goal[0], min=0, max=MAX_SIDE - 1, step=1, format="%.0f")
                    goal_c = ui.number("Columna meta", value=maze0.goal[1], min=0, max=MAX_SIDE - 1, step=1, format="%.0f")
                with ui.row().classes("w-full gap-2"):
                    generate_btn = ui.button("Generar", icon="auto_awesome", on_click=lambda: generate(False))
                    random_btn = ui.button("Aleatorio", icon="casino", on_click=lambda: generate(True)).props("outline")
                apply_btn = ui.button("Aplicar salida y meta", icon="pin_drop", on_click=lambda: move_ends()).props(
                    "outline"
                ).classes("w-full")
                name_in = ui.input("Nombre del archivo", value=safe_stem(maze0.name)).classes("w-full")
                with ui.row().classes("w-full gap-2"):
                    ui.button("Guardar", icon="save", on_click=lambda: save_maze())
                    ui.button("Descargar", icon="download", on_click=lambda: download_maze()).props("outline")
                stems = list_stems()
                saved = ui.select(
                    stems,
                    value=maze0.name if maze0.name in stems else (stems[0] if stems else None),
                    label="Archivos guardados",
                ).classes("w-full")
                ui.button("Cargar", icon="folder_open", on_click=lambda: load_maze()).props("outline")

        with ui.column().classes("w-full gap-3"):
            with ui.card().classes("w-full"):
                ui.label("Recompensa").classes("text-lg")
                ui.label(
                    "step = 1 en cada transición. goal = 1 al entrar en la meta. "
                    "hit_wall = 1 si choca. progress = distancia anterior − distancia nueva."
                ).classes("text-caption text-slate-400")
                preset = ui.select(PRESET_OPTIONS, value=preset0, label="Preset").classes("w-full")
                formula = ui.textarea("Función", value=reward0).classes("w-full").props(
                    "input-style='font-family: ui-monospace, monospace'"
                )
                preview_label = ui.label("").classes("text-caption text-slate-300")

            with ui.card().classes("w-full"):
                ui.label("Entrenamiento").classes("text-lg")
                ui.label("ε-greedy. En un empate, la flecha usa el orden N, E, S, W.").classes(
                    "text-caption text-slate-400"
                )
                with ui.grid(columns=2).classes("w-full gap-2"):
                    alpha_in = ui.number("Alfa α", value=0.2, min=0, max=1, step=0.05, format="%.2f")
                    gamma_in = ui.number("Gamma γ", value=0.95, min=0, max=1, step=0.01, format="%.2f")
                    eps_in = ui.number("Épsilon ε", value=0.25, min=0, max=1, step=0.05, format="%.2f")
                    episodes_in = ui.number("Episodios", value=500, min=1, max=5000, step=50, format="%.0f")
                    steps_in = ui.number("Pasos máx.", value=300, min=1, max=2000, step=10, format="%.0f")
                    agent_seed = ui.number("Semilla del agente", value=0, min=0, step=1, format="%.0f")
                arrows = ui.checkbox("Flechas de la política greedy", value=True)
                with ui.row().classes("w-full gap-2"):
                    train_btn = ui.button("Entrenar", icon="model_training", on_click=lambda: start_training())
                    stop_btn = ui.button("Detener", icon="stop", on_click=lambda: stop_training()).props("outline")
                play_btn = ui.button("Animar camino", icon="play_arrow", on_click=lambda: play()).props("outline").classes(
                    "w-full"
                )
                bar = ui.linear_progress(value=0, show_value=False).props("instant-feedback color=primary")
                bar.set_visibility(False)

        with ui.card().classes("w-full board"):
            svg_view = ui.html(render_svg(maze0), sanitize=False).classes("maze-svg w-full")
            status = ui.label("Listo para entrenar.").classes("text-body2 text-slate-200")
            ui.label("S salida · G meta · el punto es el agente. Pasa el cursor sobre una celda para ver Q.").classes(
                "text-caption text-slate-400"
            )
        with ui.card().classes("w-full returns"):
            ui.label("Retorno por episodio").classes("text-lg")
            chart = ui.echart(_chart_options()).classes("w-full").style("height: 260px")

    poll_timer = ui.timer(0.25, lambda: poll(), active=False)
    anim_timer = ui.timer(0.12, lambda: step_animation(), active=False)

    def current_reward_text() -> str:
        return (formula.value or "").strip()

    def compiled_reward() -> RewardFunction:
        return RewardFunction(current_reward_text())

    def refresh_preview() -> None:
        try:
            text = preview(current_reward_text())
        except RewardError as exc:
            preview_label.classes(replace="text-caption text-red-400")
            preview_label.set_text(str(exc))
            return
        preview_label.classes(replace="text-caption text-slate-300")
        preview_label.set_text(text)

    def on_preset(event) -> None:
        if syncing["on"]:
            return
        expr = PRESETS.get(event.value)
        if expr is None:
            return
        syncing["on"] = True
        formula.set_value(expr)
        syncing["on"] = False
        refresh_preview()
        forget_policy()

    def on_formula(_event) -> None:
        if syncing["on"]:
            return
        match = next((name for name, expr in PRESETS.items() if expr == current_reward_text()), None)
        syncing["on"] = True
        preset.set_value(match or CUSTOM)
        syncing["on"] = False
        refresh_preview()
        forget_policy()

    def read_ends(rows: int, cols: int) -> tuple[tuple[int, int], tuple[int, int]]:
        start = (_whole(start_r.value, 0), _whole(start_c.value, 0))
        goal = (_whole(goal_r.value, rows - 1), _whole(goal_c.value, cols - 1))
        try:
            validate_ends(rows, cols, start, goal)
        except ValueError:
            start, goal = (0, 0), (rows - 1, cols - 1)
            ui.notify("Salida o meta fuera de la cuadrícula: se usan las esquinas.", type="warning")
        start_r.set_value(start[0])
        start_c.set_value(start[1])
        goal_r.set_value(goal[0])
        goal_c.set_value(goal[1])
        return start, goal

    def fill_fields(maze: Maze) -> None:
        rows_in.set_value(maze.rows)
        cols_in.set_value(maze.cols)
        seed_in.set_value(maze.seed)
        extra_in.set_value(maze.extra_passages)
        start_r.set_value(maze.start[0])
        start_c.set_value(maze.start[1])
        goal_r.set_value(maze.goal[0])
        goal_c.set_value(maze.goal[1])
        name_in.set_value(safe_stem(maze.name))

    def set_reward_text(expr: str) -> None:
        match = next((name for name, preset_expr in PRESETS.items() if preset_expr == expr.strip()), None)
        syncing["on"] = True
        formula.set_value(expr)
        preset.set_value(match or CUSTOM)
        syncing["on"] = False
        refresh_preview()

    def redraw() -> None:
        maze = state["maze"]
        policy = None
        q = None
        if state["Q"] is not None and arrows.value:
            policy = greedy_policy(maze, state["Q"])
            q = state["Q"]
        trail = state["path"]
        svg_view.content = render_svg(maze, agent=state["agent"], policy=policy, trail=trail, q=q)

    def reset_chart() -> None:
        chart.options["xAxis"]["data"] = []
        chart.options["series"][0]["data"] = []
        chart.update()

    def show_returns(values: list[float]) -> None:
        xs, ys = _buckets(values)
        chart.options["xAxis"]["data"] = xs
        chart.options["series"][0]["data"] = ys
        chart.update()

    def set_busy(busy: bool) -> None:
        state["training"] = busy
        for button in (train_btn, generate_btn, random_btn, apply_btn, play_btn):
            button.disable() if busy else button.enable()
        stop_btn.enable() if busy else stop_btn.disable()
        bar.set_visibility(busy)

    def forget_policy() -> None:
        if state["training"]:
            job["id"] += 1
            poll_timer.deactivate()
            anim_timer.deactivate()
            set_busy(False)
        state["Q"] = None
        state["path"] = None
        state["agent"] = state["maze"].start
        anim_i["n"] = 0
        bar.set_value(0)
        reset_chart()
        status.set_text("Listo para entrenar.")
        redraw()

    def adopt(maze: Maze) -> None:
        if not is_reachable(maze):
            ui.notify("Ese laberinto no tiene camino hasta la meta.", type="negative")
        state["maze"] = maze
        fill_fields(maze)
        forget_policy()

    def generate(randomize: bool) -> None:
        if randomize:
            seed_in.set_value(random.randint(0, 999_999))
        rows = _whole(rows_in.value, 8)
        cols = _whole(cols_in.value, 8)
        start, goal = read_ends(rows, cols)
        try:
            maze = generate_maze(
                rows,
                cols,
                seed=_whole(seed_in.value, 0),
                extra_passages=_whole(extra_in.value, 0),
                start=start,
                goal=goal,
                name=safe_stem(name_in.value or "laberinto"),
            )
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        adopt(maze)

    def move_ends() -> None:
        maze = state["maze"]
        start, goal = read_ends(maze.rows, maze.cols)
        try:
            validate_ends(maze.rows, maze.cols, start, goal)
        except ValueError as exc:
            ui.notify(str(exc), type="negative")
            return
        moved = replace(maze, start=start, goal=goal)
        if not is_reachable(moved):
            ui.notify("Con esa salida y esa meta no hay camino.", type="negative")
            return
        adopt(moved)

    def refresh_files(select: str | None = None) -> None:
        stems = list_stems()
        current = select if select in stems else saved.value
        if current not in stems:
            current = stems[0] if stems else None
        saved.set_options(stems, value=current)

    def save_maze() -> None:
        maze = state["maze"]
        expr = current_reward_text()
        try:
            RewardFunction(expr)
            path = save(maze, expr, name_in.value or maze.name)
        except (RewardError, ValueError, OSError) as exc:
            ui.notify(str(exc), type="negative")
            return
        maze.name = path.stem
        name_in.set_value(path.stem)
        refresh_files(path.stem)
        ui.notify(f"Guardado en {path.name}", type="positive")

    def download_maze() -> None:
        maze = state["maze"]
        expr = current_reward_text()
        try:
            RewardFunction(expr)
            if not is_reachable(maze):
                raise ValueError("no hay camino de la salida a la meta")
            payload = dumps(maze, expr).encode("utf-8")
        except (RewardError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        ui.download(payload, f"{safe_stem(name_in.value or maze.name)}.yaml")

    def load_maze() -> None:
        stem = saved.value
        if not stem or stem == "(vacío)":
            ui.notify("No hay laberintos guardados.", type="warning")
            return
        path = MAZES_DIR / f"{stem}.yaml"
        try:
            maze, expr = load(path)
        except (OSError, ValueError, yaml_error()) as exc:
            ui.notify(str(exc), type="negative")
            return
        set_reward_text(expr)
        adopt(maze)
        if not is_reachable(maze):
            return
        ui.notify(f"Cargado {path.name}", type="positive")

    def start_training() -> None:
        if state["training"]:
            return
        maze = state["maze"]
        if not is_reachable(maze):
            ui.notify("No hay camino de la salida a la meta.", type="negative")
            return
        try:
            reward_fn = compiled_reward()
        except RewardError as exc:
            ui.notify(str(exc), type="negative")
            return
        cfg = TrainConfig(
            alpha=float(alpha_in.value if alpha_in.value is not None else 0.2),
            gamma=float(gamma_in.value if gamma_in.value is not None else 0.95),
            epsilon=float(eps_in.value if eps_in.value is not None else 0.25),
            episodes=_whole(episodes_in.value, 500),
            max_steps=_whole(steps_in.value, 300),
            seed=_whole(agent_seed.value, 0),
        )
        snapshot = replace(maze, passages=set(maze.passages))
        job["id"] += 1
        mine = job["id"]
        with lock:
            shared.update(
                job=mine,
                episode=0,
                total=cfg.episodes,
                returns=[],
                done=False,
                error=None,
                result=None,
            )
        state["Q"] = None
        state["path"] = None
        state["agent"] = snapshot.start
        state["reward_fn"] = reward_fn
        anim_timer.deactivate()
        set_busy(True)
        bar.set_value(0)
        status.set_text(f"Entrenando… 0 / {cfg.episodes}")
        redraw()

        def on_batch(episode: int, returns: list[float]) -> None:
            with lock:
                if shared["job"] != mine:
                    return
                shared["episode"] = episode
                shared["returns"] = returns

        def work() -> None:
            try:
                result = train(
                    snapshot,
                    reward_fn,
                    cfg,
                    on_batch=on_batch,
                    batch=max(1, cfg.episodes // 40),
                    should_stop=lambda: job["id"] != mine,
                )
            except Exception as exc:  # noqa: BLE001 — show the message in the UI
                with lock:
                    if shared["job"] == mine:
                        shared["error"] = str(exc)
                        shared["done"] = True
                return
            with lock:
                if shared["job"] == mine:
                    shared["result"] = result
                    shared["returns"] = result.returns
                    shared["episode"] = len(result.returns)
                    shared["done"] = True

        threading.Thread(target=work, daemon=True).start()
        poll_timer.activate()

    def stop_training() -> None:
        if not state["training"]:
            return
        job["id"] += 1
        poll_timer.deactivate()
        set_busy(False)
        status.set_text("Entrenamiento detenido.")

    def poll() -> None:
        with lock:
            if shared["job"] != job["id"]:
                return
            episode = shared["episode"]
            total = shared["total"]
            returns = list(shared["returns"])
            done = shared["done"]
            error = shared["error"]
            result: TrainResult | None = shared["result"]
        if total:
            bar.set_value(min(1.0, episode / total))
        if returns:
            show_returns(returns)
            status.set_text(f"Episodio {episode} de {total} · retorno {returns[-1]:.2f}")
        if not done:
            return
        poll_timer.deactivate()
        set_busy(False)
        if error:
            ui.notify(error, type="negative")
            status.set_text(error)
            return
        if result is None:
            return
        state["Q"] = result.q
        finish = greedy_rollout(
            state["maze"],
            result.q,
            state.get("reward_fn") or compiled_reward(),
            _whole(steps_in.value, 300),
        )
        state["path"] = None
        state["agent"] = state["maze"].start
        if result.stopped:
            message = "Entrenamiento detenido. "
        else:
            message = ""
        if finish.reached:
            message += f"La política greedy llega en {len(finish.path) - 1} pasos. Retorno {finish.total:.2f}."
        else:
            message += "La política greedy no llega a la meta."
        status.set_text(message)
        redraw()

    def play() -> None:
        if state["Q"] is None:
            ui.notify("Entrena primero.", type="warning")
            return
        reward_fn = state.get("reward_fn")
        if reward_fn is None:
            try:
                reward_fn = compiled_reward()
            except RewardError as exc:
                ui.notify(str(exc), type="negative")
                return
        finish = greedy_rollout(
            state["maze"],
            state["Q"],
            reward_fn,
            _whole(steps_in.value, 300),
        )
        state["path"] = [finish.path[0]]
        state["agent"] = finish.path[0]
        anim_i["n"] = 0
        state["_roll"] = finish
        anim_timer.interval = 0.08 if len(finish.path) > 40 else 0.14
        redraw()
        if len(finish.path) <= 1:
            return
        anim_timer.activate()

    def step_animation() -> None:
        finish = state.get("_roll")
        if finish is None:
            anim_timer.deactivate()
            return
        anim_i["n"] += 1
        index = min(anim_i["n"], len(finish.path) - 1)
        state["path"] = finish.path[: index + 1]
        state["agent"] = finish.path[index]
        redraw()
        if index >= len(finish.path) - 1:
            anim_timer.deactivate()
            if finish.reached:
                status.set_text(
                    f"Camino greedy: {len(finish.path) - 1} pasos. Retorno {finish.total:.2f}."
                )
            else:
                status.set_text("La política greedy no llega a la meta.")

    preset.on_value_change(on_preset)
    formula.on_value_change(on_formula)
    arrows.on_value_change(lambda _: redraw())
    refresh_preview()
    stop_btn.disable()


def yaml_error() -> type[BaseException]:
    import yaml

    return yaml.YAMLError


def main() -> None:
    ui.run(
        title="Q-learning · Laberinto",
        host="127.0.0.1",
        port=8765,
        dark=True,
        language="es",
        reload=False,
        show=os.environ.get("MAZE_NO_BROWSER") != "1",
        favicon="🧭",
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
