# @author Cursor
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app_storage import LOG_LEVELS, AppStore, GuiSettings, ProjectRow, build_review_settings
from config import ConfigError, Settings
from main import run_review

USAGE_TEXT = """\
1. 最初に「設定」で次を保存します。
   - GITLAB_TOKEN
   - OPENAI_API_KEY
   - GITLAB_URL
   LOG_LEVEL、SUMMARY_MAX_LINES、SUMMARY_MAX_CHARS もここで変更できます。
2. 左上の「行を追加」でレビュー対象を追加します。行番号は 1、2、3 と増えます。
3. プロジェクト名、プロジェクトID、マージリクエストIDを入力します。入力欄からフォーカスが外れると保存されます。
4. 「アップロード」でレビュー仕様書（Markdown）を選びます。一度保存され、再アップロードで置き換わります。
5. 「レビュー実行」で、その行のマージリクエストをレビューし、GitLab にコメントとサマリーを投稿します。
6. 実行中のログは画面下部に表示されます。同時に実行できるのは 1 件です。
"""


class _Signals(QObject):
    log = Signal(str)
    finished = Signal()


class _SignalLogHandler(logging.Handler):
    def __init__(self, signals: _Signals) -> None:
        super().__init__()
        self._signals = signals

    def emit(self, record: logging.LogRecord) -> None:
        self._signals.log.emit(self.format(record) + "\n")


class _SignalStream:
    def __init__(self, signals: _Signals) -> None:
        self._signals = signals

    def write(self, text: str) -> int:
        if text:
            self._signals.log.emit(text if text.endswith("\n") else text + "\n")
        return len(text)

    def flush(self) -> None:
        return None


