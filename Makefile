PYTHON ?= python
# A PublicDataToolkit checkout. Or `pip install -e $(PDT)` and run `pdt check`.
PDT ?= ../PublicDataToolkit

# Data jobs run under a memory cap (CLAUDE.md); the activity file has 5 million rows.
CAP ?= systemd-run --user --scope -p MemoryMax=6G -p MemorySwapMax=0 --quiet

.PHONY: download data build views check export-daaf

## Fetch the sources into data/raw. Read the publisher's terms first, then: make download ARGS=--accept-terms
download:
	PYTHONPATH=$(PDT)/lib $(PYTHON) scripts/download.py $(ARGS)

## Write the common-format parquet files in data/processed (STANDARD.md §8)
data:
	$(CAP) env PYTHONPATH=$(PDT)/lib $(PYTHON) scripts/build_data.py

## Build metadata records from data/raw (build/build_records.py writes build/report.md)
build:
	$(CAP) env PYTHONPATH=$(PDT)/lib $(PYTHON) build/build_records.py

## Generate agent/, docs/ and export/ from the records (pdt views)
## VIEWS_ARGS="--only site" builds docs/ alone, as the Pages workflow does.
views:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt views . $(VIEWS_ARGS)

## Check the repo against the PublicDataToolkit standard (pdt check)
check:
	$(CAP) env PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt check .

## On request: export/daaf/, this dataset as a DAAF data-source skill (pdt export daaf).
## The skill's name starts with dataset.yaml's `domain`; ARGS="--domain health" overrides it.
export-daaf:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt export daaf . $(ARGS)
