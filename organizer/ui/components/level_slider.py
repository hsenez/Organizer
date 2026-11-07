"""Curseur à crans pour une caractéristique (importance, urgence, statut, type).

On peut **glisser** le curseur, **cliquer** sur la piste, ou **cliquer sur un emoji** sous la piste.
Chaque cran a son emoji, son libellé et une infobulle ; la couleur du curseur suit la valeur.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from enum import Enum
from typing import Generic, TypeVar

from nicegui import ui

from organizer.ui.theme import color_name

E = TypeVar("E", bound=Enum)


class LevelSlider(Generic[E]):
    def __init__(
        self,
        title: str,
        options: Sequence[E],
        value: E,
        on_change: Callable[[E], None],
        *,
        marker: str | None = None,
    ):
        self.options = list(options)
        self.value = value
        self._on_change = on_change
        self._options_ui: list[ui.element] = []
        last = len(self.options) - 1

        with ui.column().classes("w-full gap-0") as self.root:
            if marker:
                self.root.mark(marker)
            with ui.row().classes("w-full items-baseline justify-between"):
                ui.label(title).classes("text-sm text-gray-500")
                self.current = ui.label().classes("text-sm font-semibold")
            # Chaque cran occupe une cellule de même largeur ; la piste va du centre de la première cellule au
            # centre de la dernière, pour que les crans tombent pile sous les emojis.
            half_cell = 50 / len(self.options)
            with ui.element("div").classes("w-full").style(f"padding: 0 {half_cell}%"):
                self.slider = (
                    ui.slider(min=0, max=last, step=1, value=self.options.index(value))
                    .props("markers snap track-size=6px thumb-size=20px")
                    .on_value_change(lambda e: self._select_index(int(e.value), notify=True))
                )
            with ui.row().classes("w-full no-wrap gap-0 -mt-1"):
                for index, option in enumerate(self.options):
                    with (
                        ui.column()
                        .classes("level-option flex-1 basis-0 min-w-0 items-center gap-0")
                        .on("click", lambda i=index: self.slider.set_value(i))
                        .tooltip(f"{option.meta.label} — {option.meta.tooltip}") as option_ui
                    ):
                        if marker:
                            option_ui.mark(f"{marker}-{option.value}")
                        ui.label(option.meta.emoji).classes("text-lg leading-6")
                        ui.label(option.meta.label).classes("text-[10px] leading-3 text-center")
                    self._options_ui.append(option_ui)
        self._select_index(self.options.index(value), notify=False)

    def _select_index(self, index: int, *, notify: bool) -> None:
        option = self.options[index]
        changed = option != self.value
        self.value = option
        self.slider.props(f"color={color_name(option)}")
        self.current.set_text(option.meta.text)
        self.current.style(f"color: {option.meta.color}")
        for i, element in enumerate(self._options_ui):
            if i == index:
                element.classes(add="level-selected").style("opacity: 1")
            else:
                element.classes(remove="level-selected").style("opacity: 0.55")
        if notify and changed:
            self._on_change(option)

    def set(self, value: E) -> None:
        """Change la valeur affichée sans déclencher ``on_change``."""
        self.value = value  # avant set_value : le rappel verra « pas de changement » et ne notifiera pas
        index = self.options.index(value)
        self.slider.set_value(index)
        self._select_index(index, notify=False)
