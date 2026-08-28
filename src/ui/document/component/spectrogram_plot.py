import numpy as np
import pyqtgraph as pg
from PyQt6.QtWidgets import QWidget

from res.constants import MAX_SGRAM_LENGTH
from ui.document.state.sgram_state import SpectrogramState


class SpectrogramPlot(pg.PlotItem):
    def __init__(
        self, parent: QWidget | None = None, linked_plot: pg.PlotItem | None = None
    ):
        super().__init__(parent)

        self.setLabel("left", self.tr("Frequency"), units="Hz")
        self.getAxis("left").enableAutoSIPrefix(False)
        self.getAxis("left").setWidth(60)

        self.setLabel("bottom", self.tr("Time"), units="s")
        self.getAxis("bottom").enableAutoSIPrefix(False)

        self.showGrid(x=True, y=True, alpha=0.3)
        self.getViewBox().setMouseEnabled(x=False, y=False)
        self.getViewBox().rbScaleBox.hide()

        self.spec_img = pg.ImageItem()
        self.addItem(self.spec_img)
        lut = pg.colormap.get("CET-L1").getLookupTable(nPts=256)[::-1]
        self.spec_img.setLookupTable(lut)

        self.cursor_line = pg.InfiniteLine(angle=90, movable=False, pen="r")
        self.addItem(self.cursor_line, ignoreBounds=True)
        self.cursor_line.setVisible(False)

        self.selection_region = pg.LinearRegionItem(
            values=[0, 0],
            brush=pg.mkBrush(0, 100, 200, 50),
            movable=False,
        )
        self.selection_region.setZValue(10)
        self.addItem(self.selection_region)
        self.selection_region.setVisible(False)

        self.getViewBox().setXLink(linked_plot)

        self.center_text_item = pg.TextItem(
            self.tr("Zoom to a chunk of {} seconds or shorter to see spectrogram").format(MAX_SGRAM_LENGTH),
            anchor=(0.5, 0.5),
        )
        self.center_text_item.setFont(pg.Qt.QtGui.QFont("Arial", 32))
        self.center_text_item.setVisible(False)
        self.addItem(self.center_text_item)

    def populate_spectrogram(self, sgram: SpectrogramState, gray_cutoff: float):
        """Fill the spectrogram image with data"""

        self.center_text_item.setVisible(False)

        self.getViewBox().setLimits(yMin=0, yMax=sgram.f[-1])
        self.getViewBox().setYRange(sgram.f[0], sgram.f[-1])

        vmin = (
            np.min(sgram.sxx_window)
            + (np.max(sgram.sxx_window) - np.min(sgram.sxx_window)) * gray_cutoff
        )
        self.spec_img.setImage(
            sgram.sxx_window.T,
            autoLevels=False,
            levels=(vmin, np.max(sgram.sxx_window)),
        )

        time_start = sgram.t_window[0]
        time_end = sgram.t_window[-1]
        freq_start = sgram.f[0]
        freq_end = sgram.f[-1]

        rect = pg.QtCore.QRectF(
            time_start, freq_start, time_end - time_start, freq_end - freq_start
        )
        self.spec_img.setRect(rect)

        return True

    def set_cursor_position(self, x: float, visible: bool):
        self.cursor_line.setPos(x)
        self.cursor_line.setVisible(visible)

    def update_selection_region(self, box_left: float, xrange: float):
        if xrange > 0:
            self.selection_region.setRegion([box_left, box_left + xrange])
            self.selection_region.setVisible(True)
        else:
            self.selection_region.setVisible(False)

    def display_window_too_big(self):
        if self.spec_img:
            self.spec_img.clear()

        x_range, y_range = self.getViewBox().viewRange()
        center_x = (x_range[0] + x_range[1]) / 2.0
        center_y = (y_range[0] + y_range[1]) / 2.0

        self.center_text_item.setPos(center_x, center_y)
        self.center_text_item.setVisible(True)
