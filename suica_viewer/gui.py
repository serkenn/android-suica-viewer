import csv
import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import nfc
from nfc.tag import Tag
from nfc.tag.tt3_sony import FelicaStandard

from .auth_client import FelicaRemoteClient, FelicaRemoteClientError
from .card_data import (
    CardData,
    CardDataService,
    SystemInfo,
    resolve_server_url,
)
from .reader_errors import describe_reader_error
from .station_code_lookup import StationCodeLookup
from .utils import SYSTEM_CODE, format_region, format_yen

SUMMARY_VAR_KEYS: tuple[str, ...] = (
    "idi",
    "pmi",
    "idm",
    "pmm",
    "card_type",
    "issuer",
    "balance",
    "last_topup_amount",
    "transaction_number",
    "issued_at",
    "expires_at",
    "issued_station",
    "commuter_pass",
    "commuter_period",
)
COMMUTER_DETAIL_KEYS: tuple[str, ...] = (
    "valid_from",
    "valid_to",
    "start_station",
    "end_station",
    "via1",
    "via2",
    "issued_at",
)
SF_GATE_VAR_KEYS: tuple[str, ...] = (
    "entry_station",
    "intermediate_entry",
    "intermediate_entry_date",
    "intermediate_entry_time",
    "intermediate_exit",
    "intermediate_exit_time",
    "unknown_value1",
    "unknown_value2",
)
CARD_DETAIL_SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "発行情報",
        (
            ("所有者名", "owner_name"),
            ("所有者電話番号", "owner_phone_hex"),
            ("所有者年齢", "owner_age_code"),
            ("所有者生年月日", "owner_birthdate"),
            ("第二発行ID", "secondary_issue_id"),
            ("発行者ID", "issuer_id"),
            ("デポジット額", "deposit"),
            ("発行機器", "issued_by"),
            ("発行駅", "issued_station"),
            ("発行日", "issued_at"),
            ("有効期限", "expires_at"),
        ),
    ),
    (
        "最終チャージ情報",
        (
            ("チャージ機器", "last_topup_equipment"),
            ("チャージ駅", "last_topup_station"),
            ("チャージ金額", "last_topup_amount"),
        ),
    ),
)
ATTRIBUTE_DETAIL_FIELDS: tuple[tuple[str, str], ...] = (
    ("カード種別", "card_type"),
    ("地域", "region_display"),
    ("残高", "attribute_balance"),
    ("取引通番", "attribute_transaction_number"),
)
MISC_DETAIL_FIELDS: tuple[tuple[str, str], ...] = (
    ("不明な残高", "unknown_balance"),
    ("不明な日付", "unknown_date"),
    ("不明な取引通番", "unknown_transaction_number"),
)
HISTORY_FILTER_FIELDS: tuple[str, ...] = (
    "recorded_on",
    "transaction_type",
    "pay_type",
    "gate_instruction_type",
    "entry_station",
    "exit_station",
    "recorded_by",
)

# heading text -> (entry key, is_numeric) used by the sortable Treeview columns.
HISTORY_SORT_KEYS: dict[str, tuple[str, bool]] = {
    "日時": ("recorded_on", False),
    "取引種別": ("transaction_type", False),
    "支払種別": ("pay_type", False),
    "改札処理": ("gate_instruction_type", False),
    "入場駅": ("entry_station", False),
    "出場駅": ("exit_station", False),
    "差額": ("delta", True),
    "残高": ("balance", True),
    "機器": ("recorded_by", False),
    "通番": ("transaction_number", True),
}
GATE_SORT_KEYS: dict[str, tuple[str, bool]] = {
    "日時": ("date", False),
    "入出場種別": ("gate_in_out_type", False),
    "中間処理": ("intermediate_gate_instruction_type", False),
    "駅": ("station", False),
    "装置番号": ("device_id_hex", False),
    "金額": ("amount", True),
    "定期運賃": ("commuter_pass_fee", True),
    "定期駅": ("commuter_station", False),
}

# CSV export layout for the transaction history.
HISTORY_CSV_COLUMNS: tuple[tuple[str, str], ...] = (
    ("日付", "recorded_on"),
    ("時刻", "transaction_time"),
    ("取引種別", "transaction_type"),
    ("支払種別", "pay_type"),
    ("改札処理", "gate_instruction_type"),
    ("入場駅", "entry_station"),
    ("出場駅", "exit_station"),
    ("差額", "delta"),
    ("残高", "balance"),
    ("機器", "recorded_by"),
    ("通番", "transaction_number"),
)

LIGHT_THEME: dict[str, str] = {
    "bg": "#f3f4f8",
    "surface": "#ffffff",
    "border": "#d1d5db",
    "text": "#111827",
    "text_muted": "#6b7280",
    "heading": "#1f2937",
    "hero_bg": "#4c6ef5",
    "hero_fg": "#ffffff",
    "hero_sub": "#dbe4ff",
    "tree_even": "#ffffff",
    "tree_odd": "#f5f7fb",
    "tree_sel_bg": "#e0ecff",
    "tree_sel_fg": "#000000",
    "charge_fg": "#0f7b3f",
    "heading_bg": "#eef1f7",
    "progress_trough": "#dbe1ef",
    "progress_bar": "#4c6ef5",
    "tab_bg": "#f3f4f8",
    "tab_sel_bg": "#ffffff",
    "tab_sel_fg": "#111827",
    "tab_fg": "#4b5563",
    "text_widget_bg": "#ffffff",
    "text_widget_fg": "#111827",
}
DARK_THEME: dict[str, str] = {
    "bg": "#1e1f26",
    "surface": "#2a2c36",
    "border": "#3f4250",
    "text": "#e5e7eb",
    "text_muted": "#9ca3af",
    "heading": "#f3f4f6",
    "hero_bg": "#3b4bbf",
    "hero_fg": "#ffffff",
    "hero_sub": "#c7d0ff",
    "tree_even": "#2a2c36",
    "tree_odd": "#31333f",
    "tree_sel_bg": "#3d4b7a",
    "tree_sel_fg": "#ffffff",
    "charge_fg": "#4ade80",
    "heading_bg": "#31333f",
    "progress_trough": "#3f4250",
    "progress_bar": "#7c93ff",
    "tab_bg": "#1e1f26",
    "tab_sel_bg": "#2a2c36",
    "tab_sel_fg": "#ffffff",
    "tab_fg": "#9ca3af",
    "text_widget_bg": "#23252e",
    "text_widget_fg": "#e5e7eb",
}


@dataclass(frozen=True)
class TreeColumnSpec:
    heading: str
    width: int
    anchor: str | None = None