class ReviewApp(QWidget):
    def __init__(self, store: AppStore | None = None) -> None:
        super().__init__()
        self.store = store or AppStore()
        self.settings = self.store.load_settings()
        self.rows = self.store.load_projects()
        self._running = False
        self._run_buttons: list[QPushButton] = []
        self._fields: dict[tuple[str, str], QLineEdit] = {}
        self._signals = _Signals()
        self._signals.log.connect(self._append_log)
        self._signals.finished.connect(self._review_finished)

        self.setWindowTitle("レビュー")
        self.resize(1080, 680)
        self.setMinimumSize(860, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        self.header = QHBoxLayout()
        root.addLayout(self.header)
        self.body = QVBoxLayout()
        root.addLayout(self.body, stretch=1)
        log_label = QLabel("ログ")
        root.addWidget(log_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(160)
        root.addWidget(self.log)
        self.status_bar = QStatusBar()
        usage_button = QPushButton("使い方")
        usage_button.clicked.connect(self._show_usage)
        self.status_bar.addPermanentWidget(usage_button)
        root.addWidget(self.status_bar)

        handler = _SignalLogHandler(self._signals)
        handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(getattr(logging, self.settings.log_level, logging.INFO))
        self._render()

    def _show_usage(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("使い方")
        dialog.resize(640, 420)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(USAGE_TEXT)
        text.setReadOnly(True)
        layout.addWidget(text)
        close_button = QPushButton("閉じる")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    def _render(self) -> None:
        self._clear_layout(self.header)
        self._clear_layout(self.body)
        self._run_buttons.clear()
        self._fields.clear()

        add_button = QPushButton("行を追加")
        add_button.clicked.connect(self._add_row)
        self.header.addWidget(add_button)
        self.header.addStretch(1)
        if self.settings.is_configured():
            settings_button = QPushButton("設定")
            settings_button.clicked.connect(self._open_settings)
            self.header.addWidget(settings_button)

        if not self.settings.is_configured() and not self.rows:
            prompt = QWidget()
            prompt_layout = QVBoxLayout(prompt)
            prompt_layout.addStretch(1)
            message = QLabel("先に接続設定を保存してください")
            message.setAlignment(Qt.AlignmentFlag.AlignCenter)
            prompt_layout.addWidget(message)
            setup_button = QPushButton("設定してください")
            setup_button.clicked.connect(self._open_settings)
            prompt_layout.addWidget(setup_button, alignment=Qt.AlignmentFlag.AlignCenter)
            prompt_layout.addStretch(1)
            self.body.addWidget(prompt, stretch=1)
            return

        if not self.settings.is_configured():
            banner = QHBoxLayout()
            banner.addWidget(QLabel("先に接続設定を保存してください"))
            setup_button = QPushButton("設定してください")
            setup_button.clicked.connect(self._open_settings)
            banner.addWidget(setup_button)
            banner.addStretch(1)
            self.body.addLayout(banner)

        self.body.addWidget(self._build_table(), stretch=1)

    def _build_table(self) -> QScrollArea:
        table = QWidget()
        grid = QGridLayout(table)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        columns = (
            ("#", 36),
            ("プロジェクト名", 180),
            ("プロジェクトID", 120),
            ("マージリクエストID", 160),
            ("レビュー仕様書", 180),
        )
        for column, (title, width) in enumerate(columns):
            label = QLabel(title)
            label.setMinimumWidth(width)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(label, 0, column)
            grid.setColumnMinimumWidth(column, width)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        grid.setColumnStretch(3, 1)
        grid.setColumnStretch(4, 1)

        for index, row in enumerate(self.rows, start=1):
            self._add_row_cells(grid, index, row)
        grid.setRowStretch(len(self.rows) + 1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(table)
        return scroll

    def _add_row_cells(self, grid: QGridLayout, index: int, row: ProjectRow) -> None:
        number = QLabel(str(index))
        number.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(number, index, 0)
        grid.addWidget(self._line_edit(row, "name", row.name), index, 1)
        grid.addWidget(self._line_edit(row, "project_id", row.project_id), index, 2)
        grid.addWidget(self._line_edit(row, "mr_iid", row.mr_iid), index, 3)
        rules_label = QLabel(row.rules_filename if self.store.has_rules(row.id) else "未設定")
        rules_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(rules_label, index, 4)
        upload = QPushButton("アップロード")
        upload.clicked.connect(lambda _checked=False, row_id=row.id: self._upload_rules(row_id))
        grid.addWidget(upload, index, 5)
        run_button = QPushButton("レビュー実行")
        run_button.clicked.connect(lambda _checked=False, row_id=row.id: self._run_row(row_id))
        run_button.setEnabled(not self._running)
        self._run_buttons.append(run_button)
        grid.addWidget(run_button, index, 6)
        delete = QPushButton("削除")
        delete.clicked.connect(lambda _checked=False, row_id=row.id: self._delete_row(row_id))
        grid.addWidget(delete, index, 7)

    def _line_edit(self, row: ProjectRow, field: str, value: str) -> QLineEdit:
        edit = QLineEdit(value)
        self._fields[(row.id, field)] = edit
        edit.editingFinished.connect(lambda row_id=row.id, key=field: self._save_row_field(row_id, key))
        return edit

    def _save_row_field(self, row_id: str, field: str) -> None:
        edit = self._fields.get((row_id, field))
        if edit is None:
            return
        for row in self.rows:
            if row.id == row_id:
                setattr(row, field, edit.text().strip())
                break
        self.store.save_projects(self.rows)

    def _save_visible_rows(self) -> None:
        for (row_id, field), edit in self._fields.items():
            for row in self.rows:
                if row.id == row_id:
                    setattr(row, field, edit.text().strip())
        if self.rows:
            self.store.save_projects(self.rows)

    def _add_row(self) -> None:
        self._save_visible_rows()
        self.rows.append(ProjectRow.create())
        self.store.save_projects(self.rows)
        self._render()

    def _delete_row(self, row_id: str) -> None:
        if self._running:
            return
        answer = QMessageBox.question(self, "削除", "この行を削除しますか？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.rows = [row for row in self.rows if row.id != row_id]
        self.store.delete_rules(row_id)
        self.store.save_projects(self.rows)
        self._render()

    def _upload_rules(self, row_id: str) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self,
            "レビュー仕様書",
            "",
            "Markdown (*.md);;すべてのファイル (*.*)",
        )
        if not selected:
            return
        try:
            filename = self.store.store_rules(row_id, Path(selected))
        except (OSError, UnicodeError, ConfigError) as exc:
            QMessageBox.critical(self, "アップロード", str(exc))
            return
        for row in self.rows:
            if row.id == row_id:
                row.rules_filename = filename
                break
        self.store.save_projects(self.rows)
        self._append_log(f"仕様書を保存しました: {filename}\n")
        self._render()

    def _open_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("設定")
        form = QFormLayout(dialog)
        token = QLineEdit(self.settings.gitlab_token)
        token.setEchoMode(QLineEdit.EchoMode.Password)
        api_key = QLineEdit(self.settings.openai_api_key)
        api_key.setEchoMode(QLineEdit.EchoMode.Password)
        gitlab_url = QLineEdit(self.settings.gitlab_url)
        summary_lines = QLineEdit(str(self.settings.summary_max_lines))
        summary_chars = QLineEdit(str(self.settings.summary_max_chars))
        log_level = QComboBox()
        log_level.addItems(list(LOG_LEVELS))
        log_level.setCurrentText(self.settings.log_level)
        form.addRow("GITLAB_TOKEN", token)
        form.addRow("OPENAI_API_KEY", api_key)
        form.addRow("GITLAB_URL", gitlab_url)
        form.addRow("LOG_LEVEL", log_level)
        form.addRow("SUMMARY_MAX_LINES", summary_lines)
        form.addRow("SUMMARY_MAX_CHARS", summary_chars)

        buttons = QHBoxLayout()
        save_button = QPushButton("保存")
        buttons.addStretch(1)
        buttons.addWidget(save_button)
        form.addRow(buttons)

        def save() -> None:
            try:
                summary_max_lines = int(summary_lines.text().strip())
                summary_max_chars = int(summary_chars.text().strip())
            except ValueError:
                QMessageBox.critical(dialog, "設定", "SUMMARY_MAX_LINES と SUMMARY_MAX_CHARS は整数です")
                return
            candidate = GuiSettings(
                gitlab_token=token.text(),
                openai_api_key=api_key.text(),
                gitlab_url=gitlab_url.text(),
                log_level=log_level.currentText(),
                summary_max_lines=summary_max_lines,
                summary_max_chars=summary_max_chars,
            )
            if not candidate.is_configured():
                QMessageBox.critical(
                    dialog,
                    "設定",
                    "GITLAB_TOKEN、OPENAI_API_KEY、GITLAB_URL を入力してください",
                )
                return
            try:
                self.settings = self.store.save_settings(candidate)
            except ConfigError as exc:
                QMessageBox.critical(dialog, "設定", str(exc))
                return
            logging.getLogger().setLevel(getattr(logging, self.settings.log_level, logging.INFO))
            dialog.accept()
            self._render()

        save_button.clicked.connect(save)
        dialog.exec()

    def _run_row(self, row_id: str) -> None:
        if self._running:
            return
        self._save_visible_rows()
        row = next((item for item in self.rows if item.id == row_id), None)
        if row is None:
            return
        if not self.settings.is_configured():
            self._append_log("先に接続設定を保存してください\n")
            return
        try:
            project_id = int(row.project_id)
            mr_iid = int(row.mr_iid)
        except ValueError:
            self._append_log("プロジェクトIDとマージリクエストIDは整数です\n")
            return
        if not self.store.has_rules(row.id):
            self._append_log("レビュー仕様書をアップロードしてください\n")
            return
        try:
            review_settings = build_review_settings(self.settings, project_id, mr_iid)
        except ConfigError as exc:
            self._append_log(f"{exc}\n")
            return

        self._running = True
        self._set_run_buttons_enabled(False)
        self._append_log(f"レビューを開始します: {row.name or row.project_id} !{mr_iid}\n")
        worker = threading.Thread(
            target=self._run_worker,
            args=(review_settings, self.store.rules_path(row.id)),
            daemon=True,
        )
        worker.start()

    def _run_worker(self, review_settings: Settings, rules_path: Path) -> None:
        stream = _SignalStream(self._signals)
        previous_stdout = sys.stdout
        previous_stderr = sys.stderr
        sys.stdout = stream
        sys.stderr = stream
        try:
            logging.getLogger().setLevel(getattr(logging, review_settings.log_level, logging.INFO))
            run_review(review_settings, rules_path)
        except Exception as exc:  # noqa: BLE001
            self._signals.log.emit(f"ERROR: {exc}\n")
        finally:
            sys.stdout = previous_stdout
            sys.stderr = previous_stderr
            self._signals.finished.emit()

    def _review_finished(self) -> None:
        self._running = False
        self._set_run_buttons_enabled(True)

    def _set_run_buttons_enabled(self, enabled: bool) -> None:
        for button in self._run_buttons:
            button.setEnabled(enabled)

    def _append_log(self, text: str) -> None:
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)

    def _clear_layout(self, layout: QHBoxLayout | QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child is not None:
                self._clear_layout(child)  # type: ignore[arg-type]


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ReviewApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
