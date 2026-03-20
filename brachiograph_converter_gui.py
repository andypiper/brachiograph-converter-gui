# TODO: better help info / commenting
# TODO: handle image sizing
# TODO: figure out a way to handle SVG
# TODO: other optimisations e.g. threading
# TODO: send print instruction?

import posixpath
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

APP_DIR = Path(__file__).parent.resolve()
APP_ID = "org.andypiper.brachiograph-converter"

SIZE_LIMIT = 3 * 1024 * 1024  # 3 MB
IMAGE_MIME_TYPES = ["image/jpeg", "image/png", "image/tiff", "image/webp"]
IMAGES_DIR = Path("images")
TEMP_DIR = Path("temp")


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

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        sftp_btn = Gtk.Button(icon_name="preferences-system-symbolic")
        sftp_btn.set_tooltip_text("SFTP Settings")
        sftp_btn.connect("clicked", self._on_sftp_settings)
        header.pack_end(sftp_btn)

        # Toast overlay wraps all content so toasts appear above everything.
        self._toast_overlay = Adw.ToastOverlay()
        toolbar_view.set_content(self._toast_overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self._toast_overlay.set_child(root)

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
        self.image_entry_row = self._make_entry_row("Image File", self._on_browse_image)
        image_list.append(self.image_entry_row)

        settings_list = self._make_list_box()
        left.append(settings_list)
        self.contours_spin = self._make_spin_row(
            "Contours",
            "Default 2; smaller = more detail",
            0, 10, 1,
            "draw-contours",
        )
        settings_list.append(self.contours_spin)
        self.hatch_spin = self._make_spin_row(
            "Hatch",
            "Hatching spacing. Default 16; smaller = more detail",
            1, 100, 1,
            "draw-hatch",
        )
        settings_list.append(self.hatch_spin)
        self.repeat_spin = self._make_spin_row(
            "Repeat Contours",
            "Times to repeat outer edges. Default 0",
            0, 10, 1,
            "repeat-contours",
        )
        settings_list.append(self.repeat_spin)

        generate_btn = Gtk.Button(label="Generate")
        generate_btn.add_css_class("suggested-action")
        generate_btn.connect("clicked", self._on_generate)
        left.append(generate_btn)

        left.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Upload section
        left.append(self._section_label("Upload to BrachioGraph"))

        json_list = self._make_list_box()
        left.append(json_list)
        self.json_entry_row = self._make_entry_row("JSON File", self._on_browse_json)
        json_list.append(self.json_entry_row)

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
        # Stack switches between the empty-state page and the generated image.
        self._preview_stack = Gtk.Stack()
        self._preview_stack.set_hexpand(True)
        self._preview_stack.set_vexpand(True)
        root.append(self._preview_stack)

        empty_page = Adw.StatusPage()
        empty_page.set_icon_name("image-x-generic-symbolic")
        empty_page.set_title("No Preview")
        empty_page.set_description("Convert an image to see the result here")
        self._preview_stack.add_named(empty_page, "empty")

        self.picture = Gtk.Picture()
        self.picture.set_hexpand(True)
        self.picture.set_vexpand(True)
        self.picture.set_can_shrink(True)
        self.picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.picture.add_css_class("card")
        self._preview_stack.add_named(self.picture, "picture")

    @staticmethod
    def _section_label(text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text)
        lbl.add_css_class("title-4")
        lbl.set_xalign(0)
        lbl.set_margin_top(4)
        return lbl

    @staticmethod
    def _make_list_box() -> Gtk.ListBox:
        lb = Gtk.ListBox()
        lb.set_selection_mode(Gtk.SelectionMode.NONE)
        lb.add_css_class("boxed-list")
        return lb

    def _make_entry_row(self, title: str, callback) -> Adw.EntryRow:
        """Create an Adw.EntryRow with a flat file-open button suffix."""
        row = Adw.EntryRow()
        row.set_title(title)
        btn = Gtk.Button(icon_name="document-open-symbolic")
        btn.set_valign(Gtk.Align.CENTER)
        btn.add_css_class("flat")
        btn.connect("clicked", callback)
        row.add_suffix(btn)
        return row

    def _make_spin_row(
        self,
        title: str,
        subtitle: str,
        min_val: float,
        max_val: float,
        step: float,
        settings_key: str,
    ) -> Adw.SpinRow:
        """Create an Adw.SpinRow wired to a GSettings integer key."""
        adj = Gtk.Adjustment(
            value=float(self._settings.get_int(settings_key)),
            lower=min_val,
            upper=max_val,
            step_increment=step,
            page_increment=step * 10,
        )
        row = Adw.SpinRow.new(adj, climb_rate=1, digits=0)
        row.set_title(title)
        row.set_subtitle(subtitle)
        row.connect(
            "notify::value",
            lambda s, _: self._settings.set_int(settings_key, int(s.get_value())),
        )
        return row

    # ── Signal handlers ────────────────────────────────────────────────────────

    def _on_browse_image(self, _btn) -> None:
        last_dir = self._settings.get_string("last-image-directory") or str(Path.home())
        f = Gtk.FileFilter()
        f.set_name("Images")
        for mime in IMAGE_MIME_TYPES:
            f.add_mime_type(mime)
        self._open_file_dialog("Select Image", f, last_dir, self._on_image_chosen)

    def _on_image_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        path = self._finish_file_dialog(dialog, result, self.image_entry_row)
        if path:
            self._settings.set_string("last-image-directory", str(Path(path).parent))

    def _on_browse_json(self, _btn) -> None:
        f = Gtk.FileFilter()
        f.set_name("JSON files")
        f.add_pattern("*.json")
        self._open_file_dialog(
            "Select JSON File", f,
            str(IMAGES_DIR.resolve()),
            self._on_json_chosen,
        )

    def _on_json_chosen(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        self._finish_file_dialog(dialog, result, self.json_entry_row)

    def _on_generate(self, _btn) -> None:
        image_file = self.image_entry_row.get_text().strip()
        if not image_file:
            self._show_dialog("Image Not Selected", "Please select an image file to convert.")
            return

        try:
            if Path(image_file).stat().st_size > SIZE_LIMIT:
                self._show_dialog(
                    "File Too Large",
                    "The selected image file is too large. Please resize it and try again.",
                )
                return
        except OSError as exc:
            self._show_dialog("File Error", f"Could not read image file: {exc}")
            return

        print("Begin JSON generation")
        image_to_json(
            image_file,
            draw_contours=int(self.contours_spin.get_value()),
            draw_hatch=int(self.hatch_spin.get_value()),
            repeat_contours=int(self.repeat_spin.get_value()),
        )

        input_svg = IMAGES_DIR / f"{Path(image_file).stem}.svg"
        output_png = TEMP_DIR / "converted.png"
        output_png.parent.mkdir(parents=True, exist_ok=True)

        with open(input_svg) as svg_file, open(output_png, "wb") as png_file:
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
        json_file = self.json_entry_row.get_text().strip()

        if not json_file:
            self._show_dialog("JSON File Not Selected", "Please select a JSON file to upload.")
            return

        if not all([hostname, username, password, remote_directory]):
            self._show_dialog(
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
                    remote_path = posixpath.join(remote_directory, Path(json_file).name)
                    sftp.put(json_file, remote_path)
            self._show_toast("File uploaded successfully")
        except paramiko.AuthenticationException:
            self._show_dialog(
                "Authentication Error",
                "Authentication failed. Please check your credentials.",
            )
        except Exception as exc:
            self._show_dialog("Upload Error", f"An error occurred: {exc}")

    def _on_view_files(self, _btn) -> None:
        # Create the output directory if it doesn't already exist — the user
        # is explicitly asking to open it, so creating it here is correct.
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Opening directory: {IMAGES_DIR}")
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(IMAGES_DIR)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(IMAGES_DIR)])
            else:
                subprocess.Popen(["xdg-open", str(IMAGES_DIR)])
        except Exception as exc:
            print(f"Error opening directory: {exc}")

    def _on_sftp_settings(self, _btn) -> None:
        dlg = SFTPSettingsDialog()
        dlg.bind_settings(self._settings)
        dlg.present(self)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _open_file_dialog(
        self,
        title: str,
        file_filter: Gtk.FileFilter,
        initial_dir: str,
        callback,
    ) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(file_filter)
        dialog = Gtk.FileDialog()
        dialog.set_title(title)
        dialog.set_filters(filters)
        dialog.set_initial_folder(Gio.File.new_for_path(initial_dir))
        dialog.open(self, None, callback)

    def _finish_file_dialog(
        self,
        dialog: Gtk.FileDialog,
        result: Gio.AsyncResult,
        entry: Gtk.Editable,
    ) -> str | None:
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error:
            return None
        path = gfile.get_path()
        if path:
            entry.set_text(path)
        return path

    def _set_picture(self, path: Path) -> None:
        self.picture.set_file(Gio.File.new_for_path(str(path)))
        self._preview_stack.set_visible_child_name("picture")

    def _show_dialog(self, heading: str, body: str) -> None:
        """Show a modal alert for errors that require user acknowledgement."""
        dialog = Adw.AlertDialog(heading=heading, body=body)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.present(self)

    def _show_toast(self, message: str) -> None:
        """Show a transient, non-blocking toast for confirmations."""
        self._toast_overlay.add_toast(Adw.Toast(title=message))


# ── Application ───────────────────────────────────────────────────────────────


class BrachiographApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.connect("activate", self._on_activate)

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

    def _on_activate(self, app: "BrachiographApp") -> None:
        window = BrachiographWindow(application=app)
        window.present()


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> int:
    """Entry point used by the installed console script and by direct invocation."""
    # When running from the source tree, point GLib at the local schema and
    # compile it if necessary. Installed builds find the schema via the
    # standard XDG path (~/.local/share/glib-2.0/schemas/) set by make install.
    schema_dir = APP_DIR / "data"
    if (schema_dir / f"{APP_ID}.gschema.xml").exists() and "GSETTINGS_SCHEMA_DIR" not in os.environ:
        os.environ["GSETTINGS_SCHEMA_DIR"] = str(schema_dir)
        if not (schema_dir / "gschemas.compiled").exists():
            subprocess.run(["glib-compile-schemas", str(schema_dir)], check=False)

    app = BrachiographApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