def _format_currency(value: Any) -> str:
    return format_yen(value) if isinstance(value, int) else "-"


def _format_integer(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else "-"


def _format_delta(value: Any) -> str:
    if not isinstance(value, int):
        return "-"
    if value > 0:
        return f"+{value:,} 円"
    return f"{value:,} 円"


def _format_hex_clock(value: Any) -> str:
    if isinstance(value, str) and len(value) >= 4:
        return f"{value[0:2]}:{value[2:4]}"
    return "-"


class SuicaGuiApp:
    """Tkinter-based GUI that shows Suica IC card information."""

    def __init__(self) -> None:
        self.dark_mode = False
        self.theme = LIGHT_THEME
        self.root = self._create_root_window()
        self._initialize_state()
        self._configure_base_style()
        self._load_station_data()
        self.scrollable_container = self._create_scrollable_container()
        self._build_ui()
        self._apply_theme()
        self._register_event_handlers()
        self._start_nfc_thread()

    def _create_root_window(self) -> tk.Tk:
        root = tk.Tk()
        root.title("Suica ビューア")
        root.geometry("1440x900")
        root.minsize(1024, 768)
        return root

    def _initialize_state(self) -> None:
        self.status_var = tk.StringVar(
            master=self.root, value="カードをかざしてください。"
        )
        self.last_updated_var = tk.StringVar(master=self.root, value="読取日時: —")
        self.theme_button_var = tk.StringVar(master=self.root, value="🌙 ダーク")
        self.progress_var = tk.DoubleVar(master=self.root, value=0.0)
        self.summary_vars = self._create_string_vars(SUMMARY_VAR_KEYS)
        self.hero_balance_var = tk.StringVar(master=self.root, value="—")
        self.hero_subtitle_var = tk.StringVar(master=self.root, value="カード未読取")
        self.history_filter_var = tk.StringVar(master=self.root)
        self.current_history: list[dict[str, Any]] = []
        self._history_view: list[dict[str, Any]] = []
        self._gate_view: list[dict[str, Any]] = []
        self._sort_state: dict[tuple[str, str], bool] = {}
        self.current_card_json = ""
        self.copy_details_button: ttk.Button | None = None
        self.export_details_button: ttk.Button | None = None
        self.export_csv_button: ttk.Button | None = None
        self.theme_button: ttk.Button | None = None
        self.history_filter_entry: ttk.Entry | None = None
        self.history_tree: ttk.Treeview | None = None
        self.gate_tree: ttk.Treeview | None = None
        self.current_gate_entries: list[dict[str, Any]] = []
        self.sf_gate_vars = self._create_string_vars(SF_GATE_VAR_KEYS)
        self.commuter_detail_vars = self._create_string_vars(COMMUTER_DETAIL_KEYS)
        self.card_detail_sections = CARD_DETAIL_SECTIONS
        card_keys = [
            key for _, fields in self.card_detail_sections for _, key in fields
        ]
        self.card_detail_vars = self._create_string_vars(card_keys)
        self.attribute_detail_fields = ATTRIBUTE_DETAIL_FIELDS
        attribute_keys = [key for _, key in self.attribute_detail_fields]
        self.attribute_detail_vars = self._create_string_vars(attribute_keys)
        self.misc_detail_fields = MISC_DETAIL_FIELDS
        misc_keys = [key for _, key in self.misc_detail_fields]
        self.misc_detail_vars = self._create_string_vars(misc_keys)
        self.server_url = resolve_server_url()
        self._remote_client: FelicaRemoteClient | None = None
        self.card_data_service: CardDataService | None = None
        self.progress_bar: ttk.Progressbar | None = None
        self.details_text: tk.Text | None = None

    def _create_string_vars(
        self,
        keys: Iterable[str],
        *,
        default: str = "-",
    ) -> dict[str, tk.StringVar]:
        return {key: tk.StringVar(master=self.root, value=default) for key in keys}

    @staticmethod
    def _reset_string_vars(mapping: dict[str, tk.StringVar], value: str = "-") -> None:
        for var in mapping.values():
            var.set(value)

    def _load_station_data(self) -> None:
        try:
            self.station_code_lookup = StationCodeLookup()
            self.card_data_service = CardDataService(self.station_code_lookup)
        except Exception as exc:
            messagebox.showerror(
                "駅データ読み込みエラー",
                f"station_codes.csv を読み込めませんでした: {exc}",
            )
            self.root.destroy()
            raise SystemExit(1) from exc

    def _register_event_handlers(self) -> None:
        self.root.bind("<Control-f>", self._focus_history_filter)
        self.root.bind("<Command-f>", self._focus_history_filter)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _get_remote_client(self, tag: FelicaStandard) -> FelicaRemoteClient:
        if self._remote_client is None:
            self._remote_client = FelicaRemoteClient(self.server_url, tag)
        else:
            self._remote_client.reset(tag)
        return self._remote_client

    def _start_nfc_thread(self) -> None:
        self.nfc_thread = threading.Thread(target=self._nfc_loop, daemon=True)
        self.nfc_thread.start()

    # ------------------------------------------------------------------ #
    # Styling / theming                                                  #
    # ------------------------------------------------------------------ #
    def _configure_base_style(self) -> None:
        """Configure theme-independent style bits (fonts, geometry)."""
        self.style = ttk.Style(self.root)
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass

        base_font = ("Helvetica", 12)
        self.root.option_add("*TLabel.font", base_font)
        self.root.option_add("*TButton.font", base_font)
        self.root.option_add("*Treeview.font", base_font)
        self.root.option_add("*TEntry.font", base_font)

        self.style.configure("SectionBody.TFrame", borderwidth=1, relief="solid")
        self.style.configure("Treeview", rowheight=28, borderwidth=0)
        self.style.configure("Treeview.Heading", font=("Helvetica", 13, "bold"))
        self.style.configure("Status.TLabel", font=("Helvetica", 16, "bold"))
        self.style.configure("SummaryKey.TLabel", font=("Helvetica", 12, "bold"))
        self.style.configure("SummaryValue.TLabel", font=("Helvetica", 12))
        self.style.configure("Meta.TLabel", font=("Helvetica", 11))
        self.style.configure("SectionMeta.TLabel", font=("Helvetica", 11))
        self.style.configure("SectionHeader.TLabel", font=("Helvetica", 13, "bold"))
        self.style.configure("SubsectionHeader.TLabel", font=("Helvetica", 12, "bold"))
        self.style.configure("HeroCaption.TLabel", font=("Helvetica", 12, "bold"))
        self.style.configure("HeroBalance.TLabel", font=("Helvetica", 34, "bold"))
        self.style.configure("HeroSub.TLabel", font=("Helvetica", 13))
        self.style.configure("TNotebook", borderwidth=0)
        self.style.configure("TNotebook.Tab", padding=(14, 7), font=("Helvetica", 12))

    def _apply_theme(self) -> None:
        """Apply the current palette to every styled and raw widget."""
        theme = self.theme
        style = self.style

        self.root.configure(bg=theme["bg"])
        for name in (
            "Main.TFrame",
            "SectionWrapper.TFrame",
        ):
            style.configure(name, background=theme["bg"])
        style.configure(
            "SectionBody.TFrame",
            background=theme["surface"],
            bordercolor=theme["border"],
        )
        style.configure("SectionInner.TFrame", background=theme["surface"])
        style.configure("Hero.TFrame", background=theme["hero_bg"])

        style.configure(
            "Treeview",
            background=theme["surface"],
            fieldbackground=theme["surface"],
            foreground=theme["text"],
        )
        style.configure(
            "Treeview.Heading",
            background=theme["heading_bg"],
            foreground=theme["heading"],
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", theme["tree_sel_bg"])],
            foreground=[("selected", theme["tree_sel_fg"])],
        )

        style.configure(
            "Status.TLabel", background=theme["bg"], foreground=theme["heading"]
        )
        style.configure(
            "SummaryKey.TLabel",
            background=theme["surface"],
            foreground=theme["text_muted"],
        )
        style.configure(
            "SummaryValue.TLabel",
            background=theme["surface"],
            foreground=theme["text"],
        )
        style.configure(
            "Meta.TLabel", background=theme["bg"], foreground=theme["text_muted"]
        )
        style.configure(
            "SectionMeta.TLabel",
            background=theme["surface"],
            foreground=theme["text_muted"],
        )
        style.configure(
            "SectionHeader.TLabel",
            background=theme["bg"],
            foreground=theme["heading"],
        )
        style.configure(
            "SubsectionHeader.TLabel",
            background=theme["surface"],
            foreground=theme["heading"],
        )
        style.configure(
            "HeroCaption.TLabel",
            background=theme["hero_bg"],
            foreground=theme["hero_sub"],
        )
        style.configure(
            "HeroBalance.TLabel",
            background=theme["hero_bg"],
            foreground=theme["hero_fg"],
        )
        style.configure(
            "HeroSub.TLabel",
            background=theme["hero_bg"],
            foreground=theme["hero_sub"],
        )
        style.configure("TNotebook", background=theme["bg"])
        style.map(
            "TNotebook.Tab",
            background=[
                ("selected", theme["tab_sel_bg"]),
                ("!selected", theme["tab_bg"]),
            ],
            foreground=[
                ("selected", theme["tab_sel_fg"]),
                ("!selected", theme["tab_fg"]),
            ],
        )
        style.configure(
            "Status.Horizontal.TProgressbar",
            troughcolor=theme["progress_trough"],
            background=theme["progress_bar"],
            bordercolor=theme["progress_trough"],
        )

        if hasattr(self, "_scroll_canvas"):
            self._scroll_canvas.configure(background=theme["bg"])
        self._configure_tree_tags()
        if self.details_text is not None:
            self.details_text.configure(
                background=theme["text_widget_bg"],
                foreground=theme["text_widget_fg"],
                insertbackground=theme["text_widget_fg"],
            )

    def _configure_tree_tags(self) -> None:
        theme = self.theme
        for tree in (self.history_tree, self.gate_tree):
            if tree is None:
                continue
            tree.tag_configure("even", background=theme["tree_even"])
            tree.tag_configure("odd", background=theme["tree_odd"])
            tree.tag_configure(
                "even_charge",
                background=theme["tree_even"],
                foreground=theme["charge_fg"],
            )
            tree.tag_configure(
                "odd_charge",
                background=theme["tree_odd"],
                foreground=theme["charge_fg"],
            )

    def _toggle_theme(self) -> None:
        self.dark_mode = not self.dark_mode
        self.theme = DARK_THEME if self.dark_mode else LIGHT_THEME
        self.theme_button_var.set("☀ ライト" if self.dark_mode else "🌙 ダーク")
        self._apply_theme()

    def _create_scrollable_container(self) -> ttk.Frame:
        container = ttk.Frame(self.root, style="Main.TFrame")
        container.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(container, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        content_frame = ttk.Frame(canvas, style="Main.TFrame")
        window_id = canvas.create_window((0, 0), window=content_frame, anchor="nw")

        content_frame.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )

        def _on_mousewheel(event: Any) -> None:
            delta = 0
            if hasattr(event, "delta") and event.delta:
                delta = event.delta
            elif getattr(event, "num", None) == 4:
                delta = 120
            elif getattr(event, "num", None) == 5:
                delta = -120

            if delta > 0:
                canvas.yview_scroll(-1, "units")
            elif delta < 0:
                canvas.yview_scroll(1, "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        canvas.bind_all("<Button-4>", _on_mousewheel)
        canvas.bind_all("<Button-5>", _on_mousewheel)

        self._scroll_canvas = canvas
        return content_frame

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(
            self.scrollable_container, padding=24, style="Main.TFrame"
        )
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(main_frame, padding=(0, 0, 0, 16), style="Main.TFrame")
        header_frame.pack(fill=tk.X)
        header_frame.columnconfigure(0, weight=1)
        header_frame.columnconfigure(1, weight=0)

        status_label = ttk.Label(
            header_frame,
            textvariable=self.status_var,
            style="Status.TLabel",
            anchor="w",
        )
        status_label.grid(row=0, column=0, sticky="w")

        header_controls = ttk.Frame(header_frame, style="Main.TFrame")
        header_controls.grid(row=0, column=1, sticky="e", padx=(16, 0))
        ttk.Label(
            header_controls,
            textvariable=self.last_updated_var,
            style="Meta.TLabel",
            anchor="e",
        ).pack(side=tk.LEFT, padx=(0, 12))
        self.theme_button = ttk.Button(
            header_controls,
            textvariable=self.theme_button_var,
            command=self._toggle_theme,
            width=10,
        )
        self.theme_button.pack(side=tk.LEFT)

        self.progress_bar = ttk.Progressbar(
            header_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
            style="Status.Horizontal.TProgressbar",
        )
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        ttk.Separator(main_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 16))

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        overview_frame = ttk.Frame(notebook, padding=16, style="Main.TFrame")
        notebook.add(overview_frame, text="概要")

        card_frame = ttk.Frame(notebook, padding=16, style="Main.TFrame")
        notebook.add(card_frame, text="カード情報")

        history_frame = ttk.Frame(notebook, padding=16, style="Main.TFrame")
        notebook.add(history_frame, text="取引履歴")

        gate_frame = ttk.Frame(notebook, padding=16, style="Main.TFrame")
        notebook.add(gate_frame, text="改札")

        data_frame = ttk.Frame(notebook, padding=16, style="Main.TFrame")
        notebook.add(data_frame, text="データ")

        self._build_overview_tab(overview_frame)
        self._build_card_tab(card_frame)
        self._build_history_tab(history_frame)
        self._build_gate_tab(gate_frame)
        self._build_data_tab(data_frame)

    def _build_hero(self, parent: ttk.Frame) -> None:
        hero = ttk.Frame(parent, style="Hero.TFrame", padding=(24, 20, 24, 20))
        hero.pack(fill=tk.X, padx=4, pady=(0, 16))
        ttk.Label(hero, text="残高", style="HeroCaption.TLabel").pack(anchor="w")
        ttk.Label(
            hero, textvariable=self.hero_balance_var, style="HeroBalance.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            hero, textvariable=self.hero_subtitle_var, style="HeroSub.TLabel"
        ).pack(anchor="w", pady=(6, 0))

    def _populate_label_value_grid(
        self,
        frame: tk.Widget,
        items: Iterable[tuple[str, str]],
        variables: dict[str, tk.StringVar],
        *,
        label_width: int | None,
        wraplength: int = 900,
        padx: tuple[int, int] = (0, 12),
        pady: int = 4,
        label_style: str = "SummaryKey.TLabel",
        value_style: str = "SummaryValue.TLabel",
    ) -> None:
        for row, (label_text, key) in enumerate(items):
            label_kwargs: dict[str, Any] = {
                "text": f"{label_text}:",
                "anchor": "e",
                "style": label_style,
            }
            if label_width is not None:
                label_kwargs["width"] = label_width
            ttk.Label(frame, **label_kwargs).grid(
                row=row, column=0, sticky="e", pady=pady, padx=padx
            )
            ttk.Label(
                frame,
                textvariable=variables[key],
                style=value_style,
                anchor="w",
                wraplength=wraplength,
            ).grid(row=row, column=1, sticky="w", pady=pady)

    def _create_section(
        self,
        parent: tk.Widget,
        title: str,
        *,
        padding: int | tuple[int, int, int, int] = 12,
        margin: tuple[int, int] = (0, 16),
        fill: Literal["none", "x", "y", "both"] = "x",
        expand: bool = False,
        variant: Literal["primary", "embedded"] = "primary",
    ) -> ttk.Frame:
        if variant == "embedded":
            wrapper_style = "SectionInner.TFrame"
            header_style = "SubsectionHeader.TLabel"
            pack_kwargs: dict[str, Any] = {"pady": margin}
        else:
            wrapper_style = "SectionWrapper.TFrame"
            header_style = "SectionHeader.TLabel"
            pack_kwargs = {"pady": margin, "padx": 4}

        section_wrapper = ttk.Frame(parent, style=wrapper_style)
        section_wrapper.pack(fill=fill, expand=expand, **pack_kwargs)

        header_row = ttk.Frame(section_wrapper, style=wrapper_style)
        header_row.pack(fill=tk.X)
        ttk.Label(header_row, text=title, style=header_style).pack(side=tk.LEFT)

        if isinstance(padding, tuple):
            padding_values = padding
        else:
            padding_values = (padding, padding, padding, padding)

        content = ttk.Frame(
            section_wrapper,
            padding=padding_values,
            style="SectionBody.TFrame",
        )
        content.pack(fill=fill, expand=expand, pady=(6, 0))
        return content

    def _create_treeview(
        self,
        parent: ttk.Frame,
        column_specs: Iterable[TreeColumnSpec],
        *,
        on_sort: Callable[[str], None] | None = None,
    ) -> ttk.Treeview:
        specs = list(column_specs)
        column_ids = [spec.heading for spec in specs]
        tree = ttk.Treeview(
            parent, columns=column_ids, show="headings", selectmode="browse"
        )
        for spec in specs:
            heading_kwargs: dict[str, Any] = {"text": spec.heading}
            if on_sort is not None:
                heading_kwargs["command"] = lambda c=spec.heading: on_sort(c)
            tree.heading(spec.heading, **heading_kwargs)
            column_kwargs: dict[str, Any] = {"width": spec.width}
            if spec.anchor:
                column_kwargs["anchor"] = spec.anchor
            tree.column(spec.heading, **column_kwargs)

        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
        return tree

    def _build_overview_tab(self, frame: ttk.Frame) -> None:
        self._build_hero(frame)

        sections = [
            (
                "カード識別",
                [
                    ("IDm", "idm"),
                    ("PMm", "pmm"),
                    ("IDi", "idi"),
                    ("PMi", "pmi"),
                    ("カード種別", "card_type"),
                    ("発行者", "issuer"),
                ],
            ),
            (
                "利用サマリ",
                [
                    ("残高", "balance"),
                    ("最終チャージ金額", "last_topup_amount"),
                    ("取引通番", "transaction_number"),
                ],
            ),
            (
                "発行・有効情報",
                [
                    ("発行日", "issued_at"),
                    ("有効期限", "expires_at"),
                    ("発行駅", "issued_station"),
                ],
            ),
            (
                "定期券ハイライト",
                [
                    ("区間", "commuter_pass"),
                    ("有効期間", "commuter_period"),
                ],
            ),
        ]

        for title, items in sections:
            section_frame = self._create_section(
                frame,
                title,
                padding=(12, 8, 12, 8),
                margin=(0, 12),
            )
            section_frame.columnconfigure(1, weight=1)
            self._populate_label_value_grid(
                section_frame,
                items,
                self.summary_vars,
                label_width=None,
                wraplength=640,
                label_style="SummaryKey.TLabel",
                value_style="SummaryValue.TLabel",
            )

    def _build_card_tab(self, frame: ttk.Frame) -> None:
        for section_title, fields in self.card_detail_sections:
            section_frame = self._create_section(
                frame,
                section_title,
                padding=(12, 8, 12, 8),
                margin=(0, 12),
            )
            section_frame.columnconfigure(1, weight=1)
            self._populate_label_value_grid(
                section_frame,
                fields,
                self.card_detail_vars,
                label_width=16,
                wraplength=660,
            )

        attribute_section = self._create_section(
            frame,
            "カード属性",
            padding=(12, 8, 12, 8),
            margin=(0, 12),
        )
        attribute_section.columnconfigure(1, weight=1)
        self._populate_label_value_grid(
            attribute_section,
            self.attribute_detail_fields,
            self.attribute_detail_vars,
            label_width=16,
            wraplength=660,
        )

        commuter_section = self._create_section(
            frame,
            "定期券情報",
            padding=(12, 8, 12, 8),
            margin=(0, 12),
        )
        commuter_section.columnconfigure(1, weight=1)

        commuter_labels = [
            ("開始日", "valid_from"),
            ("終了日", "valid_to"),
            ("始点駅", "start_station"),
            ("終点駅", "end_station"),
            ("経由駅1", "via1"),
            ("経由駅2", "via2"),
            ("発行日", "issued_at"),
        ]

        self._populate_label_value_grid(
            commuter_section,
            commuter_labels,
            self.commuter_detail_vars,
            label_width=12,
            wraplength=640,
        )

    def _build_history_tab(self, frame: ttk.Frame) -> None:
        search_frame = ttk.Frame(frame, padding=(0, 0, 0, 8), style="Main.TFrame")
        search_frame.pack(fill=tk.X, pady=(0, 12))
        search_frame.columnconfigure(1, weight=1)

        ttk.Label(search_frame, text="フィルター", style="Meta.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        filter_entry = ttk.Entry(
            search_frame,
            textvariable=self.history_filter_var,
        )
        filter_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.history_filter_entry = filter_entry
        ttk.Button(
            search_frame,
            text="クリア",
            command=self._clear_history_filter,
        ).grid(row=0, column=2, sticky="e")

        history_container = self._create_section(
            frame,
            "取引履歴（列見出しクリックで並び替え）",
            padding=(4, 4, 4, 4),
            margin=(0, 0),
            fill="both",
            expand=True,
        )

        history_columns = [
            TreeColumnSpec("日時", 190),
            TreeColumnSpec("取引種別", 160),
            TreeColumnSpec("支払種別", 180),
            TreeColumnSpec("改札処理", 180),
            TreeColumnSpec("入場駅", 240),
            TreeColumnSpec("出場駅", 240),
            TreeColumnSpec("差額", 120, "e"),
            TreeColumnSpec("残高", 120, "e"),
            TreeColumnSpec("機器", 170),
            TreeColumnSpec("通番", 110, "e"),
        ]
        self.history_tree = self._create_treeview(
            history_container,
            history_columns,
            on_sort=self._sort_history,
        )

        self.history_filter_var.trace_add("write", self._apply_history_filter)

    def _build_gate_tab(self, frame: ttk.Frame) -> None:
        gate_container = self._create_section(
            frame,
            "改札入出場履歴（列見出しクリックで並び替え）",
            padding=(4, 4, 4, 4),
            margin=(0, 12),
            fill="both",
            expand=True,
        )

        gate_columns = [
            TreeColumnSpec("日時", 200),
            TreeColumnSpec("入出場種別", 200),
            TreeColumnSpec("中間処理", 200),
            TreeColumnSpec("駅", 280),
            TreeColumnSpec("装置番号", 140, "center"),
            TreeColumnSpec("金額", 140, "e"),
            TreeColumnSpec("定期運賃", 140, "e"),
            TreeColumnSpec("定期駅", 200),
        ]
        self.gate_tree = self._create_treeview(
            gate_container,
            gate_columns,
            on_sort=self._sort_gate,
        )

        sf_frame = self._create_section(
            frame,
            "SF改札入場情報",
            padding=(12, 8, 12, 8),
            margin=(0, 12),
        )
        sf_frame.columnconfigure(1, weight=1)

        sf_labels = [
            ("入場駅", "entry_station"),
            ("中間改札入場駅", "intermediate_entry"),
            ("中間改札入場日付", "intermediate_entry_date"),
            ("中間改札入場時刻", "intermediate_entry_time"),
            ("中間改札出場駅", "intermediate_exit"),
            ("中間改札出場時刻", "intermediate_exit_time"),
            ("不明値1", "unknown_value1"),
            ("不明値2", "unknown_value2"),
        ]

        self._populate_label_value_grid(
            sf_frame,
            sf_labels,
            self.sf_gate_vars,
            label_width=14,
            wraplength=460,
            padx=(0, 8),
            pady=2,
        )

    def _build_data_tab(self, frame: ttk.Frame) -> None:
        self._build_misc_tab(frame)
        self._build_details_tab(frame)

    def _build_misc_tab(self, frame: ttk.Frame) -> None:
        misc_container = self._create_section(
            frame,
            "不明な情報",
            padding=(12, 8, 12, 8),
            margin=(0, 12),
        )
        misc_container.columnconfigure(1, weight=1)

        self._populate_label_value_grid(
            misc_container,
            self.misc_detail_fields,
            self.misc_detail_vars,
            label_width=14,
        )

    def _build_details_tab(self, frame: ttk.Frame) -> None:
        details_container = self._create_section(
            frame,
            "カード情報 JSON",
            padding=(12, 12, 12, 12),
            margin=(0, 12),
            fill="both",
            expand=True,
        )

        toolbar = ttk.Frame(details_container, style="SectionInner.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(toolbar, text="操作", style="SectionMeta.TLabel").pack(side=tk.LEFT)

        button_row = ttk.Frame(toolbar, style="SectionInner.TFrame")
        button_row.pack(side=tk.RIGHT)

        self.copy_details_button = ttk.Button(
            button_row,
            text="JSONをコピー",
            command=self._copy_details_to_clipboard,
            state=tk.DISABLED,
        )
        self.copy_details_button.pack(side=tk.LEFT)

        self.export_details_button = ttk.Button(
            button_row,
            text="JSONを書き出し…",
            command=self._export_details_to_file,
            state=tk.DISABLED,
        )
        self.export_details_button.pack(side=tk.LEFT, padx=(8, 0))

        self.export_csv_button = ttk.Button(
            button_row,
            text="履歴をCSVで書き出し…",
            command=self._export_history_to_csv,
            state=tk.DISABLED,
        )
        self.export_csv_button.pack(side=tk.LEFT, padx=(8, 0))

        text_container = ttk.Frame(details_container, style="SectionInner.TFrame")
        text_container.pack(fill=tk.BOTH, expand=True)
        text_container.columnconfigure(0, weight=1)
        text_container.rowconfigure(0, weight=1)

        self.details_text = tk.Text(
            text_container, wrap=tk.NONE, borderwidth=0, highlightthickness=0
        )
        self.details_text.configure(state=tk.DISABLED, font=("TkFixedFont", 11))

        y_scroll = ttk.Scrollbar(
            text_container, orient=tk.VERTICAL, command=self.details_text.yview
        )
        x_scroll = ttk.Scrollbar(
            text_container, orient=tk.HORIZONTAL, command=self.details_text.xview
        )
        self.details_text.configure(
            xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set
        )

        self.details_text.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

    def _copy_details_to_clipboard(self) -> None:
        if not self.current_card_json:
            messagebox.showinfo("カード情報なし", "カード情報が読み込まれていません。")
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(self.current_card_json)
        self.root.update_idletasks()
        self._update_status("カード詳細をクリップボードにコピーしました。")

    def _export_details_to_file(self) -> None:
        if not self.current_card_json:
            messagebox.showinfo("カード情報なし", "カード情報が読み込まれていません。")
            return

        file_path = filedialog.asksaveasfilename(
            title="カード情報を書き出し",
            defaultextension=".json",
            filetypes=[
                ("JSON ファイル", "*.json"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as output_file:
                output_file.write(self.current_card_json)
        except OSError as exc:
            messagebox.showerror(
                "書き出しエラー", f"ファイルに保存できませんでした: {exc}"
            )
            return

        self._update_status(f"カード情報を書き出しました: {file_path}")

    def _export_history_to_csv(self) -> None:
        if not self.current_history:
            messagebox.showinfo("履歴なし", "取引履歴が読み込まれていません。")
            return

        file_path = filedialog.asksaveasfilename(
            title="取引履歴をCSVで書き出し",
            defaultextension=".csv",
            filetypes=[
                ("CSV ファイル", "*.csv"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if not file_path:
            return

        try:
            # utf-8-sig so Excel opens Japanese text without mojibake.
            with open(file_path, "w", encoding="utf-8-sig", newline="") as output_file:
                writer = csv.writer(output_file)
                writer.writerow([header for header, _ in HISTORY_CSV_COLUMNS])
                for entry in self.current_history:
                    writer.writerow(
                        [
                            self._csv_cell(entry.get(key))
                            for _, key in HISTORY_CSV_COLUMNS
                        ]
                    )
        except OSError as exc:
            messagebox.showerror(
                "書き出しエラー", f"ファイルに保存できませんでした: {exc}"
            )
            return

        self._update_status(f"取引履歴を書き出しました: {file_path}")

    @staticmethod
    def _csv_cell(value: Any) -> str:
        if value is None:
            return ""
        return str(value)

    def _clear_history_filter(self) -> None:
        if self.history_filter_var.get():
            self.history_filter_var.set("")
        else:
            self._apply_history_filter()

    def _apply_history_filter(self, *_: Any) -> None:
        tree = self.history_tree
        if tree is None:
            return
        if not tree.get_children() and not self.current_history:
            return

        query = self.history_filter_var.get().strip().lower()
        if not self.current_history:
            tree.delete(*tree.get_children())
            return

        if not query:
            self._render_history_rows(self.current_history)
            return

        filtered = [
            entry
            for entry in self.current_history
            if any(
                query in str(entry.get(field, "")).lower()
                for field in HISTORY_FILTER_FIELDS
            )
            or query in str(entry.get("transaction_time", "")).lower()
            or query in str(entry.get("balance", "")).lower()
            or query in str(entry.get("transaction_number", "")).lower()
        ]
        self._render_history_rows(filtered)

    def _render_history_rows(self, rows: list[dict[str, Any]]) -> None:
        if self.history_tree is None:
            return

        # Keep a private copy so column sorting reorders the view without
        # mutating the canonical card-order list (used for CSV export).
        self._history_view = list(rows)
        self.history_tree.delete(*self.history_tree.get_children())

        for index, entry in enumerate(self._history_view):
            entry_station = entry.get("entry_station", "-")
            exit_station = entry.get("exit_station", "-")
            if entry.get("transaction_type_code") == 0x46:
                entry_station = "—"
                exit_station = "—"

            transaction_number_display = _format_integer(
                entry.get("transaction_number")
            )

            delta = entry.get("delta")
            values = (
                f"{entry['recorded_on']} {entry.get('transaction_time', '')}".strip(),
                entry.get("transaction_type", "-"),
                entry.get("pay_type", "-"),
                entry.get("gate_instruction_type", "-"),
                entry_station,
                exit_station,
                _format_delta(delta),
                _format_currency(entry.get("balance")),
                entry.get("recorded_by", "-"),
                transaction_number_display,
            )
            zebra = "odd" if index % 2 else "even"
            tag = f"{zebra}_charge" if isinstance(delta, int) and delta > 0 else zebra
            self.history_tree.insert("", tk.END, values=values, tags=(tag,))

    def _sort_history(self, column: str) -> None:
        spec = HISTORY_SORT_KEYS.get(column)
        if spec is None or not self._history_view:
            return
        key, numeric = spec
        reverse = self._next_sort_direction("history", column)
        self._history_view.sort(
            key=lambda entry: _sort_value(entry, key, numeric), reverse=reverse
        )
        self._render_history_rows(self._history_view)

    def _sort_gate(self, column: str) -> None:
        spec = GATE_SORT_KEYS.get(column)
        if spec is None or not self._gate_view:
            return
        key, numeric = spec
        reverse = self._next_sort_direction("gate", column)
        self._gate_view.sort(
            key=lambda entry: _sort_value(entry, key, numeric), reverse=reverse
        )
        self._render_gate_rows(self._gate_view)

    def _next_sort_direction(self, tree_name: str, column: str) -> bool:
        state_key = (tree_name, column)
        reverse = not self._sort_state.get(state_key, False)
        self._sort_state[state_key] = reverse
        return reverse

    def _focus_history_filter(self, event: Any | None = None) -> str | None:
        if self.history_filter_entry is None:
            return None

        self.history_filter_entry.focus_set()
        self.history_filter_entry.selection_range(0, tk.END)
        return "break"

    def _nfc_loop(self) -> None:
        self._reset_progress()
        self._update_status("NFC リーダーを初期化しています…")

        try:
            with nfc.ContactlessFrontend("usb") as clf:
                self._update_status("カードをかざしてください。")
                self._reset_progress()
                while True:
                    try:
                        clf.connect(
                            rdwr={
                                "targets": ["212F", "424F"],
                                "on-connect": self._on_connect,
                                "on-release": self._on_release,
                            }
                        )
                    except Exception as exc:
                        self._reset_progress()
                        self._update_status(f"読み取りエラー: {exc}")
        # Catch everything: this runs in a daemon thread, so an escaping exception
        # kills it silently and the UI waits for a reader that will never arrive.
        # usb1's USBError is not an OSError, so `except IOError` misses it.
        except Exception as exc:
            self._reset_progress()
            self._update_status(f"NFC リーダーを初期化できません: {exc}")
            self._show_error(
                "NFC リーダーを初期化できません", describe_reader_error(exc)
            )

    def _on_connect(self, tag: Tag) -> bool:
        self._reset_progress()
        if not isinstance(tag, FelicaStandard):
            self._update_status("FeliCa 以外のタグを検出しました。")
            return True

        self._update_status("カード情報を取得しています…")
        self._set_progress(5.0)

        try:
            card_data = self._collect_card_data(tag)
        except FelicaRemoteClientError as exc:
            self._reset_progress()
            self._update_status(f"サーバ通信エラー: {exc}")
            return True
        except Exception as exc:
            self._reset_progress()
            self._update_status(f"カード情報の取得に失敗しました: {exc}")
            return True

        self.root.after(0, self._apply_card_data, card_data)
        return True

    def _on_release(self, tag: Tag) -> bool:
        self.root.after(0, self._handle_card_removed)
        return True

    def _collect_card_data(self, tag: FelicaStandard) -> CardData:
        polling_result = tag.polling(SYSTEM_CODE)
        if len(polling_result) != 2:
            raise RuntimeError("Polling 応答が不正です。")
        tag.idm, tag.pmm = polling_result
        self._set_progress(15.0)

        client = self._get_remote_client(tag)
        if self.card_data_service is None:
            raise RuntimeError("カードデータサービスが初期化されていません。")

        return self.card_data_service.collect(
            client,
            progress_callback=self._set_progress,
        )

    def _format_region(self, region_code: Any) -> str:
        if isinstance(region_code, int):
            return format_region(region_code)
        return "-"

    def _update_summary(
        self,
        system_info: SystemInfo,
        issue_primary: dict[str, Any],
        last_topup: dict[str, Any],
        attribute_info: dict[str, Any],
        commuter_info: dict[str, Any],
    ) -> None:
        topup_info = last_topup or {}
        self.summary_vars["idi"].set(system_info.idi_display)
        self.summary_vars["pmi"].set(system_info.pmi)
        self.summary_vars["idm"].set(system_info.idm_hex)
        self.summary_vars["pmm"].set(system_info.pmm_hex)
        card_type = attribute_info.get("card_type", "-")
        issuer = issue_primary.get("issuer_id", "-")
        self.summary_vars["card_type"].set(card_type)
        self.summary_vars["issuer"].set(issuer)
        balance_display = _format_currency(attribute_info.get("balance"))
        self.summary_vars["balance"].set(balance_display)
        self.summary_vars["last_topup_amount"].set(
            _format_currency(topup_info.get("amount"))
        )
        self.summary_vars["issued_at"].set(issue_primary.get("issued_at", "-"))
        self.summary_vars["expires_at"].set(issue_primary.get("expires_at", "-"))
        self.summary_vars["issued_station"].set(
            issue_primary.get("issued_station", "-")
        )
        self.summary_vars["transaction_number"].set(
            _format_integer(attribute_info.get("transaction_number"))
        )

        # Hero card
        self.hero_balance_var.set(balance_display)
        subtitle_parts = [part for part in (card_type, issuer) if part and part != "-"]
        self.hero_subtitle_var.set(" · ".join(subtitle_parts) or "カード読取済み")

        start_station = commuter_info.get("start_station")
        end_station = commuter_info.get("end_station")
        if start_station and end_station:
            commuter_summary = f"{start_station} → {end_station}"
        else:
            commuter_summary = "-"
        self.summary_vars["commuter_pass"].set(commuter_summary)

        valid_from = commuter_info.get("valid_from")
        valid_to = commuter_info.get("valid_to")
        if valid_from and valid_to:
            commuter_period = f"{valid_from} 〜 {valid_to}"
        else:
            commuter_period = "-"
        self.summary_vars["commuter_period"].set(commuter_period)

    def _update_commuter_details(self, commuter_info: dict[str, Any]) -> None:
        field_mapping = {
            "valid_from": "valid_from",
            "valid_to": "valid_to",
            "start_station": "start_station",
            "end_station": "end_station",
            "via1": "via1_station",
            "via2": "via2_station",
            "issued_at": "issued_at",
        }
        for target_key, source_key in field_mapping.items():
            value = commuter_info.get(source_key)
            display = "-" if value in (None, "") else str(value)
            self.commuter_detail_vars[target_key].set(display)

    def _apply_card_data(self, card_data: CardData) -> None:
        system_info = card_data.system
        issue_primary = card_data.issue_primary
        last_topup = card_data.last_topup
        attribute_info = card_data.attribute
        commuter_info = card_data.commuter

        self._update_summary(
            system_info,
            issue_primary,
            last_topup,
            attribute_info,
            commuter_info,
        )
        self._update_commuter_details(commuter_info)
        self._populate_card_details(
            issue_primary,
            last_topup,
            attribute_info,
            card_data.unknown,
        )
        self._populate_history(card_data.transaction_history)
        self._populate_gate_info(card_data.gate, card_data.sf_gate)
        self._populate_details(card_data)
        self._finalize_card_update()

    def _populate_card_details(
        self,
        issue_primary: dict[str, Any],
        last_topup: dict[str, Any],
        attribute_info: dict[str, Any],
        unknown_info: dict[str, Any],
    ) -> None:
        topup_info = last_topup or {}
        region_display = self._format_region(attribute_info.get("region"))
        attribute_txn_display = _format_integer(
            attribute_info.get("transaction_number")
        )
        unknown_balance_display = _format_currency(unknown_info.get("balance"))
        unknown_txn_display = _format_integer(unknown_info.get("transaction_number"))

        detail_values: dict[str, Any] = {
            "owner_name": issue_primary.get("owner_name", "-"),
            "owner_phone_hex": issue_primary.get("owner_phone_hex", "-"),
            "owner_age_code": issue_primary.get("owner_age_code", "-"),
            "owner_birthdate": issue_primary.get("owner_birthdate", "-"),
            "secondary_issue_id": issue_primary.get("secondary_issue_id", "-"),
            "issuer_id": issue_primary.get("issuer_id", "-"),
            "deposit": _format_currency(issue_primary.get("deposit")),
            "issued_by": issue_primary.get("issued_by", "-"),
            "issued_station": issue_primary.get("issued_station", "-"),
            "issued_at": issue_primary.get("issued_at", "-"),
            "expires_at": issue_primary.get("expires_at", "-"),
            "last_topup_equipment": topup_info.get("equipment", "-"),
            "last_topup_station": topup_info.get("station", "-"),
            "last_topup_amount": _format_currency(topup_info.get("amount")),
            "card_type": attribute_info.get("card_type", "-"),
            "region_display": region_display,
            "attribute_transaction_number": attribute_txn_display,
            "attribute_balance": _format_currency(attribute_info.get("balance")),
        }

        for _, fields in self.card_detail_sections:
            for _, key in fields:
                self.card_detail_vars[key].set(detail_values.get(key, "-"))

        for _, key in self.attribute_detail_fields:
            self.attribute_detail_vars[key].set(detail_values.get(key, "-"))

        self.misc_detail_vars["unknown_balance"].set(unknown_balance_display)
        self.misc_detail_vars["unknown_date"].set(unknown_info.get("date", "-"))
        self.misc_detail_vars["unknown_transaction_number"].set(unknown_txn_display)

    def _populate_gate_info(
        self,
        gate_entries: list[dict[str, Any]],
        sf_gate_info: dict[str, Any],
    ) -> None:
        if self.gate_tree is None:
            return

        self.current_gate_entries = gate_entries
        self._render_gate_rows(gate_entries)
        if sf_gate_info is None:
            sf_gate_info = {}

        self.sf_gate_vars["entry_station"].set(sf_gate_info.get("entry_station", "-"))
        self.sf_gate_vars["intermediate_entry"].set(
            sf_gate_info.get("intermediate_entry_station", "-")
        )
        self.sf_gate_vars["intermediate_entry_date"].set(
            sf_gate_info.get("intermediate_entry_date", "-")
        )
        self.sf_gate_vars["intermediate_entry_time"].set(
            _format_hex_clock(sf_gate_info.get("intermediate_entry_time"))
        )
        self.sf_gate_vars["intermediate_exit"].set(
            sf_gate_info.get("intermediate_exit_station", "-")
        )
        self.sf_gate_vars["intermediate_exit_time"].set(
            _format_hex_clock(sf_gate_info.get("intermediate_exit_time"))
        )
        self.sf_gate_vars["unknown_value1"].set(
            sf_gate_info.get("unknown_value1_hex", "-")
        )
        self.sf_gate_vars["unknown_value2"].set(
            sf_gate_info.get("unknown_value2_hex", "-")
        )

    def _render_gate_rows(self, entries: list[dict[str, Any]]) -> None:
        if self.gate_tree is None:
            return

        # Copy so column sorting reorders the view without mutating card data.
        self._gate_view = list(entries)
        self.gate_tree.delete(*self.gate_tree.get_children())

        for index, entry in enumerate(self._gate_view):
            date_value = entry.get("date")
            timestamp = date_value if isinstance(date_value, str) else "-"
            time_value = entry.get("time")
            if isinstance(time_value, str) and time_value:
                timestamp = f"{timestamp} {time_value}".strip()
            timestamp = timestamp.strip()
            values = (
                timestamp,
                entry.get("gate_in_out_type", "-"),
                entry.get("intermediate_gate_instruction_type", "-"),
                entry.get("station", "-"),
                entry.get("device_id_hex", "-"),
                _format_currency(entry.get("amount")),
                _format_currency(entry.get("commuter_pass_fee")),
                entry.get("commuter_station", "-"),
            )
            tag = "odd" if index % 2 else "even"
            self.gate_tree.insert("", tk.END, values=values, tags=(tag,))

    def _populate_history(self, history: list[dict[str, Any]]) -> None:
        self.current_history = history
        self._apply_history_filter()

    def _populate_details(self, card_data: CardData) -> None:
        if self.details_text is None:
            return

        serializable_data = card_data.to_serializable_dict()
        text = json.dumps(serializable_data, ensure_ascii=False, indent=2)
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", text)
        self.details_text.configure(state=tk.DISABLED)
        self.current_card_json = text

        for button in (
            self.copy_details_button,
            self.export_details_button,
            self.export_csv_button,
        ):
            if button is not None:
                button.configure(state=tk.NORMAL)

    def _finalize_card_update(self) -> None:
        self.last_updated_var.set(f"読取日時: {self._current_local_timestamp()}")
        self._update_status("カード情報を読み取りました。")
        self._set_progress(100.0)

    def _set_progress(self, value: float) -> None:
        clamped = max(0.0, min(100.0, value))
        self.root.after(0, self.progress_var.set, clamped)

    def _reset_progress(self) -> None:
        self._set_progress(0.0)

    def _handle_card_removed(self) -> None:
        self._reset_progress()
        self._update_status("カードをかざしてください。")
        self.last_updated_var.set("読取日時: —")

        self._reset_string_vars(self.summary_vars)
        self._reset_string_vars(self.card_detail_vars)
        self._reset_string_vars(self.attribute_detail_vars)
        self._reset_string_vars(self.commuter_detail_vars)
        self._reset_string_vars(self.misc_detail_vars)
        self._reset_string_vars(self.sf_gate_vars)
        self.hero_balance_var.set("—")
        self.hero_subtitle_var.set("カード未読取")

        self.current_history = []
        self._history_view = []
        self.history_filter_var.set("")
        if self.history_tree is not None:
            self.history_tree.delete(*self.history_tree.get_children())

        self.current_gate_entries = []
        self._gate_view = []
        if self.gate_tree is not None:
            self.gate_tree.delete(*self.gate_tree.get_children())

        if self.details_text is not None:
            self.details_text.configure(state=tk.NORMAL)
            self.details_text.delete("1.0", tk.END)
            self.details_text.configure(state=tk.DISABLED)
        self.current_card_json = ""

        for button in (
            self.copy_details_button,
            self.export_details_button,
            self.export_csv_button,
        ):
            if button is not None:
                button.configure(state=tk.DISABLED)

        if self._remote_client is not None:
            self._remote_client.close()
            self._remote_client = None

    def _update_status(self, message: str) -> None:
        self.root.after(0, self.status_var.set, message)

    def _show_error(self, title: str, message: str) -> None:
        # Safe to call from the NFC thread; Tk itself is touched on the main thread.
        self.root.after(0, messagebox.showerror, title, message)

    def _current_local_timestamp(self) -> str:
        local_time = datetime.now().astimezone()
        return local_time.strftime("%Y-%m-%d %H:%M:%S %Z")

    def _on_close(self) -> None:
        if self._remote_client is not None:
            self._remote_client.close()
            self._remote_client = None
        self.root.quit()

    def run(self) -> None:
        self.root.mainloop()


def _sort_value(entry: dict[str, Any], key: str, numeric: bool) -> tuple:
    """Sort key that keeps missing values last regardless of type."""
    value = entry.get(key)
    if numeric:
        return (value is None, value if isinstance(value, int) else 0)
    return (value is None, str(value if value is not None else "").lower())


def fix_ic_code_map() -> None:
    FelicaStandard.IC_CODE_MAP[0x31] = ("RC-S???", 1, 1)
    FelicaStandard.IC_CODE_MAP[0x36] = ("RC-S???", 1, 1)


def main() -> None:
    fix_ic_code_map()

    app = SuicaGuiApp()
    app.run()


if __name__ == "__main__":
    main()
