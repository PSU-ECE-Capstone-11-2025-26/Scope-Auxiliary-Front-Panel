.PHONY: all wheel deb image clean

# Directories
SOFTWARE_DIR := software
AFP_UI_DIR   := afp-ui
IMAGE_BUILD_DIR := image-builder
IMAGE_SRC_DIR := $(IMAGE_BUILD_DIR)/config
RPI_IMAGE_DIR := $(IMAGE_BUILD_DIR)/rpi-image-gen

GODOT_BIN := Godot-stable_linux.arm64

WHEEL := $(wildcard $(SOFTWARE_DIR)/dist/*.whl)

all: wheel deb image

## Build UI binaries
ui:
	${GODOT_BIN} --headless --export-release "Linux" $(AFP_UI_DIR)/$(AFP_UI_DIR)-pkg/opt/tek/afp/ui/ $(AFP_UI_DIR)/project.godot

## Build the Python wheel using uv
wheel:
	cd $(SOFTWARE_DIR) && uv build --wheel

## Build the Debian package
deb:
	cd $(AFP_UI_DIR) && dpkg-deb -b --root-owner-group afp-ui-pkg afp-ui_arm64.deb

## Run rpi-image-gen
image:
	mkdir -p $(IMAGE_SRC_DIR)/packages
	cp $(AFP_UI_DIR)/*.deb $(IMAGE_SRC_DIR)/packages/
	cp $(WHEEL) $(IMAGE_SRC_DIR)/packages/
	cd $(RPI_IMAGE_DIR) && ./rpi-image-gen build -S ../$(IMAGE_SRC_DIR) -c ../$(IMAGE_SRC_DIR)/config/tekafp.yaml

clean:
	rm -rf $(SOFTWARE_DIR)/dist
	cd $(AFP_UI_DIR) && dh_clean
	rm -rf $(RPI_IMAGE_DIR)/work/*
