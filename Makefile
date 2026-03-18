PROJECTDIR  := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PREFIX      ?= $(HOME)/.local
BINDIR      := $(PREFIX)/bin
APPDIR      := $(PREFIX)/share/applications
ICONDIR     := $(PREFIX)/share/icons/hicolor/512x512/apps
METAINFODIR := $(PREFIX)/share/metainfo
SCHEMADIR   := $(PREFIX)/share/glib-2.0/schemas

APP_ID      := uk.andypiper.brachiograph-converter
SCHEMA_XML  := data/$(APP_ID).gschema.xml

.PHONY: sync compile-schemas run install uninstall clean

## Install Python dependencies into the project virtual environment.
## The venv is created with --system-site-packages so that PyGObject
## (python3-gi, installed via apt/dnf) is visible inside it.
sync:
	uv venv --system-site-packages
	uv sync --frozen --inexact

## Compile the GSettings schema into data/ for development use.
compile-schemas:
	glib-compile-schemas data/

## Run the application from the source tree (compiles schema automatically).
run: sync compile-schemas
	GSETTINGS_SCHEMA_DIR=data/ uv run brachiograph-converter

## Install the application for the current user.
##   - Creates a wrapper in ~/.local/bin
##   - Installs the .desktop file, icon, AppStream metainfo, and GSettings schema
install: sync
	@mkdir -p "$(BINDIR)" "$(APPDIR)" "$(ICONDIR)" "$(METAINFODIR)" "$(SCHEMADIR)"
	@# Wrapper script: delegates to the venv binary so uv need not be in PATH at runtime
	@printf '#!/bin/sh\nexec "%s/.venv/bin/brachiograph-converter" "$$@"\n' \
		"$(PROJECTDIR)" > "$(BINDIR)/brachiograph-converter"
	@chmod +x "$(BINDIR)/brachiograph-converter"
	@# Desktop integration
	cp data/$(APP_ID).desktop "$(APPDIR)/"
	cp ui/icon.png "$(ICONDIR)/$(APP_ID).png"
	cp data/$(APP_ID).metainfo.xml "$(METAINFODIR)/"
	@# GSettings schema
	cp $(SCHEMA_XML) "$(SCHEMADIR)/"
	glib-compile-schemas "$(SCHEMADIR)"
	@# Refresh caches (non-fatal if tools are absent)
	-gtk-update-icon-cache -f -t "$(PREFIX)/share/icons/hicolor"
	-update-desktop-database "$(APPDIR)"
	@echo ""
	@echo "Installed. Make sure $(BINDIR) is on your PATH, then run:"
	@echo "  brachiograph-converter"
	@echo "or launch it from your application grid."

## Remove all files installed by 'make install'.
uninstall:
	rm -f "$(BINDIR)/brachiograph-converter"
	rm -f "$(APPDIR)/$(APP_ID).desktop"
	rm -f "$(ICONDIR)/$(APP_ID).png"
	rm -f "$(METAINFODIR)/$(APP_ID).metainfo.xml"
	rm -f "$(SCHEMADIR)/$(APP_ID).gschema.xml"
	-glib-compile-schemas "$(SCHEMADIR)"
	-gtk-update-icon-cache -f -t "$(PREFIX)/share/icons/hicolor"
	-update-desktop-database "$(APPDIR)"

## Remove generated files (virtual environment and compiled schemas).
clean:
	rm -rf .venv data/gschemas.compiled
