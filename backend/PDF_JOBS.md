Report Demo PDF generation
=========================

Report_Demo.html now POSTs /api/combine-pdf-jobs, polls the job every two
seconds, and downloads /api/combine-pdf-jobs/{job_id}/result once ready.
Conversion no longer holds a browser request open past a proxy's 60-second
idle timeout. The original synchronous /api/combine-to-pdf remains available
for existing callers.

Deploy the backend and HTML together by rebuilding the backend image using
the existing compose configuration (from this directory):

    podman compose up -d --build backend

The current Dockerfile runs one Uvicorn process. Jobs are temporary and local
to that process: do not enable multiple workers or backend replicas without
moving jobs/results to shared storage and a shared queue. Restarting the
backend loses pending jobs and results. Completed results expire after 30
minutes on subsequent queue access and can be evicted earlier if the eight-job
capacity is reached. Two report jobs run concurrently; each keeps the existing
five-file conversion concurrency. A full active queue returns HTTP 429.

Validation:

    py -3 -m unittest discover -s . -p test_pdf_jobs.py -v

After deployment, generate the affected STEAM TURBINE report and confirm the
create request returns 202 promptly, polling returns 200 while conversion
runs (including past 60 seconds), and the result displays the expected pages
in selected file order. Also check conversion failures display an error and
ZIP download still uses the files from the completed preview.
