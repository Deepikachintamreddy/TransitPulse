# Makefile for TransitPulse

.PHONY: data data-full benchmark serve demo cloud clean

data:
	py generate_pings.py --scale small

data-full:
	py generate_pings.py --scale full

benchmark:
	py benchmark.py --run-all

serve:
	py -m uvicorn server:app --reload --host 0.0.0.0 --port 8000

demo:
	py generate_pings.py --scale small
	py pipeline.py --input data/pings --output data/output
	py scripts/generate_copilot_cache.py
	py -m uvicorn server:app --host 0.0.0.0 --port 8000

cloud:
	@echo "Running in Cloud Mode (GCS + BigQuery)..."
	py generate_pings.py --scale small
	py pipeline.py --input data/pings --output data/output
	py scripts/generate_copilot_cache.py
	py loader.py
	SET BQ_SERVE_MODE=cloud&& py -m uvicorn server:app --host 0.0.0.0 --port 8000

clean:
	if exist data rmdir /s /q data
	if exist results\benchmark_results.json del /f /q results\benchmark_results.json
