"""FastAPI application for webhook-based event-driven execution."""

import logging
from typing import Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from durable_monty.service import OrchestratorService
from durable_monty.models import Call

logger = logging.getLogger(__name__)


class JobResult(BaseModel):
    """Result payload from executor webhook."""
    job_id: str
    result: Any
    status: str = "finished"  # finished or failed
    error: str | None = None


def create_app(service: OrchestratorService) -> FastAPI:
    """Create FastAPI app with webhook endpoints."""
    app = FastAPI(title="Durable Monty", description="Durable functions orchestrator")

    @app.post("/webhook/complete")
    async def webhook_complete(payload: JobResult):
        """
        Webhook endpoint for executors to report job completion.

        Used by event-driven executors (Lambda, Modal, etc) to push results
        instead of being polled by the worker.
        """
        try:
            logger.info(f"Webhook received for job {payload.job_id[:8]}: {payload.status}")

            # Find the call by job_id
            with Session(service.engine) as session:
                call = session.query(Call).filter_by(job_id=payload.job_id).first()

                if not call:
                    raise HTTPException(status_code=404, detail=f"Job {payload.job_id} not found")

                if payload.status == "finished":
                    # Complete the call
                    service.complete_call(
                        call.execution_id,
                        call.call_id,
                        payload.result
                    )
                    logger.info(f"Completed call {call.call_id} for execution {call.execution_id[:8]}")

                elif payload.status == "failed":
                    # Mark as failed
                    call.status = "failed"
                    call.error = payload.error or "Unknown error"
                    session.commit()
                    logger.error(f"Job {payload.job_id[:8]} failed: {call.error}")

                return {"status": "ok", "execution_id": call.execution_id, "call_id": call.call_id}

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing webhook: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/executions/{execution_id}")
    async def get_execution(execution_id: str):
        """Get execution status."""
        result = service.poll(execution_id)
        if not result:
            raise HTTPException(status_code=404, detail="Execution not found")
        return result

    @app.get("/executions")
    async def list_executions():
        """List all executions."""
        return service.poll()

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok"}

    return app
