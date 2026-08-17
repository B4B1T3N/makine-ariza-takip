"""Matplotlib tabanlı grafik bileşenleri.

Tasarım kuralları:
  * Tek serili grafiklerde tek renk, açıklama kutusu yok (başlık seriyi tanımlar).
  * İki serili grafikte hem açıklama kutusu hem farklı işaretçi kullanılır;
    böylece seriler yalnızca renkle ayrışmaz.
  * Öncelik/durum dağılımları sıralı veri olduğu için açıktan koyuya tek hue
    rampası kullanır; eksen etiketi kimliği taşır.
  * Değerler doğrudan çubuk uçlarına yazılır, ızgara geri planda kalır.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402
from PyQt6.QtWidgets import QSizePolicy  # noqa: E402

from app.ui import style  # noqa: E402

matplotlib.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
    "font.size": 9,
    "axes.edgecolor": style.CHART_AXIS,
    "axes.labelcolor": style.CHART_INK,
    "text.color": style.CHART_INK,
    "xtick.color": style.CHART_INK_MUTED,
    "ytick.color": style.CHART_INK_MUTED,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.titlecolor": style.PRIMARY,
    "figure.autolayout": False,
})


class ChartCanvas(FigureCanvasQTAgg):
    """Tek eksenli, yeniden çizilebilir grafik yüzeyi."""

    def __init__(self, height: float = 3.0, parent=None):
        self.figure = Figure(figsize=(5, height), dpi=100,
                             facecolor=style.CHART_SURFACE)
        super().__init__(self.figure)
        self.setParent(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(int(height * 100))
        self.ax = self.figure.add_subplot(111)
        self._prepare_axes()

    def _prepare_axes(self) -> None:
        self.ax.set_facecolor(style.CHART_SURFACE)
        for side in ("top", "right"):
            self.ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            self.ax.spines[side].set_color(style.CHART_AXIS)
            self.ax.spines[side].set_linewidth(1.0)
        self.ax.tick_params(length=0, pad=6)

    def reset(self) -> None:
        self.figure.clear()
        self.ax = self.figure.add_subplot(111)
        self._prepare_axes()

    def show_empty(self, message: str = "Gösterilecek veri yok") -> None:
        self.reset()
        self.ax.text(0.5, 0.5, message, ha="center", va="center",
                     color=style.CHART_INK_MUTED, fontsize=10,
                     transform=self.ax.transAxes)
        self.ax.set_axis_off()
        self.figure.tight_layout()
        self.draw_idle()

    # --- Grafik tipleri ---------------------------------------------------
    def draw_hbar(
        self,
        labels: list[str],
        values: list[float],
        colors: list[str] | str = style.CHART_SINGLE,
        title: str = "",
        value_fmt: str = "{:.0f}",
        xlabel: str = "",
    ) -> None:
        """Yatay çubuk: sıralı listeler (top 10 makine, dağılımlar)."""
        if not labels or not any(values):
            self.show_empty()
            return

        self.reset()
        if isinstance(colors, str):
            colors = [colors] * len(labels)

        positions = range(len(labels))
        # En büyük değer en üstte görünsün diye eksen ters çevrilir.
        bars = self.ax.barh(list(positions), values, height=0.62, color=colors,
                            edgecolor=style.CHART_SURFACE, linewidth=2)
        self.ax.set_yticks(list(positions))
        self.ax.set_yticklabels(labels)
        self.ax.invert_yaxis()

        self.ax.xaxis.grid(True, color=style.CHART_GRID, linewidth=0.8)
        self.ax.set_axisbelow(True)
        self.ax.spines["left"].set_visible(False)
        self.ax.tick_params(axis="x", labelsize=8)
        # Kayıt sayıları tam sayıdır; eksende ondalık tik gösterilmez.
        self.ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        if xlabel:
            self.ax.set_xlabel(xlabel, fontsize=8, color=style.CHART_INK_MUTED)

        top = max(values) if max(values) else 1
        self.ax.set_xlim(0, top * 1.16)
        for bar, value in zip(bars, values):
            self.ax.text(
                bar.get_width() + top * 0.02,
                bar.get_y() + bar.get_height() / 2,
                value_fmt.format(value),
                va="center", ha="left", fontsize=8.5, fontweight="bold",
                color=style.CHART_INK,
            )

        if title:
            self.ax.set_title(title, loc="left", pad=10)
        self.figure.tight_layout()
        self.draw_idle()

    def draw_vbar(
        self,
        labels: list[str],
        values: list[float],
        colors: list[str] | str = style.CHART_SINGLE,
        title: str = "",
        ylabel: str = "",
    ) -> None:
        """Dikey çubuk: az sayıda kategori (öncelik dağılımı)."""
        if not labels or not any(values):
            self.show_empty()
            return

        self.reset()
        if isinstance(colors, str):
            colors = [colors] * len(labels)

        positions = range(len(labels))
        bars = self.ax.bar(list(positions), values, width=0.58, color=colors,
                           edgecolor=style.CHART_SURFACE, linewidth=2)
        self.ax.set_xticks(list(positions))
        self.ax.set_xticklabels(labels)

        self.ax.yaxis.grid(True, color=style.CHART_GRID, linewidth=0.8)
        self.ax.set_axisbelow(True)
        self.ax.spines["bottom"].set_color(style.CHART_AXIS)
        self.ax.tick_params(axis="y", labelsize=8)
        self.ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        if ylabel:
            self.ax.set_ylabel(ylabel, fontsize=8, color=style.CHART_INK_MUTED)

        top = max(values) if max(values) else 1
        self.ax.set_ylim(0, top * 1.18)
        for bar, value in zip(bars, values):
            self.ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + top * 0.03,
                f"{value:.0f}",
                ha="center", va="bottom", fontsize=9, fontweight="bold",
                color=style.CHART_INK,
            )

        if title:
            self.ax.set_title(title, loc="left", pad=10)
        self.figure.tight_layout()
        self.draw_idle()

    def draw_trend(
        self,
        labels: list[str],
        series: list[tuple[str, list[float]]],
        title: str = "",
        ylabel: str = "Kayıt sayısı",
    ) -> None:
        """Zaman serisi çizgi grafiği (açılan / kapanan arıza)."""
        if not labels:
            self.show_empty()
            return

        self.reset()
        # Seriler renk dışında işaretçi ile de ayrışır.
        markers = ["o", "s", "^", "D"]
        linestyles = ["-", "--", "-.", ":"]

        x = range(len(labels))
        for i, (name, values) in enumerate(series):
            self.ax.plot(
                list(x), values,
                label=name,
                color=style.CHART_SERIES[i % len(style.CHART_SERIES)],
                linewidth=2,
                marker=markers[i % len(markers)],
                markersize=4.5 if len(labels) > 25 else 6,
                markeredgecolor=style.CHART_SURFACE,
                markeredgewidth=1.5,
                linestyle=linestyles[i % len(linestyles)],
            )

        self.ax.set_xticks(list(x))
        self.ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7.5)
        # Etiket kalabalığını önlemek için aralıklı gösterim.
        step = max(1, len(labels) // 12)
        for i, tick in enumerate(self.ax.get_xticklabels()):
            tick.set_visible(i % step == 0 or i == len(labels) - 1)

        self.ax.yaxis.grid(True, color=style.CHART_GRID, linewidth=0.8)
        self.ax.set_axisbelow(True)
        self.ax.set_ylabel(ylabel, fontsize=8, color=style.CHART_INK_MUTED)
        self.ax.tick_params(axis="y", labelsize=8)
        self.ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=6))
        self.ax.set_ylim(bottom=0)
        self.ax.margins(x=0.02)

        if len(series) > 1:
            legend = self.ax.legend(
                loc="upper left", frameon=False, fontsize=8.5, ncols=len(series)
            )
            for text in legend.get_texts():
                text.set_color(style.CHART_INK)

        if title:
            self.ax.set_title(title, loc="left", pad=10)
        self.figure.tight_layout()
        self.draw_idle()


def ordinal_colors(count: int) -> list[str]:
    """Sıralı veriler için açıktan koyuya doğrulanmış mavi rampa."""
    if count <= 4:
        return style.CHART_ORDINAL_4[:count]
    return style.CHART_ORDINAL_5[:count]
