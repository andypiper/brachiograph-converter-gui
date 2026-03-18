# TODO: better help info / commenting
# TODO: handle image sizing
# TODO: figure out a way to handle SVG
# TODO: other optimisations e.g. threading
# TODO: send print instruction?

import subprocess
import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

import paramiko
import cairosvg

from linedraw import image_to_json

# Absolute path to the directory containing this file; used to locate
# bundled assets (ui/) whether running from source or as an installed wheel.
APP_DIR = Path(__file__).parent.resolve()
APP_ID = "uk.andypiper.brachiograph-converter"

SIZE_LIMIT = 3 * 1024 * 1024  # 3 MB
IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/tiff", "image/webp"]


# ── SFTP settings dialog ─────────────────────────────────────────────────────


class SFTPSettingsDialog(Adw.PreferencesDialog):
    """Preferences dialog for SFTP connection settings.

    Call bind_settings(gio_settings) after construction to wire the rows
    directly to GSettings — changes are persisted automatically.
    """

    def __init__(self):
        super().__init__()
        self.set_title("SFTP Settings")
        self.set_search_enabled(False)

        page = Adw.PreferencesPage()
        self.add(page)

        group = Adw.PreferencesGroup()
        group.set_title("Connection")
        page.add(group)

        self.hostname_row = Adw.EntryRow()
        self.hostname_row.set_title("Hostname")
        group.add(self.hostname_row)

        self.username_row = Adw.EntryRow()
        self.username_row.set_title("Username")
        group.add(self.username_row)

        # NOTE: stored in dconf (not encrypted). Replace with libsecret for
        # a hardened deployment.
        self.password_row = Adw.PasswordEntryRow()
        self.password_row.set_title("Password")
        group.add(self.password_row)

        self.directory_row = Adw.EntryRow()
        self.directory_row.set_title("Remote Directory")
        group.add(self.directory_row)

    def bind_settings(self, settings: Gio.Settings) -> None:
        """Bind all rows to GSettings — changes write through immediately."""
        flags = Gio.SettingsBindFlags.DEFAULT
        settings.bind("sftp-hostname", self.hostname_row, "text", flags)
        settings.bind("sftp-user", self.username_row, "text", flags)
        settings.bind("sftp-password", self.password_row, "text", flags)
        settings.bind("sftp-directory", self.directory_row, "text", flags)


# ── Main window ──────────────────────────────────────────────────────────────


class BrachiographWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._settings = Gio.Settings(schema_id=APP_ID)
        self.set_title("BrachioGraph Image Converter")
        self.set_default_size(960, 640)
        self._setup_ui()
        self._load_settings()

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        sftp_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        sftp_btn.set_tooltip_text("SFTP Settings")
        sftp_btn.connect("clicked", self._on_sftp_settings)
        header.pack_end(sftp_btn)

        # Root horizontal split
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        toolbar_view.set_content(root)

        # ── Left panel ────────────────────────────────────────────────────────
        left_scroll = Gtk.ScrolledWindow()
        left_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        left_scroll.set_size_request(340, -1)
        root.append(left_scroll)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.set_margin_top(4)
        left.set_margin_bottom(4)
        left.set_margin_start(4)
        left.set_margin_end(4)
        left_scroll.set_child(left)

        # Convert section
        left.append(self._section_label("Convert Image to JSON"))

        image_list = self._make_list_box()
        left.append(image_list)
        self.image_entry = Gtk.Entry()
        self.image_entry.set_placeholder_text("Select an image file…")
        self._append_file_row(image_list, "Image:", self.image_entry, self._on_browse_image)

        settings_list = self._make_list_box()
        left.append(settings_list)

        self.contours_scale = self._append_scale_row(
            settings_list,
            "Contours",
            "Default 2; smaller = more detail",
            0, 10, 1, 2,
            "draw-contours",
        )
        self.hatch_scale = self._append_scale_row(
            settings_list,
            "Hatch",
            "Hatching spacing. Default 16; smaller = more detail",
            1, 100, 1, 16,
            "draw-hatch",
        )
        self.repeat_scale = self._append_scale_row(
            settings_list,
            "Repeat Contours",
            "Times to repeat outer edges. Default 0",
            0, 10, 1, 0,
            "repeat-contours",
        )

        generate_btn = Gtk.Button(label="Generate")
        generate_btn.add_css_class("suggested-action")
        generate_btn.connect("clicked", self._on_generate)
        left.append(generate_btn)

        left.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Upload section
        left.append(self._section_label("Upload to BrachioGraph"))

        json_list = self._make_list_box()
        left.append(json_list)
        self.json_entry = Gtk.Entry()
        self.json_entry.set_placeholder_text("Select a JSON file…")
        self._append_file_row(json_list, "JSON File:", self.json_entry, self._on_browse_json)

        upload_btn = Gtk.Button(label="Upload Files")
        upload_btn.connect("clicked", self._on_upload)
        left.append(upload_btn)

        left.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        view_btn = Gtk.Button(label="View Files")
        view_btn.connect("clicked", self._on_view_files)
        left.append(view_btn)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        left.append(spacer)

        # ── Right panel: preview ──────────────────────────────────────────────
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        right.set_hexpand(True)
        right.set_vexpand(True)
        root.append(right)

        self.picture = Gtk.Picture()
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.set_can_shrink(True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.add_css_class("card")
        right.append(self.picture)

        self._set_picture(APP_DIR / "ui" / "blank.png")

    @staticmethod
    def _section_label(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.add_css_class("title-3")
        lbl.set_xalign(0)
        lbl.set_margin_top(4)
        return lbl

    @staticmethod
    def _make_list_box() -> Gtk.ListBox:
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        return lb

    @staticmethod
    def _make_list_row(child: Gtk.Widget) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_child(child)
        return row

    def _append_file_row(
        self,
        list_box: Gtk.ListBox,
        label_text: str,
        entry: Gtk.Entry,
        callback,
    ) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        lbl = Gtk.Label(label=label_text, xalign=0)
        lbl.set_size_request(80, -1)
        box.append(lbl)

        entry.set_hexpand(True)
        box.append(entry)

        btn = Gtk.Button(label="Browse")
        btn.set_valign(Gtk.Align.CENTER)
        btn.connect("clicked", callback)
        box.append(btn)

        list_box.append(self._make_list_row(box))

    def _append_scale_row(
        self,
        list_box: Gtk.ListBox,
        title: str,
        tooltip: str,
        min_val: int,
        max_val: int,
        step: int,
        default: int,
        settings_key: str,
    ) -> Gtk.Scale:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(12)
        box.set_margin_end(12)

        lbl = Gtk.Label(label=f"{title}:", xalign=0)
        lbl.set_size_request(130, -1)
        lbl.set_tooltip_text(tooltip)
        box.append(lbl)

        adj = Gtk.Adjustment(
            value=default,
            lower=min_val,
            upper=max_val,
            step_increment=step,
            page_increment=step * 10,
        )
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        scale.set_hexpand(True)
        scale.set_draw_value(False)
        scale.set_round_digits(0)
        scale.set_tooltip_text(tooltip)
        box.append(scale)

        value_lbl = Gtk.Label(label=str(default))
        value_lbl.set_size_request(32, -1)
        value_lbl.set_xalign(1)
        box.append(value_lbl)

        def on_value_changed(s: Gtk.Scale) -> None:
            v = int(s.get_value())
            value_lbl.set_label(str(v))
            self._settings.set_int(settings_key, v)

        scale.connect("value-changed", on_value_changed)
        list_box.append(self._make_list_row(box))
        return scale

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self) -> None:
        """Populate widgets from GSettings on startup."""
        self.contours_scale.set_value(self._settings.get_int("draw-contours"))
        self.hatch_scale.set_value(self._settings.get_int("draw-hatch"))
        self.repeat_scale.set_value(self._settings.get_int("repeat-contours"))

    # ── Signal handlers ────────────────────────────────────────────────────────

    def _on_browse_image(self, _btn) -> None:
        last_dir = self._settings.get_string("last-image-directory") or str(Path.home())

        dialog = Gtk.FileDialog()
        dialog.set_title("Select Image")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter()
        f.set_name("Images")
        for mime in IMAGE_MIME_TYPES:
            f.add_mime_type(mime)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.set_initial_folder(Gio.File.new_for_path(last_dir))
        dialog.open(self, None, self._on_image_chosen)

    def _on_image_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            self.image_entry.set_text(path)
            self._settings.set_string("last-image-directory", str(Path(path).parent))

    def _on_browse_json(self, _btn) -> None:
        images_dir = Path("images")
        images_dir.mkdir(parents=True, exist_ok=True)

        dialog = Gtk.FileDialog()
        dialog.set_title("Select JSON File")

        filters = Gio.ListStore.new(Gtk.FileFilter)
        f = Gtk.FileFilter()
        f.set_name("JSON files")
        f.add_pattern("*.json")
        filters.append(f)
        dialog.set_filters(filters)
        dialog.set_initial_folder(Gio.File.new_for_path(str(images_dir.resolve())))
        dialog.open(self, None, self._on_json_chosen)

    def _on_json_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            self.json_entry.set_text(path)

    def _on_generate(self, _btn) -> None:
        image_file = self.image_entry.get_text().strip()
        if not image_file:
            self._show_error("Image Not Selected", "Please select an image file to convert.")
            return

        if os.path.getsize(image_file) > SIZE_LIMIT:
            self._show_error(
                "File Too Large",
                "The selected image file is too large. Please resize it and try again.",
            )
            return

        print("Begin JSON generation")
        image_to_json(
            image_file,
            draw_contours=int(self.contours_scale.get_value()),
            draw_hatch=int(self.hatch_scale.get_value()),
            repeat_contours=int(self.repeat_scale.get_value()),
        )

        input_svg = Path("images") / f"{Path(image_file).stem}.svg"
        output_png = Path("temp") / "converted.png"
        output_png.parent.mkdir(parents=True, exist_ok=True)

        with open(str(input_svg)) as svg_file:
            with open(str(output_png), "wb") as png_file:
                cairosvg.svg2png(
                    file_obj=svg_file,
                    write_to=png_file,
                    parent_width=512,
                    parent_height=512,
                )

        self._set_picture(output_png)

    def _on_upload(self, _btn) -> None:
        hostname = self._settings.get_string("sftp-hostname")
        username = self._settings.get_string("sftp-user")
        password = self._settings.get_string("sftp-password")
        remote_directory = self._settings.get_string("sftp-directory")
        json_file = self.json_entry.get_text().strip()

        if not json_file:
            self._show_error("JSON File Not Selected", "Please select a JSON file to upload.")
            return

        if not all([hostname, username, password, remote_directory]):
            self._show_error(
                "SFTP Configuration Missing",
                "Please configure the SFTP settings before uploading.\n"
                "Click the settings icon in the header bar.",
            )
            return

        print(f"Begin SFTP upload to {hostname}")
        try:
            with paramiko.Transport((hostname, 22)) as transport:
                transport.connect(username=username, password=password)
                with paramiko.SFTPClient.from_transport(transport) as sftp:
                    remote_path = str(Path(remote_directory) / Path(json_file).name)
                    sftp.put(json_file, remote_path)
            self._show_info("Upload Completed", "File uploaded successfully.")
        except paramiko.AuthenticationException:
            self._show_error(
                "Authentication Error",
                "Authentication failed. Please check your credentials.",
            )
        except Exception as exc:
            self._show_error("Upload Error", f"An error occurred: {exc}")

    def _on_view_files(self, _btn) -> None:
        images_dir = Path("images")
        images_dir.mkdir(parents=True, exist_ok=True)
        print(f"Opening directory: {images_dir}")
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(images_dir)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(images_dir)])
            else:
                subprocess.Popen(["xdg-open", str(images_dir)])
        except Exception as exc:
            print(f"Error opening directory: {exc}")

    def _on_sftp_settings(self, _btn) -> None:
        dlg = SFTPSettingsDialog()
        dlg.bind_settings(self._settings)
        dlg.present(self)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _set_picture(self, path: Path) -> None:
        self.picture.set_file(Gio.File.new_for_path(str(path)))

    def _show_error(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present(self)

    def _show_info(self, heading: str, body: str) -> None:
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present(self)


# ── Application ───────────────────────────────────────────────────────────────


class BrachiographApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)

    def _on_activate(self, app: "BrachiographApp") -> None:
        window = BrachiographWindow(application=app)
        window.present()


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    """Entry point used by the installed console script and by direct invocation."""
    # When running from the source tree, compile the GSettings schema into
    # data/ and point GLib at it. Once `make install` has been run the schema
    # lives in ~/.local/share/glib-2.0/schemas/ and no override is needed.
    schema_xml = APP_DIR / "data" / f"{APP_ID}.gschema.xml"
    compiled = APP_DIR / "data" / "gschemas.compiled"
    if schema_xml.exists() and "GSETTINGS_SCHEMA_DIR" not in os.environ:
        if not compiled.exists():
            subprocess.run(
                ["glib-compile-schemas", str(schema_xml.parent)],
                check=False,
            )
        if compiled.exists():
            os.environ["GSETTINGS_SCHEMA_DIR"] = str(schema_xml.parent)

    app = BrachiographApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
