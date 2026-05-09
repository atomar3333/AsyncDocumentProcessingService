"""
Test 5 small PDFs with summary analysis.
Submits all 5, then polls until all complete.

Run:
  pytest tests/test_5docs_summary.py -v -s
"""

import asyncio
import time

import httpx
import pytest

BASE_URL = "http://localhost:8000"
TIMEOUT = 300  # 5 min max
POLL_INTERVAL = 5

TEST_PDFS = [
    "https://proceedings.neurips.cc/paper_files/paper/2017/file/3f5ee243547dee91fbd053c1c4a845aa-Paper.pdf",
    "https://www.comanage.me/en/downloads/invoice-example-comanage.pdf",
    "https://www.orimi.com/pdf-test_bad.pdf",
    "https://www.irs.gov/pub/irs-pdf/fw9.pdf",
    "https://assets1.cleartax-cdn.com/cleartax/images/1655708276_rentalagreementsampleandallyouneedtoknow.pdf",
]


async def submit_job(client: httpx.AsyncClient, url: str, analysis_type: str) -> dict:
    resp = await client.post(f"{BASE_URL}/jobs", json={
        "document_url": url,
        "analysis_type": analysis_type,
        "token_budget": 16000,
    })
    assert resp.status_code == 202, f"Submit failed: {resp.text}"
    return resp.json()


async def wait_for_job(client: httpx.AsyncClient, job_id: str) -> dict:
    elapsed = 0
    while elapsed < TIMEOUT:
        resp = await client.get(f"{BASE_URL}/jobs/{job_id}")
        job = resp.json()
        if job["status"] in ("completed", "failed"):
            return job
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
    return job


@pytest.mark.asyncio
async def test_5_pdfs_summary():
    """Submit 5 PDFs for summary, wait for all to complete."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Submit all 5
        start = time.time()
        jobs = []
        for url in TEST_PDFS:
            result = await submit_job(client, url, "summary")
            jobs.append(result)
            print(f"  Submitted: {result['id']} for {url.split('/')[-1]}")

        print(f"\n  All 5 submitted in {time.time() - start:.1f}s. Polling...")

        # Poll all until done
        results = []
        for job in jobs:
            final = await wait_for_job(client, job["id"])
            results.append(final)
            status = final["status"]
            tokens = final.get("token_usage", {}).get("total_tokens", "N/A") if final.get("token_usage") else "N/A"
            title = final.get("result", {}).get("title", "N/A") if final.get("result") else "N/A"
            print(f"  [{status}] {job['id'][:8]}... tokens={tokens} title={title}")

        elapsed = time.time() - start

        # Report
        completed = sum(1 for r in results if r["status"] == "completed")
        failed = sum(1 for r in results if r["status"] == "failed")
        total_tokens = sum(
            r.get("token_usage", {}).get("total_tokens", 0)
            for r in results if r.get("token_usage")
        )

        print(f"\n  === RESULTS ===")
        print(f"  Completed: {completed}/5")
        print(f"  Failed:    {failed}/5")
        print(f"  Total time: {elapsed:.1f}s")
        print(f"  Total tokens: {total_tokens}")
        print(f"  Avg time/job: {elapsed / 5:.1f}s")

        # Assert all reached terminal state
        for r in results:
            assert r["status"] in ("completed", "failed"), f"Job stuck: {r['id']} status={r['status']}"

        # Assert at least 4 of 5 completed (some PDFs may be flaky)
        assert completed >= 4, f"Only {completed}/5 completed. Errors: {[r['error'] for r in results if r['status'] == 'failed']}"

        # Verify result schema for completed jobs
        for r in results:
            if r["status"] == "completed":
                result = r["result"]
                assert "title" in result
                assert "sections" in result
                assert len(result["sections"]) >= 1
                assert 0 <= result["overall_confidence"] <= 1
                assert "key_topics" in result
                assert r["token_usage"]["total_tokens"] > 0
