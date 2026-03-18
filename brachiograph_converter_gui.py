# TODO: better help info / commenting
# TODO: handle image sizing
# TODO: figure out a way to handle SVG
# TODO: other optimisations e.g. threading
# TODO: send print instruction?

import sys
import subprocess
import os
import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

import paramiko
import cairosvg

from linedraw import image_to_json

SIZE_LIMIT = 3 * 1024 * 1024  # 3 MB
DEFAULT_SETTINGS = {
    "draw_contours": 2,
    "draw_hatch": 16,
    "repeat_contours": 0,
    "sftp_hostname": "",
    "sftp_user": "",
    "sftp_password": "",
    "sftp_directory": "",
}
IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/tiff", "image/webp"]
CONFIG_FILE = Path.home() / ".brachiograph_converter.json"


# ── SFTP settings dialog ────────────────────────────────────────────────────


class SFTPSettingsDialog(Adw.PreferencesDialog):
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

        self.password_row = Adw.PasswordEntryRow()
        self.password_row.set_title("Password")
        group.add(self.password_row)

        self.directory_row = Adw.EntryRow()
        self.directory_row.set_title("Remote Directory")
        group.add(self.directory_row)

    def populate(self, settings):
        self.hostname_row.set_text(settings.get("sftp_hostname", ""))
        self.username_row.set_text(settings.get("sftp_user", ""))
        self.password_row.set_text(settings.get("sftp_password", ""))
        self.directory_row.set_text(settings.get("sftp_directory", ""))

    def collect(self):
        return {
            "sftp_hostname": self.hostname_row.get_text(),
            "sftp_user": self.username_row.get_text(),
            "sftp_password": self.password_row.get_text(),
            "sftp_directory": self.directory_row.get_text(),
        }


# ── Main window ─────────────────────────────────────────────────────────────


class BrachiographWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("BrachioGraph Image Converter")
        self.set_default_size(960, 640)
        self._setup_ui()
        self._load_settings()

    # ── UI construction ──────────────────────────────────────────────────────

    def _setup_ui(self):
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

        # ── Left panel ───────────────────────────────────────────────────────
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
        left.append(self._make_section_label("Convert Image to JSON"))

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
        )
        self.hatch_scale = self._append_scale_row(
            settings_list,
            "Hatch",
            "Hatching spacing. Default 16; smaller = more detail",
            1, 100, 1, 16,
        )
        self.repeat_scale = self._append_scale_row(
            settings_list,
            "Repeat Contours",
            "Times to repeat outer edges. Default 0",
            0, 10, 1, 0,
        )

        generate_btn = Gtk.Button(label="Generate")
        generate_btn.add_css_class("suggested-action")
        generate_btn.connect("clicked", self._on_generate)
        left.append(generate_btn)

        left.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Upload section
        left.append(self._make_section_label("Upload to BrachioGraph"))

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

        # Push everything up
        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        left.append(spacer)

        # ── Right panel: preview ─────────────────────────────────────────────
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

        self._set_picture(Path("ui") / "blank.png")

    @staticmethod
    def _make_section_label(text):
        lbl = Gtk.Label(label=text)
        lbl.add_css_class("title-3")
        lbl.set_xalign(0)
        lbl.set_margin_top(4)
        return lbl

    @staticmethod
    def _make_list_box():
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        return lb

    @staticmethod
    def _make_list_row(child):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_child(child)
        return row

    def _append_file_row(self, list_box, label_text, entry, callback):
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

    def _append_scale_row(self, list_box, title, tooltip, min_val, max_val, step, default):
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

        value_lbl = Gtk.Label(label=str(int(default)))
        value_lbl.set_size_request(32, -1)
        value_lbl.set_xalign(1)
        box.append(value_lbl)

        scale.connect("value-changed", lambda s: value_lbl.set_label(str(int(s.get_value()))))

        list_box.append(self._make_list_row(box))
        return scale

    # ── Settings ─────────────────────────────────────────────────────────────

    def _load_settings(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                settings = json.load(f)
        else:
            settings = dict(DEFAULT_SETTINGS)
            self._save_settings(settings)

        self.contours_scale.set_value(settings.get("draw_contours", 2))
        self.hatch_scale.set_value(settings.get("draw_hatch", 16))
        self.repeat_scale.set_value(settings.get("repeat_contours", 0))

    def _save_settings(self, settings):
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f)

    def _current_settings(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                return json.load(f)
        return dict(DEFAULT_SETTINGS)

    # ── Signal handlers ───────────────────────────────────────────────────────

    def _on_browse_image(self, _btn):
        settings = self._current_settings()
        last_dir = settings.get("last_image_directory", str(Path.home()))

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

    def _on_image_chosen(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            self.image_entry.set_text(path)
            settings = self._current_settings()
            settings["last_image_directory"] = str(Path(path).parent)
            self._save_settings(settings)

    def _on_browse_json(self, _btn):
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

    def _on_json_chosen(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return
        path = gfile.get_path()
        if path:
            self.json_entry.set_text(path)

    def _on_generate(self, _btn):
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

    def _on_upload(self, _btn):
        settings = self._current_settings()
        hostname = settings.get("sftp_hostname", "")
        username = settings.get("sftp_user", "")
        password = settings.get("sftp_password", "")
        remote_directory = settings.get("sftp_directory", "")
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

    def _on_view_files(self, _btn):
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

    def _on_sftp_settings(self, _btn):
        dlg = SFTPSettingsDialog()
        dlg.populate(self._current_settings())

        def on_closed(_dialog):
            settings = self._current_settings()
            settings.update(dlg.collect())
            self._save_settings(settings)

        dlg.connect("closed", on_closed)
        dlg.present(self)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_picture(self, path):
        self.picture.set_file(Gio.File.new_for_path(str(path)))

    def _show_error(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present(self)

    def _show_info(self, heading, body):
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present(self)


# ── Application ───────────────────────────────────────────────────────────────


class BrachiographApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="uk.andypiper.brachiograph-converter")
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        window = BrachiographWindow(application=app)
        window.present()


if __name__ == "__main__":
    app = BrachiographApp()
    sys.exit(app.run(sys.argv))
