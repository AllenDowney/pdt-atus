PYTHON ?= python
# A PublicDataToolkit checkout. Or `pip install -e $(PDT)` and run `pdt check`.
PDT ?= ../PublicDataToolkit

# Data jobs run under a memory cap (CLAUDE.md); the activity file has 5 million rows.
CAP ?= systemd-run --user --scope -p MemoryMax=6G -p MemorySwapMax=0 --quiet

.PHONY: download data build views check

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
views:
	PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt views .

## Check the repo against the PublicDataToolkit standard (pdt check)
check:
	$(CAP) env PYTHONPATH=$(PDT)/lib $(PYTHON) -m pdt check .
