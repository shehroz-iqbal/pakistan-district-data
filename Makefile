.PHONY: all install data test serve clean

PYTHON ?= python3

all: data test

install:
	$(PYTHON) -m pip install -r requirements.txt

# Download pinned sources, build tables and boundaries, run checks, export files.
data:
	$(PYTHON) -m pipeline.run

test:
	$(PYTHON) -m pytest -q

# Preview the dashboard at http://localhost:8000
serve:
	cd site && $(PYTHON) -m http.server 8000

clean:
	rm -rf data/raw data/pakistan_districts.duckdb
