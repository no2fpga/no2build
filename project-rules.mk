#
# Nitro FPGA build system: Project rules file
#
# Copyright (C) 2020 Sylvain Munaut
# SPDX-License-Identifier: BSD-3-Clause
#

# Default tools
YOSYS ?= yosys
YOSYS_READ_ARGS ?=
YOSYS_SYNTH_ARGS ?= -dffe_min_ce_use 4
NEXTPNR ?= nextpnr-ice40
NEXTPNR_ARGS ?= --freq 50
ICEPACK ?= icepack
ICEPROG ?= iceprog
IVERILOG ?= iverilog
DFU_UTIL ?= dfu-util

ifeq ($(PLACER),heap)
NEXTPNR_SYS_ARGS += --placer heap
endif

ICE40_LIBS ?= $(shell yosys-config --datdir/ice40/cells_sim.v)


# Must be first rule and call it 'all' by convention
all: synth

# Base directories
ifeq ($(origin NO2BUILD_DIR), undefined)
NO2BUILD_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
endif

ifeq ($(origin NO2CORES_DIR), undefined)
NO2CORES_DIR := $(abspath $(NO2BUILD_DIR)/../cores)
endif

# Temporary build-directory
BUILD_TMP := $(abspath build-tmp)

$(BUILD_TMP):
	@mkdir -p $(BUILD_TMP)

# Discover all cores
$(foreach core_def, $(wildcard $(NO2CORES_DIR)/*/no2core.mk), $(eval include $(core_def)))

# Resolve dependency tree for project and collect sources
$(BUILD_TMP)/proj-deps.mk: Makefile $(BUILD_TMP) $(addprefix $(BUILD_TMP)/deps-core-,$(PROJ_DEPS))
	@echo "SELF_DIR := \$$(dir \$$(lastword \$$(MAKEFILE_LIST)))" > $@
	@if [ "$(PROJ_DEPS)" != "" ]; then \
		echo "include \$$(SELF_DIR)deps-core-*" >> $@; \
	fi
	@echo "PROJ_ALL_DEPS := \$$(DEPS_SOLVE_TMP)" >> $@
	@echo "PROJ_ALL_RTL_SRCS := \$$(RTL_SRCS_SOLVE_TMP)" >> $@
	@echo "PROJ_ALL_SIM_SRCS := \$$(SIM_SRCS_SOLVE_TMP)" >> $@
	@echo "PROJ_ALL_PREREQ := \$$(PREREQ_SOLVE_TMP)" >> $@

include $(BUILD_TMP)/proj-deps.mk

# Make all sources absolute
PROJ_RTL_SRCS := $(abspath $(PROJ_RTL_SRCS))
PROJ_SIM_SRCS := $(abspath $(PROJ_SIM_SRCS))
PROJ_TOP_SRC  := $(abspath $(PROJ_TOP_SRC))

# Board config
PIN_DEF ?= $(abspath data/$(PROJ_TOP_MOD)-$(BOARD).pcf)

BOARD_DEFINE=BOARD_$(shell echo $(BOARD) | tr a-z\- A-Z_)
YOSYS_READ_ARGS += -D$(BOARD_DEFINE)=1

# Add those to the list
PROJ_ALL_RTL_SRCS += $(PROJ_RTL_SRCS)
PROJ_ALL_SIM_SRCS += $(PROJ_SIM_SRCS)
PROJ_ALL_PREREQ += $(PROJ_PREREQ)

# Include path
PROJ_SYNTH_INCLUDES := -I$(abspath rtl/) $(addsuffix /rtl/, $(addprefix -I$(NO2CORES_DIR)/, $(PROJ_ALL_DEPS)))
PROJ_SIM_INCLUDES   := -I$(abspath sim/) $(addsuffix /sim/, $(addprefix -I$(NO2CORES_DIR)/, $(PROJ_ALL_DEPS)))


# Synthesis & Place-n-route rules

$(BUILD_TMP)/$(PROJ).ys: $(PROJ_TOP_SRC) $(PROJ_ALL_RTL_SRCS)
	@echo "read_verilog $(YOSYS_READ_ARGS) $(PROJ_SYNTH_INCLUDES) $(PROJ_TOP_SRC) $(PROJ_ALL_RTL_SRCS)" > $@
	@echo "synth_ice40 $(YOSYS_SYNTH_ARGS) -top $(PROJ_TOP_MOD) -json $(PROJ).json" >> $@

$(BUILD_TMP)/$(PROJ).synth.rpt $(BUILD_TMP)/$(PROJ).json: $(PROJ_ALL_PREREQ) $(BUILD_TMP)/$(PROJ).ys $(PROJ_ALL_RTL_SRCS)
	cd $(BUILD_TMP) && \
		$(YOSYS) -s $(BUILD_TMP)/$(PROJ).ys \
			 -l $(BUILD_TMP)/$(PROJ).synth.rpt

$(BUILD_TMP)/$(PROJ).pnr.rpt $(BUILD_TMP)/$(PROJ).asc: $(BUILD_TMP)/$(PROJ).json $(PIN_DEF)
	$(NEXTPNR) $(NEXTPNR_ARGS) $(NEXTPNR_SYS_ARGS) \
		--$(DEVICE) --package $(PACKAGE)  \
		-l $(BUILD_TMP)/$(PROJ).pnr.rpt \
		--json $(BUILD_TMP)/$(PROJ).json \
		--pcf $(PIN_DEF) \
		--asc $@

%.bin: %.asc
	$(ICEPACK) -s $< $@


# Simulation
$(BUILD_TMP)/%_tb: sim/%_tb.v $(ICE40_LIBS) $(PROJ_ALL_PREREQ) $(PROJ_ALL_RTL_SRCS) $(PROJ_ALL_SIM_SRCS)
	$(IVERILOG) -Wall -Wno-portbind -Wno-timescale -DSIM=1 -DNO_ICE40_DEFAULT_ASSIGNMENTS -D$(BOARD_DEFINE)=1 -o $@ \
		$(PROJ_SYNTH_INCLUDES) $(PROJ_SIM_INCLUDES) \
		$(addprefix -l, $(ICE40_LIBS) $(PROJ_ALL_RTL_SRCS) $(PROJ_ALL_SIM_SRCS)) \
		$<


# Action targets

synth: $(BUILD_TMP)/$(PROJ).bin

sim: $(addprefix $(BUILD_TMP)/, $(PROJ_TESTBENCHES))

prog: $(BUILD_TMP)/$(PROJ).bin
	$(ICEPROG) $<

sudo-prog: $(BUILD_TMP)/$(PROJ).bin
	@echo 'Executing prog as root!!!'
	sudo $(ICEPROG) $<

dfuprog: $(BUILD_TMP)/$(PROJ).bin
ifeq ($(DFU_SERIAL),)
	$(DFU_UTIL) -e -a 0 -D $<
else
	$(DFU_UTIL) -e -S $(DFU_SERIAL) -a 0 -D $<
endif

clean:
	@rm -Rf $(BUILD_TMP)


.PHONY: all synth sim prog sudo-prog clean
